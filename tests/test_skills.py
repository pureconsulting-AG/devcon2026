from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from lcc.agent.sandbox import Confirmer, Sandbox
from lcc.agent.tools import ToolContext, ToolError, available_tool_names, default_registry
from lcc.agent.verify import expand, last_test_file
from lcc.config import Config, default_config
from lcc.ollama_client import OllamaClient, ToolCall
from lcc.rag.store import Store
from lcc.skills.active import SkillSession, prepare_task, run_skill_checks
from lcc.skills.linter import lint_paths
from lcc.skills.loader import (
    load_skill_file,
    load_skills,
    parse_frontmatter,
    parse_list,
)
from lcc.skills.scaffold import EXAMPLE, ScaffoldError, create_skill
from lcc.skills.selector import SkillSelector, matching_trigger
from tests.fake_ollama import FakeOllama, keyword_embedding


def write_skill(base: Path, folder: str, **fields: str) -> Path:
    body = fields.pop("body", "# Titel\n\n1. Schritt")
    front = {"name": folder, "description": f"Beschreibung von {folder}", **fields}
    lines = ["---", *(f"{k}: {v}" for k, v in front.items() if v != ""), "---", "", body]
    path = base / folder / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / ".git").mkdir(parents=True)
    return root


def config_for(project: Path, user_skills: Path | None = None, **skills: Any) -> Config:
    config = default_config(project)
    paths = (project / ".lcc" / "skills", user_skills or project.parent / "user-skills")
    return dataclasses.replace(
        config,
        skills=dataclasses.replace(config.skills, paths=paths, **skills),
        rag=dataclasses.replace(config.rag, index_path=project / ".lcc" / "index.db"),
    )


# -- Parser ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a, b, c", ("a", "b", "c")),
        ("[a, b]", ("a", "b")),
        ("[\"test schreiben\", 'unit-test']", ("test schreiben", "unit-test")),
        ("", ()),
        ("[ ]", ()),
        ("einzeln", ("einzeln",)),
    ],
)
def test_parse_list(raw: str, expected: tuple[str, ...]) -> None:
    assert parse_list(raw) == expected


def test_parse_frontmatter_fields_body_and_warnings() -> None:
    text = (
        '---\nname: x\n# Kommentar\ndescription: "Mit: Doppelpunkt"\nfarbe: blau\n'
        "kaputte zeile\n---\n\n# Body\n"
    )
    fields, body, warnings = parse_frontmatter(text)
    assert fields == {"name": "x", "description": "Mit: Doppelpunkt"}
    assert body == "# Body"
    assert any("farbe" in w for w in warnings)
    assert any("Zeile 6" in w for w in warnings)


def test_load_skill_file_all_fields(tmp_path: Path) -> None:
    path = tmp_path / "pytest-test" / "SKILL.md"
    path.parent.mkdir()
    path.write_text(EXAMPLE, encoding="utf-8")
    skill, warnings = load_skill_file(path, "project")
    assert warnings == []
    assert skill is not None
    assert skill.name == "pytest-test"
    assert "tests" in skill.triggers
    assert skill.tools == (
        "read_file",
        "list_dir",
        "search_code",
        "edit_file",
        "write_file",
        "run_shell",
    )
    assert skill.checks == ("python -m pytest -q {test_file}",)
    assert skill.context_files == ("pyproject.toml", "tests/conftest.py")
    assert skill.model == "code"
    assert skill.version == 1
    assert skill.body.startswith("# pytest-Tests schreiben")


@pytest.mark.parametrize("missing", ["name", "description"])
def test_missing_required_field_ignores_skill(tmp_path: Path, missing: str) -> None:
    path = write_skill(tmp_path, "a", **{missing: ""})
    skill, warnings = load_skill_file(path, "project")
    assert skill is None
    assert missing in warnings[-1]
    assert "ignoriert" in warnings[-1]


def test_missing_frontmatter(tmp_path: Path) -> None:
    path = tmp_path / "x" / "SKILL.md"
    path.parent.mkdir()
    path.write_text("# nur Body\n", encoding="utf-8")
    skill, warnings = load_skill_file(path, "project")
    assert skill is None
    assert "Frontmatter" in warnings[0]


def test_bad_version_is_warning(tmp_path: Path) -> None:
    skill, warnings = load_skill_file(write_skill(tmp_path, "a", version="zwei"), "project")
    assert skill is not None and skill.version is None
    assert "version" in warnings[0]


def test_project_skill_wins_over_user(project: Path, tmp_path: Path) -> None:
    user = tmp_path / "user-skills"
    write_skill(user, "doppelt", description="vom Benutzer")
    write_skill(user, "nur-user")
    write_skill(project / ".lcc" / "skills", "doppelt", description="vom Projekt")
    result = load_skills([user, project / ".lcc" / "skills"], project)
    assert result.skills["doppelt"].description == "vom Projekt"
    assert result.skills["doppelt"].source == "project"
    assert result.skills["nur-user"].source == "user"
    assert [(lo.source, wi.source) for lo, wi in result.shadowed] == [("user", "project")]


# -- Vorauswahl --------------------------------------------------------------


@pytest.mark.parametrize(
    ("task", "expected"),
    [
        ("schreib Tests für slugify", "tests"),
        ("Bitte PYTEST nutzen", "pytest"),
        ("einen Unit-Test ergänzen", "unit-test"),
        ("Test schreiben für foo", "test schreiben"),
        ("pytestify das", None),
        ("contests", None),
        ("attests", None),
    ],
)
def test_trigger_word_boundaries(tmp_path: Path, task: str, expected: str | None) -> None:
    skill, _ = load_skill_file(
        write_skill(tmp_path, "t", triggers="test schreiben, pytest, tests, unit-test"), "project"
    )
    assert skill is not None
    assert matching_trigger(task, skill) == expected


def skills_from(project: Path, specs: dict[str, dict[str, str]]) -> list[Any]:
    base = project / ".lcc" / "skills"
    for name, fields in specs.items():
        write_skill(base, name, **fields)
    return list(load_skills([base], project).skills.values())


def test_rank_sorting_and_max_listed(project: Path) -> None:
    skills = skills_from(
        project,
        {
            "c-skill": {"triggers": "katze"},
            "b-skill": {},
            "a-skill": {},
            "z-skill": {"triggers": "katze"},
        },
    )
    config = config_for(project, preselect="triggers", max_listed=3)
    selector = SkillSelector(config, skills)
    ranked = selector.rank("die katze")
    assert [m.skill.name for m in ranked] == ["c-skill", "z-skill", "a-skill", "b-skill"]
    assert [m.score for m in ranked] == [1.0, 1.0, 0.0, 0.0]
    assert [m.skill.name for m in selector.select("die katze")] == ["c-skill", "z-skill", "a-skill"]


def test_auto_load_threshold_and_limit(project: Path) -> None:
    skills = skills_from(project, {"a": {"triggers": "katze"}, "b": {"triggers": "katze"}})
    config = config_for(project, preselect="triggers", max_auto_load=1)
    ranked = SkillSelector(config, skills).rank("katze")
    assert [m.auto_load for m in ranked] == [True, False]
    strict = config_for(project, preselect="triggers", auto_load_min_score=1.5)
    assert not any(m.auto_load for m in SkillSelector(strict, skills).rank("katze"))


def test_preselect_off_lists_alphabetically_without_auto_load(project: Path) -> None:
    skills = skills_from(project, {"b": {"triggers": "katze"}, "a": {}})
    config = config_for(project, preselect="off")
    ranked = SkillSelector(config, skills).rank("katze")
    assert [m.skill.name for m in ranked] == ["a", "b"]
    assert not any(m.auto_load for m in ranked)


def test_embeddings_score_and_cache(project: Path) -> None:
    skills = skills_from(
        project,
        {
            "tiere": {"description": "Fragen zu katze und hund"},
            "server": {"description": "Fragen zum ollama server"},
        },
    )
    fake = FakeOllama(embed_fn=keyword_embedding)
    fake.add_model("bge-m3:latest")
    client = OllamaClient("http://x:1", transport=fake.transport())
    config = config_for(project)
    with Store(config.rag.index_path) as store:
        ranked = SkillSelector(config, skills, client, store).rank("meine katze")
        assert ranked[0].skill.name == "tiere"
        assert ranked[0].reason.startswith("Ähnlichkeit")
        assert ranked[0].score > ranked[1].score
        embeds = [b["input"] for p, b in fake.requests if p == "/api/embed"]
        assert (
            len(embeds) == 1 and len(embeds[0]) == 3
        )  # Auftrag + 2 Beschreibungen in EINER Anfrage
        SkillSelector(config, skills, client, store).rank("noch eine katze")
        embeds = [b["input"] for p, b in fake.requests if p == "/api/embed"]
        assert embeds[-1] == ["noch eine katze"]  # Beschreibungen kommen aus dem Cache


def test_trigger_beats_embedding(project: Path) -> None:
    skills = skills_from(project, {"tiere": {"description": "katze", "triggers": "hund"}})
    fake = FakeOllama(embed_fn=keyword_embedding)
    fake.add_model("bge-m3:latest")
    client = OllamaClient("http://x:1", transport=fake.transport())
    ranked = SkillSelector(config_for(project), skills, client).rank("der hund")
    assert ranked[0].score == 1.0
    assert "Trigger" in ranked[0].reason


def test_embedding_failure_falls_back_to_triggers(project: Path) -> None:
    skills = skills_from(project, {"a": {"triggers": "katze"}})
    fake = FakeOllama(embed_fn=keyword_embedding)  # Embedding-Modell fehlt → 404
    client = OllamaClient("http://x:1", transport=fake.transport())
    selector = SkillSelector(config_for(project), skills, client)
    ranked = selector.rank("katze")
    assert ranked[0].score == 1.0
    assert selector.warnings and "ohne Embeddings" in selector.warnings[0]


# -- Laufzeit ----------------------------------------------------------------


def make_context(project: Path, config: Config) -> ToolContext:
    return ToolContext(
        config=config,
        sandbox=Sandbox(project, config.workspace.ignore),
        confirmer=Confirmer(interactive=False, assume_yes=True),
    )


def test_load_skill_content_and_no_double_load(project: Path) -> None:
    (project / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    skills = skills_from(
        project, {"s": {"context_files": "pyproject.toml, fehlt.txt", "body": "BODY"}}
    )
    config = config_for(project)
    ctx = make_context(project, config)
    session = SkillSession(config, {s.name: s for s in skills})
    content = session.load("s", ctx)
    assert "BODY" in content
    assert str(skills[0].directory) in content
    assert "--- pyproject.toml ---" in content
    assert "fehlt.txt" not in content
    assert "bereits geladen" in session.load("s", ctx)
    with pytest.raises(ToolError, match="Unbekannter Skill"):
        session.load("gibtsnicht", ctx)


def test_skill_folder_outside_workspace_read_only(project: Path, tmp_path: Path) -> None:
    user = tmp_path / "user-skills"
    write_skill(user, "u", body="Siehe examples/beispiel.md")
    (user / "u" / "examples").mkdir()
    (user / "u" / "examples" / "beispiel.md").write_text("Beispiel!", encoding="utf-8")
    config = config_for(project, user_skills=user)
    skills = load_skills(config.skills.paths, project).skills
    ctx = make_context(project, config)
    ctx.skills = SkillSession(config, skills)
    registry = default_registry()
    example = str(user / "u" / "examples" / "beispiel.md")
    assert not registry.execute(ToolCall("read_file", {"path": example}), ctx).ok
    assert registry.execute(ToolCall("load_skill", {"name": "u"}), ctx).ok
    assert "Beispiel!" in registry.execute(ToolCall("read_file", {"path": example}), ctx).content
    written = registry.execute(ToolCall("write_file", {"path": example, "content": "x"}), ctx)
    assert not written.ok


def test_tools_intersection(project: Path) -> None:
    skills = skills_from(
        project, {"eng": {"tools": "read_file, run_shell, gibtsnicht"}, "frei": {}}
    )
    config = config_for(project)
    ctx = make_context(project, config)
    ctx.skills = SkillSession(config, {s.name: s for s in skills})
    registry = default_registry()
    before = available_tool_names(registry, ctx)
    assert "load_skill" in before and "write_file" in before
    ctx.skills.load("frei", ctx)
    assert available_tool_names(registry, ctx) == before
    ctx.skills.load("eng", ctx)
    assert available_tool_names(registry, ctx) == ["read_file", "run_shell"]


def test_skill_model_resolution(project: Path) -> None:
    skills = skills_from(project, {"a": {"model": "chat"}, "b": {"model": "other:3b"}})
    config = dataclasses.replace(
        config_for(project),
        models=dataclasses.replace(default_config(project).models, chat="chat-model:1b"),
    )
    session = SkillSession(config, {s.name: s for s in skills})
    ctx = make_context(project, config)
    assert session.model() is None
    session.load("a", ctx)
    assert session.model() == "chat-model:1b"
    session.load("b", ctx)
    assert session.model() == "other:3b"


def test_prepare_task_auto_loads_as_system_message(project: Path) -> None:
    skills = skills_from(
        project, {"pytest-test": {"triggers": "tests", "body": "SCHRITTE"}, "x": {}}
    )
    config = config_for(project, preselect="triggers")
    ctx = make_context(project, config)
    session = SkillSession(config, {s.name: s for s in skills})
    infos: list[str] = []
    prepared = prepare_task(session, ctx, "schreib Tests für slugify", None, on_info=infos.append)
    assert [s.name for s in prepared.listing] == ["pytest-test", "x"]
    assert prepared.auto_loaded == ["pytest-test"]
    assert prepared.preface[0]["role"] == "system"
    assert "SCHRITTE" in prepared.preface[0]["content"]
    assert infos == ["⚙ Skill: pytest-test"]
    again = prepare_task(session, ctx, "noch mehr Tests", None)
    assert again.preface == []  # nicht doppelt laden


# -- Checks ------------------------------------------------------------------


def test_placeholders() -> None:
    changed = ["src/a b.py", "tests/test_a.py"]
    assert expand("pytest {test_file}", changed, last_test_file(changed)) == (
        "pytest tests/test_a.py",
        None,
    )
    assert expand("ruff {changed}", changed, None) == ("ruff 'src/a b.py' tests/test_a.py", None)
    assert expand("pytest {test_file}", ["src/a.py"], None)[1] == "{test_file}"
    assert expand("ruff {changed}", [], None)[1] == "{changed}"
    assert last_test_file(["tests/x.py", "src/y.py", "tests/z.py"]) == "tests/z.py"


def test_checks_run_after_changes(project: Path) -> None:
    import sys

    skills = skills_from(
        project,
        {
            "s": {
                "checks": (
                    f'{sys.executable} -c "import sys; sys.exit(0)", '
                    f'{sys.executable} -c "import sys; sys.exit(3)" {{test_file}}'
                )
            }
        },
    )
    config = config_for(project)
    config = dataclasses.replace(
        config, agent=dataclasses.replace(config.agent, shell_allowlist=(sys.executable,))
    )
    ctx = make_context(project, config)
    ctx.skills = SkillSession(config, {s.name: s for s in skills})
    ctx.skills.load("s", ctx)
    assert run_skill_checks(ctx.skills, ctx, 0) == []  # keine Änderung → keine Checks

    registry = default_registry()
    registry.execute(ToolCall("write_file", {"path": "src/a.py", "content": "x = 1"}), ctx)
    outcomes = run_skill_checks(ctx.skills, ctx, 0)
    assert [o.ok for o in outcomes] == [True, True]
    assert outcomes[1].skipped

    registry.execute(ToolCall("write_file", {"path": "tests/test_a.py", "content": "x"}), ctx)
    outcomes = run_skill_checks(ctx.skills, ctx, 0)
    assert [o.ok for o in outcomes] == [True, False]
    assert outcomes[1].command.endswith("tests/test_a.py")


def test_check_denied_is_failure(project: Path) -> None:
    skills = skills_from(project, {"s": {"checks": "rm -rf ."}})
    config = config_for(project)
    ctx = make_context(project, config)
    ctx.skills = SkillSession(config, {s.name: s for s in skills})
    ctx.skills.load("s", ctx)
    default_registry().execute(ToolCall("write_file", {"path": "a.py", "content": "x"}), ctx)
    [outcome] = run_skill_checks(ctx.skills, ctx, 0)
    assert not outcome.ok
    assert "Allowlist" in outcome.output()
    assert (project / "a.py").exists()


# -- Scaffold + Linter -------------------------------------------------------


def test_scaffold_new_and_example(tmp_path: Path) -> None:
    path = create_skill(tmp_path, "changelog-eintrag")
    skill, warnings = load_skill_file(path, "project")
    assert skill is not None and warnings == []
    assert skill.name == "changelog-eintrag"
    assert "## Nicht tun" in skill.body
    with pytest.raises(ScaffoldError, match="überschrieben"):
        create_skill(tmp_path, "changelog-eintrag")
    with pytest.raises(ScaffoldError, match="Ungültiger"):
        create_skill(tmp_path, "Mein_Skill")
    example = create_skill(tmp_path, "pytest-test", example=True)
    assert example.read_text(encoding="utf-8") == EXAMPLE


def test_example_and_template_pass_linter(project: Path) -> None:
    base = project / ".lcc" / "skills"
    create_skill(base, "pytest-test", example=True)
    create_skill(base, "neu")
    findings = lint_paths([base], project, 6000)
    assert [f for f in findings if f.severity == "error"] == []


def test_linter_findings(project: Path, tmp_path: Path) -> None:
    base = project / ".lcc" / "skills"
    write_skill(base, "Gross_Name")
    write_skill(base, "anderer-ordner", name="falscher-name")
    write_skill(base, "lang", description="x" * 250, body="y" * 7000, triggers="katze")
    write_skill(base, "tools", tools="read_file, zaubern", checks="pytest {foo}", triggers="katze")
    write_skill(base, "kaputt", description="")
    user = tmp_path / "user-skills"
    write_skill(user, "lang", triggers="hund")
    findings = lint_paths([base, user], project, 6000)
    messages = [(f.severity, f.message) for f in findings]

    def has(severity: str, text: str) -> bool:
        return any(s == severity and text in m for s, m in messages)

    assert has("error", "kebab-case")
    assert has("error", "Ordnernamen")
    assert has("warning", "250 Zeichen")
    assert has("warning", "7000 Zeichen")
    assert has("error", "zaubern")
    assert has("error", "{foo}")
    assert has("error", "Pflichtfelder fehlen")
    assert has("warning", "verdeckt")
    assert has("warning", "Trigger 'katze'")


def test_skill_loaded_mid_run_restricts_tools_and_switches_model(project: Path) -> None:
    from lcc.agent.loop import AgentEvents, create_agent
    from tests.fake_ollama import stream_text, stream_tool_call

    skills = skills_from(project, {"eng": {"tools": "read_file", "model": "other:3b"}})
    config = config_for(project)
    ctx = make_context(project, config)
    ctx.skills = SkillSession(config, {s.name: s for s in skills})
    fake = FakeOllama(
        chat_replies=[stream_tool_call("load_skill", {"name": "eng"}), stream_text("fertig")]
    )
    fake.add_model("qwen3.5:9b").add_model("other:3b")
    infos: list[str] = []
    agent = create_agent(
        client=OllamaClient("http://x:1", transport=fake.transport()),
        context=ctx,
        model="qwen3.5:9b",
        events=AgentEvents(on_info=infos.append),
    )
    agent.run("x")
    chats = [b for p, b in fake.requests if p == "/api/chat"]
    assert "load_skill" in [t["function"]["name"] for t in chats[0]["tools"]]
    assert [t["function"]["name"] for t in chats[1]["tools"]] == ["read_file"]
    assert chats[0]["model"] == "qwen3.5:9b"
    assert chats[1]["model"] == "other:3b"
    assert infos == ["⚙ Skill: eng"]


def test_trigger_wins_tie_against_embedding(project: Path) -> None:
    skills = skills_from(project, {"a-embed": {}, "b-trigger": {"triggers": "katze"}})
    fake = FakeOllama(embed_fn=lambda text: [1.0, 0.0])  # alles gleich ähnlich (Score 1.0)
    fake.add_model("bge-m3:latest")
    client = OllamaClient("http://x:1", transport=fake.transport())
    ranked = SkillSelector(config_for(project), skills, client).rank("katze")
    assert [m.skill.name for m in ranked] == ["b-trigger", "a-embed"]
    assert ranked[0].auto_load and not ranked[1].auto_load


def test_two_trigger_matches_decided_by_similarity(project: Path) -> None:
    skills = skills_from(
        project,
        {
            "a-pytest": {"triggers": "tests", "description": "python pytest"},
            "b-abap": {"triggers": "tests", "description": "abap unit"},
        },
    )

    def embed(text: str) -> list[float]:
        return [1.0, 0.0] if "abap" in text.lower() else [0.0, 1.0]

    fake = FakeOllama(embed_fn=embed)
    fake.add_model("bge-m3:latest")
    client = OllamaClient("http://x:1", transport=fake.transport())
    ranked = SkillSelector(config_for(project), skills, client).rank("Tests in ABAP")
    assert [m.skill.name for m in ranked] == ["b-abap", "a-pytest"]
    assert ranked[0].auto_load


def test_precomputed_task_vector_saves_embedding_call(project: Path) -> None:
    import numpy as np

    skills = skills_from(project, {"tiere": {"description": "katze"}})
    fake = FakeOllama(embed_fn=keyword_embedding)
    fake.add_model("bge-m3:latest")
    client = OllamaClient("http://x:1", transport=fake.transport())
    config = config_for(project)
    with Store(config.rag.index_path) as store:
        SkillSelector(config, skills, client, store).rank("katze")  # Beschreibung cachen
        before = len(fake.requests)
        vector = np.asarray([keyword_embedding("katze")], dtype=np.float32)
        ranked = SkillSelector(config, skills, client, store, task_vector=vector).rank("katze")
        assert len(fake.requests) == before  # kein weiterer Embed-Aufruf
        assert ranked[0].score > 0.9
