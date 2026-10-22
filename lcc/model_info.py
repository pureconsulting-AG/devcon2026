"""Modellgröße und Fähigkeiten über /api/show, gecacht in ~/.local/state/lcc/models.json.

Cache-Schlüssel: Modellname + digest (aus /api/tags) – ein neu gepulltes Modell wird also
automatisch neu abgefragt.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from lcc.config import Config
from lcc.ollama_client import OllamaClient, normalize_model_name

DEFAULT_CACHE_PATH = Path("~/.local/state/lcc/models.json")

_SIZE = re.compile(r"^\s*([\d.]+)\s*([KMBT]?)\s*$", re.IGNORECASE)
_FACTORS = {"": 1e-9, "K": 1e-6, "M": 1e-3, "B": 1.0, "T": 1e3}


@dataclass(frozen=True)
class ModelDetails:
    name: str
    digest: str = ""
    parameter_size: str = ""
    capabilities: tuple[str, ...] = field(default_factory=tuple)

    @property
    def params_b(self) -> float | None:
        return parse_parameter_size(self.parameter_size)

    @property
    def tools(self) -> bool:
        return "tools" in self.capabilities

    @property
    def thinking(self) -> bool:
        return "thinking" in self.capabilities


def parse_parameter_size(value: str) -> float | None:
    """'9.7B' → 9.7, '566.70M' → 0.5667, '1.2T' → 1200.0 (Milliarden Parameter)."""
    match = _SIZE.match(value or "")
    if not match:
        return None
    try:
        number = float(match.group(1))
    except ValueError:
        return None
    return number * _FACTORS[match.group(2).upper()]


class ModelInfoCache:
    def __init__(self, path: Path | None = None) -> None:
        self.path = (path or DEFAULT_CACHE_PATH).expanduser()

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def get(self, name: str, digest: str) -> ModelDetails | None:
        entry = self._load().get(f"{normalize_model_name(name)}@{digest}")
        if not isinstance(entry, dict):
            return None
        return ModelDetails(
            name=str(entry.get("name", name)),
            digest=str(entry.get("digest", digest)),
            parameter_size=str(entry.get("parameter_size", "")),
            capabilities=tuple(str(c) for c in entry.get("capabilities", [])),
        )

    def put(self, details: ModelDetails) -> None:
        data = self._load()
        entry = asdict(details)
        entry["capabilities"] = list(details.capabilities)
        data[f"{normalize_model_name(details.name)}@{details.digest}"] = entry
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass  # Cache ist optional


def get_model_details(
    client: OllamaClient, name: str, cache: ModelInfoCache | None = None
) -> ModelDetails:
    """Größe + Fähigkeiten eines Modells (mit Cache über Name + digest)."""
    cache = cache or ModelInfoCache()
    wanted = normalize_model_name(name)
    digest = next(
        (m.digest for m in client.list_models() if normalize_model_name(m.name) == wanted), ""
    )
    if digest:
        cached = cache.get(name, digest)
        if cached is not None:
            return cached
    data = client.show_model(name)
    details = ModelDetails(
        name=name,
        digest=digest,
        parameter_size=str((data.get("details") or {}).get("parameter_size", "")),
        capabilities=tuple(str(c) for c in data.get("capabilities") or []),
    )
    if digest:
        cache.put(details)
    return details


def is_small_model(config: Config, details: ModelDetails, override: bool | None = None) -> bool:
    """Kleinmodell-Modus: CLI-Flag > mode on/off > auto (Größe ≤ auto_max_params_b)."""
    if override is not None:
        return override
    mode = config.small_model.mode
    if mode == "on":
        return True
    if mode == "off":
        return False
    size = details.params_b
    return size is not None and size <= config.small_model.auto_max_params_b
