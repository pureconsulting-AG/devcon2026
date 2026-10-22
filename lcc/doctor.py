"""Prüfungen für 'lcc doctor'. Liefert Ergebnisse schrittweise (Generator)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal

from lcc import texts
from lcc.config import Config
from lcc.ollama_client import (
    ModelInfo,
    OllamaClient,
    OllamaConnectionError,
    OllamaError,
    normalize_model_name,
)

Status = Literal["ok", "warn", "fail"]

DOCTOR_TOOL = {
    "type": "function",
    "function": {
        "name": "echo",
        "description": "Gibt den Text zurück.",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
}


@dataclass(frozen=True)
class Check:
    name: str
    status: Status
    detail: str = ""
    exit_code: int = 0


@dataclass
class ModelReport:
    name: str
    roles: list[str]
    present: bool
    parameter_size: str = ""
    capabilities: list[str] = field(default_factory=list)

    @property
    def tools(self) -> bool:
        return "tools" in self.capabilities

    @property
    def thinking(self) -> bool:
        return "thinking" in self.capabilities


def configured_models(config: Config) -> dict[str, list[str]]:
    """Modellname → Rollen ('code', 'chat', …); leere Namen werden ausgelassen."""
    roles: dict[str, list[str]] = {}
    candidates = [
        ("code", config.models.code),
        ("chat", config.models.chat),
        ("embed", config.models.embed),
        ("rerank", config.models.rerank),
        ("escalate", config.small_model.escalate_model),
    ]
    for role, name in candidates:
        if name:
            roles.setdefault(name, []).append(role)
    return roles


def find_model(name: str, available: list[ModelInfo]) -> ModelInfo | None:
    wanted = normalize_model_name(name)
    for model in available:
        if normalize_model_name(model.name) == wanted:
            return model
    return None


@dataclass
class DoctorRun:
    """Sammelt die Modell-Berichte, während run() die Checks liefert."""

    config: Config
    client: OllamaClient
    models: list[ModelReport] = field(default_factory=list)

    def run(self) -> Iterator[Check]:
        cfg = self.config
        try:
            available = self.client.list_models()
        except OllamaConnectionError as exc:
            yield Check(texts.DOCTOR_SERVER, "fail", str(exc), exc.exit_code)
            return
        except OllamaError as exc:
            yield Check(texts.DOCTOR_SERVER, "fail", str(exc), exc.exit_code)
            return
        yield Check(
            texts.DOCTOR_SERVER,
            "ok",
            texts.DOCTOR_SERVER_OK.format(url=cfg.ollama.base_url, count=len(available)),
        )

        for name, roles in configured_models(cfg).items():
            label = texts.DOCTOR_MODEL.format(name=name, roles=", ".join(roles))
            info = find_model(name, available)
            if info is None:
                self.models.append(ModelReport(name, roles, present=False))
                yield Check(label, "fail", texts.DOCTOR_PULL_HINT.format(model=name), 4)
                continue
            report = ModelReport(name, roles, present=True, parameter_size=info.parameter_size)
            try:
                details = self.client.show_model(name)
                capabilities = details.get("capabilities") or []
                report.capabilities = [str(item) for item in capabilities]
                report.parameter_size = (details.get("details") or {}).get(
                    "parameter_size", report.parameter_size
                )
            except OllamaError as exc:
                yield Check(label, "warn", str(exc))
                self.models.append(report)
                continue
            self.models.append(report)
            yield Check(label, "ok", report.parameter_size)

        yield from self._check_tool_calling()
        yield from self._check_embedding()

    def _report(self, name: str) -> ModelReport | None:
        wanted = normalize_model_name(name)
        for report in self.models:
            if normalize_model_name(report.name) == wanted:
                return report
        return None

    def _check_tool_calling(self) -> Iterator[Check]:
        model = self.config.models.code
        label = texts.DOCTOR_TOOLS.format(model=model)
        report = self._report(model)
        if report is None or not report.present:
            yield Check(label, "warn", texts.DOCTOR_SKIPPED_MISSING)
            return
        if report.capabilities and not report.tools:
            yield Check(label, "warn", texts.DOCTOR_TOOLS_TEXT_MODE)
            return
        try:
            result = self.client.chat(
                model,
                [{"role": "user", "content": texts.DOCTOR_TOOLS_PROMPT}],
                tools=[DOCTOR_TOOL],
                options=dict(self.config.models.options),
                think=self._think(model, report),
            )
        except OllamaError as exc:
            yield Check(label, "fail", str(exc), exc.exit_code)
            return
        if any(call.name == "echo" for call in result.tool_calls):
            yield Check(label, "ok", texts.DOCTOR_TOOLS_OK)
        else:
            yield Check(label, "warn", texts.DOCTOR_TOOLS_NONE)

    def _think(self, model: str, report: ModelReport) -> bool | None:
        if self.config.models.thinking.enabled:
            return True
        return False if report.thinking else None

    def _check_embedding(self) -> Iterator[Check]:
        model = self.config.models.embed
        if not model:
            return
        label = texts.DOCTOR_EMBED.format(model=model)
        report = self._report(model)
        if report is None or not report.present:
            yield Check(label, "warn", texts.DOCTOR_SKIPPED_MISSING)
            return
        try:
            [vector] = self.client.embed(model, ["lcc doctor"])
        except OllamaError as exc:
            yield Check(label, "fail", str(exc), exc.exit_code)
            return
        yield Check(label, "ok", texts.DOCTOR_EMBED_OK.format(dimension=len(vector)))


def exit_code_for(checks: list[Check]) -> int:
    """Höchste Priorität: Server (3) vor Modell fehlt (4) vor sonstigen Fehlern (1)."""
    codes = {check.exit_code for check in checks if check.status == "fail"}
    for code in (3, 4, 1):
        if code in codes:
            return code
    return 1 if codes else 0
