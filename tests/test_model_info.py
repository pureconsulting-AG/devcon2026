from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from lcc.config import default_config
from lcc.model_info import (
    ModelDetails,
    ModelInfoCache,
    get_model_details,
    is_small_model,
    parse_parameter_size,
)
from lcc.ollama_client import OllamaClient
from tests.fake_ollama import FakeOllama


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("9.7B", 9.7), ("566.70M", 0.5667), ("1.2T", 1200.0), ("30B", 30.0), ("", None), ("x", None)],
)
def test_parse_parameter_size(raw: str, expected: float | None) -> None:
    result = parse_parameter_size(raw)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


def test_get_model_details_uses_cache_by_digest(tmp_path: Path) -> None:
    fake = FakeOllama().add_model("qwen3.5:9b", "9.7B", ("completion", "tools", "thinking"))
    client = OllamaClient("http://x:1", transport=fake.transport())
    cache = ModelInfoCache(tmp_path / "models.json")

    details = get_model_details(client, "qwen3.5:9b", cache)
    assert details.params_b == pytest.approx(9.7)
    assert details.tools and details.thinking
    assert details.digest == "sha-qwen3.5:9b"
    assert fake.paths().count("/api/show") == 1

    again = get_model_details(client, "qwen3.5:9b", cache)
    assert again == details
    assert fake.paths().count("/api/show") == 1  # aus dem Cache
    assert (tmp_path / "models.json").is_file()


def test_new_digest_invalidates_cache(tmp_path: Path) -> None:
    cache = ModelInfoCache(tmp_path / "models.json")
    cache.put(ModelDetails("m:1b", "alt", "1B", ("completion",)))
    fake = FakeOllama().add_model("m:1b", "1B", ("completion", "tools"))
    client = OllamaClient("http://x:1", transport=fake.transport())
    details = get_model_details(client, "m:1b", cache)
    assert details.tools  # neu abgefragt, weil digest anders
    assert fake.paths().count("/api/show") == 1


def test_broken_cache_file_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "models.json"
    path.write_text("{kaputt", encoding="utf-8")
    assert ModelInfoCache(path).get("m", "d") is None


@pytest.mark.parametrize(
    ("mode", "size", "override", "expected"),
    [
        ("auto", "9.7B", None, True),
        ("auto", "14B", None, True),
        ("auto", "27B", None, False),
        ("auto", "", None, False),
        ("on", "70B", None, True),
        ("off", "3B", None, False),
        ("off", "3B", True, True),
        ("auto", "3B", False, False),
    ],
)
def test_is_small_model(mode: str, size: str, override: bool | None, expected: bool) -> None:
    config = default_config()
    config = dataclasses.replace(
        config, small_model=dataclasses.replace(config.small_model, mode=mode)
    )
    assert is_small_model(config, ModelDetails("m", parameter_size=size), override) is expected
