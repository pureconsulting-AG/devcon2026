"""typer-App mit allen Befehlen."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from lcc import texts
from lcc.agent.loop import create_agent
from lcc.agent.prompts import SkillListing
from lcc.agent.sandbox import Confirmer, Sandbox
from lcc.agent.small_model import SmallModelRunner
from lcc.agent.tools import ToolContext
from lcc.config import (
    CliOverrides,
    Config,
    ConfigError,
    LoadedConfig,
    effective_as_json,
    format_effective,
    init_user_config,
    load_config,
)
from lcc.doctor import Check, DoctorRun, ModelReport, configured_models, exit_code_for
from lcc.model_info import ModelDetails, get_model_details, is_small_model
from lcc.ollama_client import Message, OllamaClient, OllamaError, model_available
from lcc.output import ChatRenderer, emit_json, small_events
from lcc.rag.indexer import Indexer
from lcc.rag.search import format_hits, open_searcher, require_searcher
from lcc.rag.store import RagError, Store
from lcc.skills.active import (
    SkillSession,
    discover,
    loader_messages,
    prepare_task,
    run_skill_checks,
)

EXIT_OK = 0
EXIT_TASK_ERROR = 1
EXIT_CONFIG_ERROR = 2
EXIT_SERVER_UNREACHABLE = 3
EXIT_MODEL_MISSING = 4
EXIT_ABORTED = 130

app = typer.Typer(no_args_is_help=False, add_completion=False, help="lcc – local code cli")
config_app = typer.Typer(help="Config anzeigen oder anlegen.", no_args_is_help=True)
app.add_typer(config_app, name="config")
rag_app = typer.Typer(help="RAG-Index aufbauen und durchsuchen.", no_args_is_help=True)
app.add_typer(rag_app, name="rag")
skills_app = typer.Typer(help="Mini-Skills auflisten, anzeigen, anlegen und prüfen.")
app.add_typer(skills_app, name="skills")


@dataclass
class GlobalOptions:
    config_path: Path | None
    url: str | None
    model: str | None
    no_rag: bool
    no_skills: bool
    json_output: bool
    show_thinking: bool
    verbose: bool

    def load(self, console: Console) -> LoadedConfig:
        """Config laden; bei Fehlern Exit 2. Warnungen nach stderr."""
        try:
            loaded = load_config(
                config_path=self.config_path,
                overrides=CliOverrides(url=self.url, model=self.model),
            )
        except ConfigError as exc:
            if self.json_output:
                emit_json({"type": "error", "message": str(exc), "exit_code": EXIT_CONFIG_ERROR})
            else:
                console.print(f"[red]{escape(str(exc))}[/red]")
            raise typer.Exit(EXIT_CONFIG_ERROR) from exc
        for warning in loaded.warnings:
            console.print(f"[yellow]{escape(warning)}[/yellow]")
        return loaded


def _err_console() -> Console:
    return Console(stderr=True)


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    config: Annotated[
        Path | None, typer.Option("--config", help="Zusätzliche Config-Datei.")
    ] = None,
    url: Annotated[str | None, typer.Option("--url", help="Ollama-URL überschreiben.")] = None,
    model: Annotated[str | None, typer.Option("--model", help="Modell überschreiben.")] = None,
    no_rag: Annotated[bool, typer.Option("--no-rag", help="RAG abschalten.")] = False,
    no_skills: Annotated[bool, typer.Option("--no-skills", help="Skills abschalten.")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="Maschinenlesbare Ausgabe.")] = False,
    show_thinking: Annotated[
        bool, typer.Option("--show-thinking", help="Thinking-Ausgabe anzeigen.")
    ] = False,
    verbose: Annotated[bool, typer.Option("-v", "--verbose", help="Mehr Ausgaben.")] = False,
) -> None:
    ctx.obj = GlobalOptions(
        config_path=config,
        url=url,
        model=model,
        no_rag=no_rag,
        no_skills=no_skills,
        json_output=json_output,
        show_thinking=show_thinking,
        verbose=verbose,
    )
    if ctx.invoked_subcommand is None:
        start_repl(ctx.obj)


def start_repl(options: GlobalOptions) -> None:
    """Interaktiver Modus (lcc ohne Unterbefehl)."""
    from lcc.repl import Repl  # prompt_toolkit nur laden, wenn gebraucht

    loaded = options.load(_err_console())
    if not _stdin_is_tty():
        _err_console().print(texts.REPL_NO_TTY)
        raise typer.Exit(EXIT_TASK_ERROR)
    with make_client(loaded.config) as client:
        code = Repl(
            loaded,
            client,
            show_thinking=options.show_thinking,
            rag_enabled=not options.no_rag,
            skills_enabled=not options.no_skills,
        ).run()
    raise typer.Exit(code)


@config_app.command("show")
def config_show(ctx: typer.Context) -> None:
    """Effektive Config inkl. Quelle jedes Werts ausgeben."""
    options: GlobalOptions = ctx.obj
    loaded = options.load(_err_console())
    if options.json_output:
        payload = {
            "files": [str(path) for path in loaded.files],
            "values": effective_as_json(loaded),
        }
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if loaded.files:
        typer.echo(f"# {texts.CONFIG_SHOW_FILES}")
        for path in loaded.files:
            typer.echo(f"#   {path}")
    else:
        typer.echo(f"# {texts.CONFIG_SHOW_NO_FILES}")
    typer.echo("")
    typer.echo(format_effective(loaded), nl=False)


@config_app.command("init")
def config_init(
    force: Annotated[bool, typer.Option("--force", help="Bestehende Datei überschreiben.")] = False,
) -> None:
    """config.example.toml nach ~/.config/lcc/config.toml schreiben."""
    console = _err_console()
    try:
        path = init_user_config(force=force)
    except FileExistsError as exc:
        console.print(f"[yellow]{escape(str(exc))}[/yellow]")
        raise typer.Exit(EXIT_TASK_ERROR) from exc
    console.print(texts.CONFIG_INIT_DONE.format(path=path))


def make_client(config: Config) -> OllamaClient:
    """Einziger Ort, an dem der Client entsteht (in Tests per monkeypatch ersetzt)."""
    return OllamaClient.from_config(config.ollama)


@contextmanager
def handle_errors(options: GlobalOptions) -> Iterator[None]:
    """Ollama-Fehler und Strg-C in Exit-Codes übersetzen."""
    try:
        yield
    except (OllamaError, RagError) as exc:
        code = exc.exit_code if isinstance(exc, OllamaError) else EXIT_TASK_ERROR
        if options.json_output:
            emit_json({"type": "error", "message": str(exc), "exit_code": code})
        else:
            _err_console().print(f"[red]{escape(str(exc))}[/red]", highlight=False)
        raise typer.Exit(code) from exc
    except KeyboardInterrupt as exc:
        _err_console().print(texts.ABORTED)
        raise typer.Exit(EXIT_ABORTED) from exc


def _stdin_is_tty() -> bool:
    """Bestätigungen sind nur möglich, wenn stdin ein Terminal ist."""
    return sys.stdin is not None and sys.stdin.isatty()


def _read_stdin() -> str:
    """stdin nur lesen, wenn etwas hineingepiped wurde."""
    stream = sys.stdin
    if stream is None or stream.isatty():
        return ""
    return stream.read()


@app.command()
def ask(
    ctx: typer.Context,
    question: Annotated[str | None, typer.Argument(help="Frage.")] = None,
) -> None:
    """Einmalige Antwort ohne Tools (Modell 'chat'). stdin wird als Kontext angehängt."""
    options: GlobalOptions = ctx.obj
    loaded = options.load(_err_console())
    cfg = loaded.config
    stdin_text = _read_stdin().strip("\n")
    if not question and not stdin_text:
        _err_console().print(texts.ASK_NO_INPUT)
        raise typer.Exit(EXIT_TASK_ERROR)
    if question and stdin_text:
        content = texts.ASK_WITH_STDIN.format(question=question, stdin=stdin_text)
    else:
        content = question or stdin_text

    renderer = ChatRenderer(
        json_mode=options.json_output,
        markdown=cfg.ui.markdown,
        show_thinking=options.show_thinking,
    )
    with handle_errors(options), make_client(cfg) as client:
        try:
            renderer.start_waiting()
            content, sources = _with_rag_context(cfg, client, options, question or content, content)
            if sources and not options.json_output:
                renderer.stop_waiting()
                _err_console().print(
                    texts.RAG_USED.format(sources=", ".join(sources)), style="dim", markup=False
                )
                renderer.start_waiting()
            result = client.chat(
                cfg.models.chat,
                [{"role": "user", "content": content}],
                options=dict(cfg.models.options),
                think=client.think_param(cfg.models.chat, cfg.models.thinking.enabled),
                on_chunk=renderer.on_chunk,
            )
        except BaseException:
            renderer.abort()
            raise
        renderer.finish(result, model=cfg.models.chat, sources=sources)


def _with_rag_context(
    cfg: Config, client: OllamaClient, options: GlobalOptions, query: str, content: str
) -> tuple[str, list[str]]:
    """Für 'ask': passende RAG-Treffer vor die Frage stellen (falls Index vorhanden)."""
    searcher = open_searcher(cfg, client, enabled=not options.no_rag)
    if searcher is None:
        return content, []
    try:
        hits = searcher.search(query)
    finally:
        searcher.store.close()
    if not hits:
        return content, []
    intro = texts.RAG_CONTEXT_INTRO.format(hits=format_hits(hits))
    sources = [f"[{h.rank}] {h.path}:{h.start_line}-{h.end_line}" for h in hits]
    return f"{intro}\n\n{content}", sources


@app.command()
def run(
    ctx: typer.Context,
    task: Annotated[str | None, typer.Argument(help="Auftrag.")] = None,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes", "-y", help="Schreiben ohne Rückfrage (Shell bleibt bestätigungspflichtig)."
        ),
    ] = False,
    small: Annotated[
        bool | None,
        typer.Option("--small/--no-small", help="Kleinmodell-Modus erzwingen / abschalten."),
    ] = None,
) -> None:
    """Einmaliger Agent-Lauf mit Tools (Modell 'code'). stdin wird als Kontext angehängt."""
    options: GlobalOptions = ctx.obj
    cfg = options.load(_err_console()).config
    interactive = _stdin_is_tty()
    stdin_text = _read_stdin().strip("\n")
    if not task and not stdin_text:
        _err_console().print(texts.RUN_NO_TASK)
        raise typer.Exit(EXIT_TASK_ERROR)
    if task and stdin_text:
        content = texts.ASK_WITH_STDIN.format(question=task, stdin=stdin_text)
    else:
        content = task or stdin_text

    renderer = ChatRenderer(
        json_mode=options.json_output,
        markdown=cfg.ui.markdown,
        show_thinking=options.show_thinking,
        show_tool_calls=cfg.ui.show_tool_calls,
    )
    context = ToolContext(
        config=cfg,
        sandbox=Sandbox(cfg.workspace.root, cfg.workspace.ignore),
        confirmer=Confirmer(
            interactive=interactive,
            assume_yes=yes,
            confirm_writes=cfg.agent.confirm_writes,
            confirm_shell=cfg.agent.confirm_shell,
        ),
    )
    context.skills = _skill_session(options, cfg)
    context.confirmer.before_prompt = renderer.stop_waiting
    with handle_errors(options), make_client(cfg) as client:
        context.rag = open_searcher(cfg, client, enabled=not options.no_rag)
        details = get_model_details(client, cfg.models.code)
        context.small_mode = is_small_model(cfg, details, small)
        text_tools = bool(details.capabilities) and not details.tools
        try:
            renderer.start_waiting()
            listing: list[SkillListing] = []
            preface: list[Message] = []
            if context.skills is not None:
                prepared = prepare_task(
                    context.skills, context, task or content, client, on_info=renderer.info
                )
                listing, preface = prepared.listing, prepared.preface
            if context.small_mode:
                renderer.info(
                    texts.SMALL_MODE_ON.format(model=cfg.models.code, size=details.parameter_size)
                )
                runner = SmallModelRunner(
                    client=client,
                    context=context,
                    model=cfg.models.code,
                    events=small_events(renderer, context.confirmer, ask=interactive and not yes),
                    skills=listing,
                    text_tools=text_tools,
                )
                small_result = runner.run(content)
                renderer.end_message()
                ok = small_result.ok
                final_content = small_result.content
                extra: dict[str, Any] = {
                    "small_mode": True,
                    "repairs": small_result.repairs,
                    "escalated": small_result.escalated,
                    "checks_ok": all(c.ok for c in small_result.checks),
                }
                if not ok:
                    renderer.notice(small_result.aborted or texts.SKILL_CHECKS_FAILED_SUMMARY)
            else:
                agent = create_agent(
                    client=client,
                    context=context,
                    model=cfg.models.code,
                    events=renderer.agent_events(),
                    skills=listing,
                    text_tools=text_tools,
                )
                result = agent.run(content, preface=preface)
                renderer.end_message()
                outcomes = (
                    run_skill_checks(
                        context.skills,
                        context,
                        0,
                        on_outcome=renderer.check_outcome,
                        on_start=renderer.check_start,
                    )
                    if context.skills is not None
                    else []
                )
                checks_ok = all(outcome.ok for outcome in outcomes)
                if not checks_ok:
                    renderer.notice(texts.SKILL_CHECKS_FAILED_SUMMARY)
                ok = result.ok and checks_ok
                final_content = result.content
                extra = {
                    "small_mode": False,
                    "steps": result.steps,
                    "stop_reason": result.stop_reason,
                    "checks_ok": checks_ok,
                }
        except BaseException:
            renderer.abort()
            raise
        renderer.final(final_content, model=cfg.models.code, ok=ok, **extra)
    if not ok:
        raise typer.Exit(EXIT_TASK_ERROR)


def _skill_session(options: GlobalOptions, cfg: Config) -> SkillSession | None:
    """Skills laden (falls aktiv); Loader-Warnungen nach stderr."""
    if options.no_skills or not cfg.skills.enabled:
        return None
    result = discover(cfg)
    for message in loader_messages(result, options.verbose):
        _err_console().print(message, style="yellow", markup=False, highlight=False)
    return SkillSession(cfg, result.skills) if result.skills else None


@app.command()
def undo(ctx: typer.Context) -> None:
    """Letzte Dateiänderung des Agenten zurücknehmen (Backups in .lcc/undo/)."""
    options: GlobalOptions = ctx.obj
    cfg = options.load(_err_console()).config
    sandbox = Sandbox(cfg.workspace.root, cfg.workspace.ignore)
    change = sandbox.undo_last()
    console = _err_console()
    if options.json_output:
        payload: dict[str, Any] = {"type": "undo", "ok": change is not None}
        if change is not None:
            payload["path"] = sandbox.relpath(change.path)
            payload["action"] = "restored" if change.existed else "deleted"
        emit_json(payload)
        if change is None:
            raise typer.Exit(EXIT_TASK_ERROR)
        return
    if change is None:
        console.print(texts.UNDO_NOTHING)
        raise typer.Exit(EXIT_TASK_ERROR)
    template = texts.UNDO_RESTORED if change.existed else texts.UNDO_DELETED
    console.print(template.format(path=sandbox.relpath(change.path)), markup=False)


@rag_app.command("index")
def rag_index(
    ctx: typer.Context,
    rebuild: Annotated[
        bool, typer.Option("--rebuild", help="Index komplett neu aufbauen.")
    ] = False,
) -> None:
    """Quellen aus [rag].sources indexieren (inkrementell über Hash + mtime)."""
    from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn

    options: GlobalOptions = ctx.obj
    cfg = options.load(_err_console()).config
    console = _err_console()
    with handle_errors(options), make_client(cfg) as client, Store(cfg.rag.index_path) as store:
        indexer = Indexer(cfg, client, store)
        columns = (
            TextColumn(texts.RAG_INDEXING),
            BarColumn(),
            MofNCompleteColumn(),
            TextColumn("{task.description}", style="dim"),
        )
        with Progress(
            *columns, console=console, transient=True, disable=options.json_output
        ) as bar:
            task = bar.add_task("", total=None)

            def progress(done: int, total: int, name: str) -> None:
                bar.update(task, completed=done - 1, total=total, description=name)

            report = indexer.run(rebuild=rebuild, progress=progress)
        documents, chunks = store.stats()
    if options.json_output:
        typer.echo(
            json.dumps(
                {
                    **report.__dict__,
                    "missing_sources": [str(p) for p in report.missing_sources],
                    "documents": documents,
                    "chunks": chunks,
                }
            )
        )
        return
    if documents == 0 and report.removed == 0:
        console.print(
            texts.RAG_NO_SOURCES.format(sources=", ".join(str(s) for s in cfg.rag.sources)),
            style="yellow",
            markup=False,
        )
    console.print(
        texts.RAG_INDEX_DONE.format(
            added=report.added,
            updated=report.updated,
            unchanged=report.unchanged,
            removed=report.removed,
            documents=documents,
            chunks=chunks,
        ),
        markup=False,
    )
    if report.skipped:
        console.print(texts.RAG_SKIPPED.format(count=report.skipped), style="dim", markup=False)


@rag_app.command("search")
def rag_search_command(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="Suchanfrage.")],
    top_k: Annotated[int | None, typer.Option("--top-k", "-k", help="Anzahl Treffer.")] = None,
) -> None:
    """Index durchsuchen: Treffer mit Score, Datei und Zeilenbereich."""
    options: GlobalOptions = ctx.obj
    cfg = options.load(_err_console()).config
    with handle_errors(options), make_client(cfg) as client:
        searcher = require_searcher(cfg, client)
        try:
            hits = searcher.search(query, top_k=top_k)
        finally:
            searcher.store.close()
    if options.json_output:
        typer.echo(json.dumps([hit.__dict__ for hit in hits], ensure_ascii=False, indent=2))
        return
    if not hits:
        _err_console().print(
            texts.RAG_NO_HITS.format(min_score=cfg.rag.min_score, query=query), markup=False
        )
        raise typer.Exit(EXIT_TASK_ERROR)
    print_hits(Console(), hits)


def print_hits(console: Console, hits: list[Any]) -> None:
    for hit in hits:
        console.print(
            f"[bold][{hit.rank}][/bold] [cyan]{escape(hit.path)}:{hit.start_line}-{hit.end_line}"
            f"[/cyan] [dim](score {hit.score:.2f})[/dim]"
        )
        preview = hit.text if len(hit.text) <= 400 else hit.text[:400] + " …"
        console.print(preview, markup=False, highlight=False)
        console.print()


@rag_app.command("stats")
def rag_stats(ctx: typer.Context) -> None:
    """Anzahl Dateien/Chunks, Embedding-Modell und Dimension des Index."""
    options: GlobalOptions = ctx.obj
    cfg = options.load(_err_console()).config
    path = cfg.rag.index_path
    if not path.is_file():
        _err_console().print(texts.RAG_NO_INDEX.format(path=path), markup=False)
        raise typer.Exit(EXIT_TASK_ERROR)
    with Store(path) as store:
        documents, chunks = store.stats()
        data = {
            "path": str(path),
            "documents": documents,
            "chunks": chunks,
            "model": store.embed_model or "-",
            "dimension": store.dimension or "-",
        }
    if options.json_output:
        typer.echo(json.dumps(data))
        return
    typer.echo(texts.RAG_STATS.format(**data))


def _source_label(source: str) -> str:
    return texts.SKILL_SOURCE_PROJECT if source == "project" else texts.SKILL_SOURCE_USER


@skills_app.callback(invoke_without_command=True)
def skills_list(ctx: typer.Context) -> None:
    """Gefundene Skills mit Quelle (Projekt/Benutzer) und Beschreibung."""
    if ctx.invoked_subcommand is not None:
        return
    options: GlobalOptions = ctx.obj
    cfg = options.load(_err_console()).config
    result = discover(cfg)
    for message in loader_messages(result, options.verbose):
        _err_console().print(message, style="yellow", markup=False, highlight=False)
    skills = sorted(result.skills.values(), key=lambda s: s.name)
    if options.json_output:
        payload = [
            {"name": s.name, "source": s.source, "description": s.description, "path": str(s.path)}
            for s in skills
        ]
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if not skills:
        paths = ", ".join(str(p) for p in cfg.skills.paths)
        _err_console().print(texts.SKILL_NONE.format(paths=paths), markup=False)
        return
    table = Table(show_header=True)
    table.add_column("Skill")
    table.add_column(texts.SKILL_COL_SOURCE)
    table.add_column(texts.SKILL_COL_DESCRIPTION)
    for skill in skills:
        table.add_row(escape(skill.name), _source_label(skill.source), escape(skill.description))
    Console().print(table)


@skills_app.command("show")
def skills_show(
    ctx: typer.Context, name: Annotated[str, typer.Argument(help="Skill-Name.")]
) -> None:
    """Frontmatter und Body eines Skills anzeigen."""
    options: GlobalOptions = ctx.obj
    cfg = options.load(_err_console()).config
    skill = discover(cfg).skills.get(name)
    if skill is None:
        available = ", ".join(sorted(discover(cfg).skills))
        _err_console().print(
            texts.SKILL_UNKNOWN.format(name=name, available=available), markup=False
        )
        raise typer.Exit(EXIT_TASK_ERROR)
    if options.json_output:
        typer.echo(
            json.dumps(
                {"frontmatter": skill.frontmatter, "body": skill.body, "path": str(skill.path)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    typer.echo(f"# {skill.path} ({_source_label(skill.source)})")
    for key, value in skill.frontmatter.items():
        typer.echo(f"{key}: {value}")
    typer.echo("")
    typer.echo(skill.body)


@skills_app.command("new")
def skills_new(
    ctx: typer.Context,
    name: Annotated[str | None, typer.Argument(help="Skill-Name (kebab-case).")] = None,
    user: Annotated[bool, typer.Option("--user", help="Als Benutzer-Skill anlegen.")] = False,
    example: Annotated[
        bool, typer.Option("--example", help="Beispiel-Skill pytest-test anlegen.")
    ] = False,
) -> None:
    """Skill-Gerüst anlegen (Projekt-Skills, --user für Benutzer-Skills)."""
    from lcc.skills.scaffold import EXAMPLE_NAME, ScaffoldError, create_skill

    options: GlobalOptions = ctx.obj
    cfg = options.load(_err_console()).config
    name = name or (EXAMPLE_NAME if example else None)
    if name is None:
        _err_console().print(texts.SKILL_NEW_NO_NAME, markup=False)
        raise typer.Exit(EXIT_TASK_ERROR)
    base = _skill_base(cfg, user=user)
    try:
        path = create_skill(base, name, example=example)
    except ScaffoldError as exc:
        _err_console().print(str(exc), style="red", markup=False)
        raise typer.Exit(EXIT_TASK_ERROR) from exc
    _err_console().print(texts.SKILL_NEW_DONE.format(path=path), markup=False)


def _skill_base(cfg: Config, *, user: bool) -> Path:
    """Erster Projekt- bzw. Benutzer-Pfad aus skills.paths."""
    from lcc.skills.loader import classify_source

    wanted = "user" if user else "project"
    for path in cfg.skills.paths:
        if classify_source(path, cfg.workspace.root) == wanted:
            return path
    if user:
        return Path("~/.config/lcc/skills").expanduser()
    return cfg.workspace.root / ".lcc" / "skills"


@skills_app.command("check")
def skills_check(ctx: typer.Context) -> None:
    """Skills prüfen: Frontmatter, Länge, doppelte Namen, überlappende Trigger."""
    from lcc.skills.linter import lint_paths

    options: GlobalOptions = ctx.obj
    cfg = options.load(_err_console()).config
    findings = lint_paths(cfg.skills.paths, cfg.workspace.root, cfg.skills.max_body_chars)
    count = len(discover(cfg).all_skills)
    errors = sum(1 for f in findings if f.severity == "error")
    warnings = len(findings) - errors
    if options.json_output:
        payload = {
            "skills": count,
            "findings": [
                {"severity": f.severity, "path": str(f.path), "message": f.message}
                for f in findings
            ],
        }
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        console = Console()
        for finding in findings:
            style = "red" if finding.severity == "error" else "yellow"
            label = texts.LINT_ERROR if finding.severity == "error" else texts.LINT_WARNING
            console.print(
                f"[{style}]{label}[/{style}] {escape(str(finding.path))}: {escape(finding.message)}"
            )
        console.print(texts.LINT_SUMMARY.format(errors=errors, warnings=warnings, skills=count))
    if errors:
        raise typer.Exit(EXIT_TASK_ERROR)


@skills_app.command("match")
def skills_match(ctx: typer.Context, task: Annotated[str, typer.Argument(help="Auftrag.")]) -> None:
    """Zeigt, welche Skills mit welchem Score und Grund ausgewählt würden."""
    from lcc.skills.active import skill_cache
    from lcc.skills.selector import SkillSelector

    options: GlobalOptions = ctx.obj
    cfg = options.load(_err_console()).config
    skills = list(discover(cfg).skills.values())
    with handle_errors(options), make_client(cfg) as client:
        store = skill_cache(cfg)
        try:
            selector = SkillSelector(cfg, skills, client, store)
            ranked = selector.rank(task)
        finally:
            if store is not None:
                store.close()
    listed = {m.skill.name for m in ranked[: cfg.skills.max_listed]}
    for warning in selector.warnings:
        _err_console().print(warning, style="yellow", markup=False)
    if options.json_output:
        payload = [
            {
                "name": m.skill.name,
                "score": round(m.score, 4),
                "reason": m.reason,
                "listed": m.skill.name in listed,
                "auto_load": m.auto_load,
            }
            for m in ranked
        ]
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if not ranked:
        _err_console().print(
            texts.SKILL_NONE.format(paths=", ".join(str(p) for p in cfg.skills.paths)),
            markup=False,
        )
        return
    table = Table(show_header=True)
    table.add_column("Skill")
    table.add_column("Score", justify="right")
    table.add_column(texts.SKILL_COL_REASON)
    table.add_column(texts.SKILL_COL_STATUS)
    for match in ranked:
        if match.auto_load:
            status = texts.SKILL_MATCH_AUTO
        elif match.skill.name in listed:
            status = texts.SKILL_MATCH_LISTED
        else:
            status = texts.SKILL_MATCH_NOT_LISTED
        table.add_row(escape(match.skill.name), f"{match.score:.2f}", escape(match.reason), status)
    Console().print(table)


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{size} B"
        value /= 1024
    return f"{size} B"  # pragma: no cover


@app.command()
def models(ctx: typer.Context) -> None:
    """Modelle auf dem Server listen; markieren, was in der Config verwendet wird oder fehlt."""
    options: GlobalOptions = ctx.obj
    cfg = options.load(_err_console()).config
    with handle_errors(options), make_client(cfg) as client:
        available = client.list_models()
    roles = configured_models(cfg)
    names = [model.name for model in available]
    missing = {name: r for name, r in roles.items() if not model_available(name, names)}

    def roles_of(model_name: str) -> list[str]:
        return [
            role
            for name, role_list in roles.items()
            if model_available(name, [model_name])
            for role in role_list
        ]

    if options.json_output:
        payload: dict[str, Any] = {
            "models": [
                {
                    "name": model.name,
                    "parameter_size": model.parameter_size,
                    "quantization": model.quantization,
                    "size": model.size,
                    "roles": roles_of(model.name),
                }
                for model in available
            ],
            "missing": [{"name": name, "roles": r} for name, r in missing.items()],
        }
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    table = Table(title=texts.MODELS_TITLE.format(url=cfg.ollama.base_url))
    table.add_column(texts.MODELS_COL_NAME)
    table.add_column(texts.MODELS_COL_PARAMS, justify="right")
    table.add_column(texts.MODELS_COL_QUANT)
    table.add_column(texts.MODELS_COL_SIZE, justify="right")
    table.add_column(texts.MODELS_COL_ROLES)
    for model in sorted(available, key=lambda m: m.name):
        model_roles = roles_of(model.name)
        table.add_row(
            f"[bold]{escape(model.name)}[/bold]" if model_roles else escape(model.name),
            model.parameter_size,
            model.quantization,
            _format_bytes(model.size),
            ", ".join(model_roles),
        )
    console = Console()
    console.print(table)
    for name, r in missing.items():
        console.print(
            "[red]✗[/red] " + escape(texts.MODELS_MISSING.format(model=name, roles=", ".join(r))),
            highlight=False,
        )


_STATUS_ICON = {"ok": "[green]✓[/green]", "warn": "[yellow]![/yellow]", "fail": "[red]✗[/red]"}


@app.command()
def doctor(ctx: typer.Context) -> None:
    """Server, Modelle, Tool-Calling und Embedding-Dimension prüfen."""
    options: GlobalOptions = ctx.obj
    cfg = options.load(_err_console()).config
    console = Console()
    checks: list[Check] = []
    with handle_errors(options), make_client(cfg) as client:
        run = DoctorRun(cfg, client)
        if not options.json_output:
            console.print(texts.DOCTOR_RUNNING.format(url=cfg.ollama.base_url))
        for check in run.run():
            checks.append(check)
            if options.json_output:
                emit_json({"type": "check", **check.__dict__})
            else:
                console.print(
                    f"{_STATUS_ICON[check.status]} {escape(check.name)}: {escape(check.detail)}",
                    highlight=False,
                )

    present = [report for report in run.models if report.present]
    if present and not options.json_output:
        table = Table(title=texts.DOCTOR_TABLE_TITLE)
        for column in (
            texts.DOCTOR_COL_MODEL,
            texts.DOCTOR_COL_ROLES,
            texts.DOCTOR_COL_SIZE,
            texts.DOCTOR_COL_TOOLS,
            texts.DOCTOR_COL_THINKING,
            texts.DOCTOR_COL_SMALL,
        ):
            table.add_column(column)
        for report in present:
            known = bool(report.capabilities)
            small = _small_label(cfg, report)
            table.add_row(
                report.name,
                ", ".join(report.roles),
                report.parameter_size,
                _yes_no(report.tools, known),
                _yes_no(report.thinking, known),
                small,
            )
        console.print(table)
    elif options.json_output:
        for report in run.models:
            emit_json(
                {
                    "type": "model",
                    "name": report.name,
                    "roles": report.roles,
                    "present": report.present,
                    "parameter_size": report.parameter_size,
                    "tools": report.tools,
                    "thinking": report.thinking,
                    "small_model": _small_flag(cfg, report),
                }
            )
    code = exit_code_for(checks)
    if code:
        raise typer.Exit(code)


GENERATING_ROLES = frozenset({"code", "chat", "escalate"})


def _small_flag(cfg: Config, report: ModelReport) -> bool | None:
    """Kleinmodell-Modus für Chat-/Code-Modelle; None für reine Embedding-/Rerank-Modelle."""
    if not GENERATING_ROLES.intersection(report.roles):
        return None
    details = ModelDetails(report.name, "", report.parameter_size, tuple(report.capabilities))
    return is_small_model(cfg, details)


def _small_label(cfg: Config, report: ModelReport) -> str:
    flag = _small_flag(cfg, report)
    if flag is None:
        return "–"
    label = texts.YES if flag else texts.NO
    if report.capabilities and not report.tools:
        label += texts.DOCTOR_TEXT_TOOLS
    return label


def _yes_no(value: bool, known: bool) -> str:
    if not known:
        return texts.UNKNOWN
    return texts.YES if value else texts.NO


def main() -> None:
    app()
