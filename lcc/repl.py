"""Interaktiver Modus: prompt_toolkit-REPL mit Agent, Slash-Befehlen und Sessions.

Strg-C bricht die laufende Generierung ab (nicht die REPL); zweimal Strg-C beendet.
"""

from __future__ import annotations

import difflib
from collections.abc import Callable, Iterable
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import CompleteEvent, Completer, Completion, PathCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from rich.console import Console

from lcc import texts
from lcc.agent.loop import create_agent
from lcc.agent.prompts import SkillListing
from lcc.agent.sandbox import AskFn, Confirmer, Sandbox, render_diff
from lcc.agent.small_model import SmallModelRunner
from lcc.agent.tools import ToolContext, ToolError, default_registry
from lcc.config import LoadedConfig, format_effective
from lcc.model_info import ModelDetails, get_model_details, is_small_model
from lcc.ollama_client import Message, OllamaClient, OllamaError, ToolCall, model_available
from lcc.output import ChatRenderer, small_events
from lcc.rag.search import RagSearcher, format_hits, open_searcher
from lcc.rag.store import RagError
from lcc.session import Session, SessionError, list_sessions
from lcc.skills.active import SkillSession, discover, prepare_task, run_skill_checks

SLASH_COMMANDS: dict[str, str] = {
    "/help": texts.HELP_HELP,
    "/exit": texts.HELP_EXIT,
    "/clear": texts.HELP_CLEAR,
    "/model": texts.HELP_MODEL,
    "/models": texts.HELP_MODELS,
    "/rag": texts.HELP_RAG,
    "/skill": texts.HELP_SKILL,
    "/skills": texts.HELP_SKILLS,
    "/add": texts.HELP_ADD,
    "/diff": texts.HELP_DIFF,
    "/undo": texts.HELP_UNDO,
    "/save": texts.HELP_SAVE,
    "/load": texts.HELP_LOAD,
    "/config": texts.HELP_CONFIG,
}
ALIASES = {"/quit": "/exit", "/q": "/exit", "/?": "/help"}


class SlashCompleter(Completer):
    """Vervollständigt Slash-Befehle am Zeilenanfang und Pfade nach /add."""

    def __init__(self, workspace_root: Path) -> None:
        self._paths = PathCompleter(get_paths=lambda: [str(workspace_root)], expanduser=True)

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterable[Completion]:
        text = document.text_before_cursor
        if text.startswith("/add "):
            sub = Document(text[len("/add ") :])
            yield from self._paths.get_completions(sub, complete_event)
            return
        if text.startswith("/") and " " not in text:
            for command, description in SLASH_COMMANDS.items():
                if command.startswith(text):
                    yield Completion(command, -len(text), display_meta=description)


def _key_bindings() -> KeyBindings:
    bindings = KeyBindings()

    @bindings.add("escape", "enter")
    def _newline(event: KeyPressEvent) -> None:
        event.current_buffer.insert_text("\n")

    return bindings


class Repl:
    def __init__(
        self,
        loaded: LoadedConfig,
        client: OllamaClient,
        *,
        show_thinking: bool = False,
        rag_enabled: bool = True,
        skills_enabled: bool = True,
        console: Console | None = None,
        ask: AskFn | None = None,
    ) -> None:
        self.loaded = loaded
        self.config = loaded.config
        self.client = client
        self.show_thinking = show_thinking
        self.console = console or Console()
        cfg = self.config
        self.sandbox = Sandbox(cfg.workspace.root, cfg.workspace.ignore)
        self.confirmer = Confirmer(
            interactive=True,
            confirm_writes=cfg.agent.confirm_writes,
            confirm_shell=cfg.agent.confirm_shell,
            console=self.console,
            ask=ask,
        )
        self.context = ToolContext(config=cfg, sandbox=self.sandbox, confirmer=self.confirmer)
        self.session = Session(cfg.session.sessions_dir, autosave=cfg.session.save_sessions)
        self.model = cfg.models.code
        self.rag_enabled = cfg.rag.enabled and rag_enabled
        self._searcher: RagSearcher | None = None
        if self.rag_enabled:
            self._searcher = open_searcher(cfg, client)
            self.context.rag = self._searcher
        self.attachments: list[str] = []
        self.interrupted = False
        self._details: ModelDetails | None = None
        if skills_enabled and cfg.skills.enabled:
            found = discover(cfg)
            for warning in found.warnings:
                self.warn(warning)
            if found.skills:
                self.context.skills = SkillSession(cfg, found.skills)

    # -- Ausgabe ------------------------------------------------------------

    def info(self, text: str) -> None:
        self.console.print(text, markup=False, highlight=False)

    def warn(self, text: str) -> None:
        self.console.print(text, style="yellow", markup=False, highlight=False)

    def error(self, text: str) -> None:
        self.console.print(text, style="red", markup=False, highlight=False)

    # -- Hauptschleife ------------------------------------------------------

    def run(self, read_line: Callable[[], str] | None = None) -> int:
        read = read_line or self._prompt_session()
        self.info(texts.REPL_WELCOME.format(model=self.model, url=self.config.ollama.base_url))
        interrupts = 0
        while True:
            try:
                line = read()
            except KeyboardInterrupt:
                interrupts += 1
                if interrupts >= 2:
                    break
                self.warn(texts.REPL_CTRL_C_HINT)
                continue
            except EOFError:
                break
            if not self.handle_line(line):
                break
            interrupts = 1 if self.interrupted else 0
        self.info(texts.REPL_BYE)
        return 0

    def _prompt_session(self) -> Callable[[], str]:
        history_path = self.config.session.history_path
        history_path.parent.mkdir(parents=True, exist_ok=True)
        session: PromptSession[str] = PromptSession(
            history=FileHistory(str(history_path)),
            completer=SlashCompleter(self.sandbox.root),
            complete_while_typing=True,
            key_bindings=_key_bindings(),
        )
        return lambda: session.prompt(texts.REPL_PROMPT)

    def handle_line(self, line: str) -> bool:
        """Verarbeitet eine Eingabe. False = REPL beenden."""
        self.interrupted = False
        text = line.strip()
        if not text:
            return True
        if text.startswith("/"):
            return self.handle_command(text)
        self.ask_agent(text)
        return True

    # -- Agent --------------------------------------------------------------

    def ask_agent(self, text: str) -> None:
        content = "\n\n".join([*self.attachments, text]) if self.attachments else text
        self.attachments = []
        renderer = ChatRenderer(
            json_mode=False,
            markdown=self.config.ui.markdown,
            show_thinking=self.show_thinking,
            show_tool_calls=self.config.ui.show_tool_calls,
            console=self.console,
            err_console=self.console,
        )
        history = self.session.history()
        changes_before = len(self.sandbox.session_changes)
        self.confirmer.before_prompt = renderer.stop_waiting
        try:
            renderer.start_waiting()
            details = self._model_details()
            self.context.small_mode = is_small_model(self.config, details)
            text_tools = bool(details.capabilities) and not details.tools
            listing: list[SkillListing] = []
            preface: list[Message] = []
            if self.context.skills is not None:
                prepared = prepare_task(
                    self.context.skills, self.context, text, self.client, on_info=renderer.info
                )
                listing, preface = prepared.listing, prepared.preface
            if self.context.small_mode:
                self._run_small(renderer, content, history, listing, text_tools)
                return
            agent = create_agent(
                client=self.client,
                context=self.context,
                model=self.model,
                events=renderer.agent_events(),
                skills=listing,
                text_tools=text_tools,
            )
            result = agent.run(content, history=history, preface=preface)
            renderer.end_message()
            outcomes = (
                run_skill_checks(
                    self.context.skills,
                    self.context,
                    changes_before,
                    on_outcome=renderer.check_outcome,
                    on_start=renderer.check_start,
                )
                if self.context.skills is not None
                else []
            )
        except KeyboardInterrupt:
            renderer.abort()
            self.warn(texts.REPL_INTERRUPTED)
            self.interrupted = True
            return
        except (OllamaError, RagError) as exc:
            renderer.abort()
            self.error(str(exc))
            return
        renderer.done()
        # Neue Nachrichten = alles nach Systemprompt + bisherigem Verlauf (inkl. Skill-Bodies).
        self.session.extend(result.messages[1 + len(history) :])
        if not all(outcome.ok for outcome in outcomes):
            self.warn(texts.SKILL_CHECKS_FAILED_SUMMARY)

    def _model_details(self) -> ModelDetails:
        if self._details is None or self._details.name != self.model:
            self._details = get_model_details(self.client, self.model)
        return self._details

    def _run_small(
        self,
        renderer: ChatRenderer,
        content: str,
        history: list[Message],
        listing: list[SkillListing],
        text_tools: bool,
    ) -> None:
        """Kleinmodell-Modus: Plan (mit Dialog) → Schritte → Verify/Repair.

        In den Verlauf kommen nur Auftrag und Ergebnis – die Schritte bauen ihren Kontext
        ohnehin jedes Mal neu auf.
        """
        runner = SmallModelRunner(
            client=self.client,
            context=self.context,
            model=self.model,
            events=small_events(renderer, self.confirmer, ask=True),
            skills=listing,
            text_tools=text_tools,
            history=history,
        )
        result = runner.run(content)
        renderer.done()
        self.session.add({"role": "user", "content": content})
        if result.ok:
            self.session.add({"role": "assistant", "content": result.content})
        else:
            message = result.aborted or texts.SKILL_CHECKS_FAILED_SUMMARY
            self.session.add({"role": "assistant", "content": message})
            self.warn(message)

    # -- Slash-Befehle ------------------------------------------------------

    def handle_command(self, text: str) -> bool:
        command, _, arg = text.partition(" ")
        command = ALIASES.get(command.lower(), command.lower())
        arg = arg.strip()
        if command == "/exit":
            return False
        handler = {
            "/help": self.cmd_help,
            "/clear": self.cmd_clear,
            "/model": self.cmd_model,
            "/models": self.cmd_models,
            "/rag": self.cmd_rag,
            "/skill": self.cmd_skill,
            "/skills": self.cmd_skills,
            "/add": self.cmd_add,
            "/diff": self.cmd_diff,
            "/undo": self.cmd_undo,
            "/save": self.cmd_save,
            "/load": self.cmd_load,
            "/config": self.cmd_config,
        }.get(command)
        if handler is None:
            suggestion = difflib.get_close_matches(command, [*SLASH_COMMANDS, *ALIASES], n=1)
            hint = texts.REPL_DID_YOU_MEAN.format(command=suggestion[0]) if suggestion else ""
            self.warn(texts.REPL_UNKNOWN_COMMAND.format(command=command) + hint)
            return True
        try:
            handler(arg)
        except (OllamaError, RagError, SessionError) as exc:
            self.error(str(exc))
        return True

    def cmd_help(self, arg: str) -> None:
        width = max(len(command) for command in SLASH_COMMANDS)
        lines = [f"  {command:<{width}}  {text}" for command, text in SLASH_COMMANDS.items()]
        self.info(texts.REPL_HELP_HEADER + "\n" + "\n".join(lines) + "\n" + texts.REPL_HELP_KEYS)

    def cmd_clear(self, arg: str) -> None:
        self.session.clear()
        self.attachments = []
        self.info(texts.REPL_CLEARED)

    def cmd_model(self, arg: str) -> None:
        if not arg:
            self.info(texts.REPL_CURRENT_MODEL.format(model=self.model))
            return
        available = [model.name for model in self.client.list_models()]
        if not model_available(arg, available):
            self.error(texts.OLLAMA_MODEL_MISSING.format(model=arg, url=self.client.base_url))
            return
        self.model = arg
        self._details = None  # Kleinmodell-Modus für das neue Modell neu bestimmen
        self.info(texts.REPL_MODEL_SET.format(model=arg))

    def cmd_models(self, arg: str) -> None:
        for model in sorted(self.client.list_models(), key=lambda m: m.name):
            marker = "*" if model_available(self.model, [model.name]) else " "
            self.info(f"{marker} {model.name}  {model.parameter_size}")

    def cmd_rag(self, arg: str) -> None:
        if arg in ("on", "off"):
            self.rag_enabled = arg == "on"
            if self.rag_enabled and self._searcher is None:
                self._searcher = open_searcher(self.config, self.client)
                if self._searcher is None:
                    self.warn(texts.RAG_NO_INDEX.format(path=self.config.rag.index_path))
            self.context.rag = self._searcher if self.rag_enabled else None
            self.info(texts.REPL_RAG_STATE.format(state=arg))
            return
        if not arg:
            self.warn(texts.HELP_RAG)
            return
        if self._searcher is None:
            self.warn(texts.RAG_NO_INDEX.format(path=self.config.rag.index_path))
            return
        hits = self._searcher.search(arg)
        if not hits:
            self.info(texts.RAG_NO_HITS.format(min_score=self.config.rag.min_score, query=arg))
            return
        self.info(format_hits(hits))

    def cmd_skill(self, arg: str) -> None:
        skills = self.context.skills
        if skills is None:
            self.warn(texts.SKILL_DISABLED)
            return
        if not arg:
            self.warn(texts.HELP_SKILL)
            return
        if skills.is_loaded(arg):
            self.info(texts.SKILL_ALREADY_LOADED.format(name=arg))
            return
        try:
            content = skills.load(arg, self.context)
        except ToolError as exc:
            self.error(str(exc))
            return
        self.session.add({"role": "system", "content": content})
        self.console.print(
            texts.SKILL_LOADED.format(name=arg), style="cyan", markup=False, highlight=False
        )

    def cmd_skills(self, arg: str) -> None:
        skills = self.context.skills
        if skills is None or not skills.available:
            self.info(texts.SKILL_DISABLED if skills is None else texts.REPL_NO_SKILLS)
            return
        for name, skill in sorted(skills.available.items()):
            marker = "⚙" if skills.is_loaded(name) else " "
            self.info(f"{marker} {name}: {skill.description}")

    def cmd_add(self, arg: str) -> None:
        if not arg:
            self.warn(texts.REPL_ADD_USAGE)
            return
        result = default_registry().execute(ToolCall("read_file", {"path": arg}), self.context)
        if not result.ok:
            self.error(result.content)
            return
        self.attachments.append(result.content)
        self.info(texts.REPL_ADDED.format(header=result.content.splitlines()[0]))

    def cmd_diff(self, arg: str) -> None:
        diff = self.sandbox.session_diff()
        if not diff:
            self.info(texts.REPL_NO_CHANGES)
            return
        self.console.print(render_diff(diff))

    def cmd_undo(self, arg: str) -> None:
        change = self.sandbox.undo_last()
        if change is None:
            self.info(texts.UNDO_NOTHING)
            return
        template = texts.UNDO_RESTORED if change.existed else texts.UNDO_DELETED
        self.info(template.format(path=self.sandbox.relpath(change.path)))

    def cmd_save(self, arg: str) -> None:
        path = self.session.save(arg or None)
        self.info(texts.REPL_SAVED.format(path=path))

    def cmd_load(self, arg: str) -> None:
        directory = self.config.session.sessions_dir
        if not arg:
            sessions = list_sessions(directory)
            if not sessions:
                self.info(texts.REPL_NO_SESSIONS)
                return
            for info in sessions[:20]:
                stamp = info.modified.strftime("%Y-%m-%d %H:%M")
                self.info(
                    texts.REPL_SESSION_LINE.format(
                        id=info.session_id, modified=stamp, messages=info.messages
                    )
                )
            return
        self.session = Session.load(directory, arg, autosave=self.config.session.save_sessions)
        self.info(
            texts.REPL_LOADED.format(id=self.session.session_id, messages=len(self.session.records))
        )

    def cmd_config(self, arg: str) -> None:
        self.info(format_effective(self.loaded).rstrip("\n"))
