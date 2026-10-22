"""Optionaler Integrationstest gegen den echten Ollama-Server.

Läuft nur mit LCC_IT=1 und wird übersprungen, wenn der Server nicht erreichbar ist:
    LCC_IT=1 python -m pytest -q tests/test_integration.py
Nutzt die normale Config (Benutzer-/Projekt-Config, LCC_OLLAMA_URL, LCC_CODE_MODEL).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lcc import cli
from lcc.config import Config, load_config
from lcc.doctor import DOCTOR_TOOL, configured_models
from lcc.ollama_client import OllamaClient, OllamaConnectionError, model_available

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.environ.get("LCC_IT") != "1", reason="nur mit LCC_IT=1"),
]


@pytest.fixture(scope="module")
def config() -> Config:
    return load_config().config


@pytest.fixture(scope="module")
def client(config: Config) -> Iterator[OllamaClient]:
    client = OllamaClient.from_config(config.ollama)
    try:
        client.list_models()
    except OllamaConnectionError as exc:
        pytest.skip(f"Server nicht erreichbar: {exc}")
    yield client
    client.close()


def test_configured_models_present(config: Config, client: OllamaClient) -> None:
    names = [model.name for model in client.list_models()]
    missing = [name for name in configured_models(config) if not model_available(name, names)]
    assert missing == [], f"fehlen auf dem Server: {missing}"


def test_chat_streams_answer(config: Config, client: OllamaClient) -> None:
    chunks: list[str] = []
    result = client.chat(
        config.models.chat,
        [{"role": "user", "content": "Antworte nur mit dem Wort: hallo"}],
        think=client.think_param(config.models.chat, False),
        on_chunk=lambda chunk: chunks.append(chunk.content),
    )
    assert "hallo" in result.content.lower()
    assert len([c for c in chunks if c]) >= 1


def test_embedding_dimension(config: Config, client: OllamaClient) -> None:
    [vector] = client.embed(config.models.embed, ["lcc Integrationstest"])
    assert len(vector) >= 128


def test_native_tool_call(config: Config, client: OllamaClient) -> None:
    if "tools" not in client.capabilities(config.models.code):
        pytest.skip("Code-Modell ohne 'tools'-Fähigkeit (Text-Tool-Modus)")
    result = client.chat(
        config.models.code,
        [{"role": "user", "content": "Rufe das Tool echo mit text='ok' auf."}],
        tools=[DOCTOR_TOOL],
        think=client.think_param(config.models.code, False),
    )
    assert any(call.name == "echo" for call in result.tool_calls)


def test_run_end_to_end(
    client: OllamaClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "proj"
    (project / ".git").mkdir(parents=True)
    monkeypatch.chdir(project)
    result = CliRunner().invoke(
        cli.app,
        [
            "--no-rag",
            "--no-skills",
            "run",
            "--yes",
            "--no-small",
            "Lege die Datei hallo.txt mit dem Inhalt Hallo Welt an.",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Hallo Welt" in (project / "hallo.txt").read_text(encoding="utf-8")
