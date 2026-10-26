"""The agent loop: stream a turn from Claude, run its tools, repeat until done."""

import itertools
import json
import platform
import queue
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

import anthropic

from . import automode, events, memory, observer, sessions
from . import ui as term
from .checkpoints import CheckpointError, Checkpoints
from .mcp import MCPError
from .permissions import suggest_rule
from .plugins import TOOL_ALIASES, Extensions, hook_tool_input
from .procs import ProcessManager
import importlib.util

from . import care, context_repos, images, instructions, models, motion, tools
from .browser import SCHEMA as BROWSER_SCHEMA, Browser, BrowserError
from .lsp import SCHEMA as LSP_SCHEMA, LSPError, LSPManager
from .sandbox import Sandbox, SandboxUnavailable
from .tools import ToolError, _check, is_mutating, run_tool, tool_definitions, validate

DEFAULT_MODEL = "syntra"  # Bowers Syntra: the newest Opus, tuned for building software
BETAS = [
    "server-side-fallback-2026-07-01",   # re-run declined requests on a fallback model
    "thinking-display-updates-2026-08-18",  # show progress notes between tool calls
    "compact-2026-01-12",  # summarize old context server-side so long sessions keep going
]
MAX_HELPERS = 4
MAX_RETRIES = 6
MAX_STOP_HOOK_ROUNDS = 3
MODES = ("ask", "auto", "plan", "yolo")
NO_KEY = ("No API key was found, so Bowers can't reach Claude. Get a key at https://console.anthropic.com, "
          "then set it before starting Bowers: export ANTHROPIC_API_KEY=sk-ant-...  (or point ANTHROPIC_BASE_URL "
          "at Bowers Router).")
MAX_JSON_RETRIES = 2
MAX_MENTION_BYTES = 100_000


PROCESS_TOOLS = {
    "start_process": {
        "description": "Start a long-running command in the background, such as a dev server (npm run dev, "
                       "python -m http.server, uvicorn, flask run). Returns its first output and the local URL it "
                       "serves, which the user sees live in their preview. Use bash for commands that finish.",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    },
    "process_logs": {
        "description": "Read recent output of a background process (to check for errors after a change).",
        "properties": {"process_id": {"type": "integer"}, "lines": {"type": "integer"}},
        "required": ["process_id"],
    },
    "stop_process": {
        "description": "Stop a background process.",
        "properties": {"process_id": {"type": "integer"}},
        "required": ["process_id"],
    },
}


AGENT_TOOLS = {
    "update_plan": {
        "description": "Show the user your plan as a checklist and keep it current. Use it for tasks with several "
                       "steps: write the plan before starting, then update statuses as you go. Send the full list "
                       "each time.",
        "properties": {"items": {"type": "array", "items": {
            "type": "object",
            "properties": {"text": {"type": "string"},
                           "status": {"type": "string", "enum": ["pending", "in_progress", "done"]}},
            "required": ["text", "status"]}}},
        "required": ["items"],
    },
    "delegate": {
        "description": "Hand a self-contained piece of work to a helper agent with its own fresh context and the "
                       "same tools. Call it several times in one response to run helpers in parallel, e.g. "
                       "research different parts of a codebase, or build independent features in separate files. "
                       "The helper sees only your prompt, so include everything it needs (goal, files, "
                       "constraints, what to report back). Its final report is returned to you. Set background "
                       "to keep working while it runs; its report then arrives automatically later. Set agent "
                       "to use one of the specialized helper types listed in your instructions.",
        "properties": {
            "description": {"type": "string", "description": "3-6 words shown to the user"},
            "prompt": {"type": "string"},
            "agent": {"type": "string", "description": "optional helper type"},
            "background": {"type": "boolean"},
        },
        "required": ["description", "prompt"],
    },
    "ask_user": {
        "description": "Ask the user one to four multiple-choice questions when a decision is genuinely theirs "
                       "(scope, behavior, look, trade-offs) and guessing could waste their time. Offer 2-4 clear "
                       "options per question, put your recommended option first and say so in its label. The user "
                       "can also type their own answer. Don't use it for things you can find out yourself.",
        "properties": {"questions": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "header": {"type": "string", "description": "1-3 word label"},
                "options": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"label": {"type": "string"}, "description": {"type": "string"}},
                    "required": ["label"]}},
                "multi_select": {"type": "boolean"},
            },
            "required": ["question", "options"]}}},
        "required": ["questions"],
    },
    "exit_plan_mode": {
        "description": "Only in plan mode: when you've researched enough and your plan is ready, present it here "
                       "(markdown: what you'll change, file by file, and how you'll verify it). The user approves "
                       "it or asks for changes. You may only change files after approval.",
        "properties": {"plan": {"type": "string"}},
        "required": ["plan"],
    },
    "load_skill": {
        "description": "Load a skill: expert instructions for a kind of task. Load the matching skill before doing "
                       "a task it covers; the list of skills is in your instructions.",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
}
QUIET_TOOLS = {"update_plan", "load_skill"}  # never need approval and change nothing

COMPACT_PROMPT = """Summarize this conversation so you can continue the work from the summary alone. Include:
the user's goals and requests (quote important wording), decisions made and why, files created or changed and
what's in them now, commands that matter (how to build, test, run), problems found and how they were fixed,
what's still left to do, and anything the user asked you to remember. Be specific: names, paths, numbers.
Reply with the summary only."""

HELPER_NOTE = """
You are a helper agent doing one part of a larger task for a lead agent. The user doesn't see your messages;
your final message is returned to the lead agent, so end with a complete, concise report: what you did or
found, with file paths and anything left undone. Stay within the task you were given.
"""

PLAN_MODE_NOTE = ("<system-reminder>Plan mode is on. Research and plan only: read files, search, run read-only "
                  "commands, and ask questions if needed, but don't create, edit or delete files or run commands "
                  "that change anything. When your plan is ready, present it with exit_plan_mode.</system-reminder>")


class TurnAborted(Exception):
    pass


SYSTEM_PROMPT = """You are Bowers, an autonomous coding agent working in the user's terminal.
You can build anything the user asks for: apps, websites, scripts, APIs, games, tools.

How to work:
- Explore before changing things: list files, read the relevant code, check how the project builds and tests.
- Make real changes with your tools. Write complete, working code, not sketches or placeholders.
- Prefer edit_file for small changes to existing files and write_file for new files.
- After changing code, verify it: run it, build it, or run the tests, and fix what fails.
- Match the existing code style. Don't add features or refactors nobody asked for.
- For a new project, pick a sensible, mainstream stack unless the user specifies one, and include a README with how to run it.
- Ask the user only when a decision is genuinely theirs to make; use ask_user for that. Otherwise use good
  defaults and say what you chose.
- To run a web app (Vite, Next.js, Flask, FastAPI, Express…), start its dev server with start_process. The user
  sees it live in their preview, so prefer real running apps to describing them. Check process_logs after changes.
- For static sites, an index.html at the project root shows in the preview without a server.
- If the user attaches images (screenshots, mockups, designs), build the UI to match them closely.
- Files the user mentions with @path are attached to their message.
- Tools named mcp__<server>__<tool> come from MCP servers the user connected; use them when they fit the task.
- Use web_search and web_fetch to read current documentation when you're unsure how a library or API works.
- When you learn something worth keeping (a mistake you made, a fix that worked, a user preference,
  how this project builds), save it with the remember tool so future sessions do better.
- GitHub: when the user mentions an issue or pull request by number, read it with github_issue or github_pr.
  Do work on a feature branch, never commit straight to the default branch, never force-push, and open
  pull requests with create_pull_request. Write PR descriptions that explain what changed and why.
- Never run destructive commands (rm -rf outside the project, force pushes, dropping databases) unless the user asked.
- Finish with a short summary of what you did and how to run or check it.

Environment:
- Working directory: {cwd}
- Platform: {platform}
- Shell for bash and start_process: {shell}
- Date: {date}
"""


VOICE_NOTE = """<voice-mode>The person is talking to you out loud through Bowers Aether. Start your final reply
with one to three short, natural spoken sentences (no markdown, lists, code or links in them); they will be read aloud.
Put any details after that. Still do the work with your tools as usual.</voice-mode>"""


BROWSER_NOTE = """
Checking your UI work: after you build or change a web page, open it with the browser tool (the dev server URL,
or the HTML file) and look at the screenshot. Click through the main flow, fix any console errors it reports,
and check a mobile viewport too. Don't tell the user a page works until you've seen it work.
"""


def build_system_prompt(root: Path, ext: Extensions | None = None, style=None) -> str:
    prompt = SYSTEM_PROMPT.format(cwd=root, platform=platform.platform(), shell=care.shell_name(), date=date.today())
    prompt += care.CARE_NOTE
    if HAS_PLAYWRIGHT:
        prompt += BROWSER_NOTE
    written = instructions.system_section(root)
    if written:
        prompt += f"\n{written}\n"
    prompt += context_repos.system_note(root)
    lessons = memory.load(root)
    if lessons:
        prompt += f"\n{lessons}\n"
    if ext and ext.skills:
        prompt += "\nSkills (load the matching one with load_skill before doing a task it covers):\n" + "\n".join(
            f"- {s.name}: {s.description}" for s in ext.skills.values()) + "\n"
    if ext and ext.agents:
        prompt += "\nSpecialized helper types for delegate's agent parameter:\n" + "\n".join(
            f"- {a.name}: {a.description}" for a in ext.agents.values()) + "\n"
    if style is not None:
        prompt += f"\nOutput style ({style.name}): follow it in everything you write to the user.\n{style.prompt}\n"
    return prompt


HAS_PLAYWRIGHT = importlib.util.find_spec("playwright") is not None

SETTING_MODES = {"default": "ask", "ask": "ask", "plan": "plan", "auto": "auto", "acceptEdits": "ask",
                 "bypassPermissions": "yolo", "yolo": "yolo", "dontAsk": "yolo"}


def mode_from_settings(ext: Extensions) -> str:
    """The starting mode a settings file asks for ("defaultMode"); acceptEdits also allows edits in the project."""
    wanted = ext.permissions.default_mode if ext and ext.permissions else None
    if wanted == "acceptEdits":
        ext.permissions.add("allow", ["Edit(/**)"], ext.root)
    return SETTING_MODES.get(wanted or "", "ask")


def _block(b, name, default=None):
    return b.get(name, default) if isinstance(b, dict) else getattr(b, name, default)


@dataclass
class Agent:
    root: Path
    model: str = DEFAULT_MODEL
    effort: str | None = None   # low..max; None: the Bowers model's own setting (or high)
    auto_approve: bool = False   # same as mode "yolo"; kept for convenience
    mode: str = "ask"            # ask | auto | plan | yolo
    web: bool = True
    exclude_tools: tuple = ()  # tool names to leave out, e.g. when a runner handles PRs itself
    display: object = field(default_factory=lambda: term.TerminalUI())  # where output goes
    confirm: Callable[[str, dict], str] | None = None  # overrides display.confirm
    client: anthropic.Anthropic | None = None  # created from the environment if not given
    messages: list = field(default_factory=list)
    always_allowed: set = field(default_factory=set)
    usage: dict = field(default_factory=lambda: {"input": 0, "output": 0, "cache_read": 0})
    mcp: object = None    # an mcp.MCPManager, already started
    procs: object = None  # a procs.ProcessManager; created if not given
    helper: bool = False  # a helper started by another agent's delegate tool
    ext: Extensions | None = None  # commands, agents, skills and hooks; loaded if not given
    agent_type: object = None      # a plugins.AgentType, for specialized helpers
    save: bool = False             # keep this conversation in ~/.docks/sessions
    session_id: str = ""
    on_background_done: Callable | None = None  # called when a background helper finishes while idle
    output_style: str = ""          # default | explanatory | learning | concise | one from output-styles/
    sandbox: Sandbox | None = None  # run shell commands in a sandbox (see sandbox.py)
    browser: Browser | None = None  # shared with helpers; started on first use
    lsp: LSPManager | None = None   # language servers, shared with helpers; each starts on first use

    def __post_init__(self):
        self.client_error = None
        self.sandbox_error = None
        self.context_used = 0  # tokens in the latest request, as the API counted them
        self.model_error = None
        if self.client is None:
            try:
                self.client = anthropic.Anthropic()
            except anthropic.AnthropicError as e:  # bad credentials setup: report it when a task runs
                self.client_error = e
        self.claude_client = self.client  # for Claude models; Codex and others go through the router
        self.profile = ""  # a Bowers model (syntra, aether, solace), or "" for an engine chosen directly
        self._apply_profile(self.model, keep_effort=self.effort is not None)
        self.effort = self.effort or "high"
        self._use_client_for_model()
        if self.ext is None:
            self.ext = Extensions.load(self.root)
        self._folders_read = set()  # subfolder instruction files already shown to Claude
        if self.ext.permissions is not None:  # reference repos are read-only
            self.ext.permissions.add("deny", context_repos.deny_rules(self.root), self.root)
        if not self.helper:
            context_repos.sync_in_background(self.root)
        self.output_style = self.output_style or str(self.ext.settings.get("outputStyle") or "default")
        self.reload_instructions()
        if self.procs is None:
            self.procs = ProcessManager(self.root)
        if self.sandbox is None and not self.helper and isinstance(self.ext.settings.get("sandbox"), dict) \
                and self.ext.settings["sandbox"].get("enabled"):
            try:
                self.set_sandbox(True)
            except SandboxUnavailable as e:  # asked for but impossible here: refuse to work rather than go unsandboxed
                self.sandbox_error = str(e)
        self.procs.sandbox = self.sandbox
        if self.browser is None:
            self.browser = Browser(self.root)
        if self.lsp is None:
            self.lsp = LSPManager(self.root, self.ext.lsp_servers)
        self.checkpoints = Checkpoints(self.root)
        self.turns = []  # one entry per user turn: where it starts in messages, and the files before it
        self.plan = []
        self.bookmarks = []
        self.session_id = self.session_id or sessions.new_id()
        self.session_name = ""
        self.created = time.time()
        self._confirm_lock = threading.Lock()
        self._background = queue.Queue()     # finished background helper reports
        self._background_running = 0
        self._ids = itertools.count(1)
        self._running = False
        self._session_started = False
        self.turn_events = []     # this turn's step-by-step log (see events.py)
        self.observations = []    # the observer's latest findings, for /fix
        self._log_parent, self._log_by = None, ""  # helpers log into the agent that started them
        self._log_lock = threading.Lock()
        self.refresh_tools()
        self.cancelled = threading.Event()

    def reload_instructions(self) -> None:
        """Rebuild the system prompt (after instruction files or the output style change)."""
        style = self.ext.output_styles.get(self.output_style.lower()) if self.output_style != "default" else None
        self.system = build_system_prompt(self.root, self.ext, style)
        if self.profile and not self.helper:
            self.system += f"\n{models.PROFILES[self.profile]['prompt']}\n"
        if self.helper:
            self.system += HELPER_NOTE
        if self.agent_type is not None:
            self.system += f"\nYour role ({self.agent_type.name}):\n{self.agent_type.prompt}\n"

    def _use_client_for_model(self) -> None:
        self.model_error = None
        self.__dict__.pop("_window", None)  # context window size differs per model
        own_router = self.claude_client is not None and not models.is_direct_anthropic(self.claude_client)
        if not models.uses_router(self.model) or own_router:
            self.client = self.claude_client  # Claude, or a client already pointed at your own router
            return
        try:
            self.client = models.router_client(self.model)
        except models.ModelError as e:  # reported when a task runs
            self.model_error = str(e)

    def _apply_profile(self, name: str, keep_effort: bool = False) -> None:
        """Use a Bowers model (its engine, effort and instructions), or an engine by name."""
        profile = models.profile_of(name)
        if profile:
            spec = models.PROFILES[profile]
            self.profile, self.model = profile, models.resolve(spec["engine"])
            if not keep_effort:
                self.effort = spec["effort"]
        else:
            self.profile, self.model = "", models.resolve(name)

    @property
    def model_label(self) -> str:
        return models.PROFILES[self.profile]["name"] if self.profile else models.label(self.model)

    def set_model(self, name: str) -> str:
        """Switch to a Bowers model (syntra, aether, solace) or an engine (opus, fable, sonnet, haiku, codex,
        chatgpt, or a model ID). Returns the engine's model ID."""
        profile = models.profile_of(name)
        if profile:
            self._apply_profile(profile)
            self._use_client_for_model()
            if hasattr(self, "tools"):
                self.refresh_tools()
                self.reload_instructions()
            return self.model
        model = models.resolve(name)
        if not model:
            raise ValueError("give a model name")
        if model in models.OPENAI_FAMILIES and models.check_openai(model):
            raise ValueError(models.check_openai(model))
        self.model, self.profile = model, ""
        self._use_client_for_model()
        if hasattr(self, "tools"):
            self.refresh_tools()
            self.reload_instructions()
        return model

    def set_output_style(self, name: str) -> None:
        if name.lower() != "default" and name.lower() not in self.ext.output_styles:
            raise ValueError(f"no output style {name!r}; choose from: default, {', '.join(self.ext.output_styles)}")
        self.output_style = name.lower()
        self.reload_instructions()

    # ------------------------------------------------------------- tools

    def refresh_tools(self) -> None:
        """Rebuild the tool list (call after MCP servers start or stop)."""
        def define(name, spec):
            return {"name": name, "description": spec["description"], "eager_input_streaming": True,
                    "input_schema": {"type": "object", "properties": spec["properties"],
                                     "required": spec["required"], "additionalProperties": False}}
        process_defs = [define(n, s) for n, s in PROCESS_TOOLS.items()]
        if HAS_PLAYWRIGHT:
            process_defs.append(define("browser", BROWSER_SCHEMA))
        if images.available():
            process_defs.append(define("generate_image", images.SCHEMA))
        if motion.available():
            process_defs.append(define("generate_video", motion.SCHEMA))
        process_defs.append(define("system_check", care.SCHEMA))
        if self.lsp.available() and self.ext.settings.get("codeIntelligence", True) is not False:
            process_defs.append(define("code_intel", LSP_SCHEMA))
        agent_defs = [define(n, s) for n, s in AGENT_TOOLS.items()
                      if not (self.helper and n in ("delegate", "exit_plan_mode"))
                      and not (n == "load_skill" and not self.ext.skills)]
        mcp_defs = self.mcp.tool_definitions() if self.mcp else []
        tools = [t for t in tool_definitions() + process_defs + agent_defs + mcp_defs + (models.web_tools(self.model) if self.web else [])
                 if t["name"] not in self.exclude_tools]
        allowed = self.agent_type.tools if self.agent_type is not None else None
        if allowed:  # a specialized helper limited to some tools (Claude Code or Bowers names both work)
            tools = [t for t in tools if t["name"] in allowed or TOOL_ALIASES.get(t["name"]) in allowed
                     or t["name"] in QUIET_TOOLS]
        self.tools = tools

    @property
    def active_mode(self) -> str:
        return "yolo" if self.auto_approve else self.mode

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {', '.join(MODES)}")
        self.mode = mode
        self.auto_approve = mode == "yolo"

    def _mutating(self, name: str) -> bool:
        if name in AGENT_TOOLS:
            return False  # a helper's own tool calls ask for approval as usual
        if name in PROCESS_TOOLS:
            return name == "start_process"
        if name in ("generate_image", "generate_video"):
            return True  # writes files and costs money
        if name == "system_check":
            return False
        if self.mcp and self.mcp.handles(name):
            return self.mcp.is_mutating(name)
        return is_mutating(name)

    def browser_needs_ok(self, args: dict) -> bool:
        return self.browser is not None and self.browser.needs_ok(args)

    def _run_tool(self, name: str, args: dict) -> tuple[str, bool]:
        if name in AGENT_TOOLS:
            if not isinstance(args, dict):
                raise ToolError("tool input must be a JSON object")
            _check(args, {"type": "object", **AGENT_TOOLS[name]}, "input")
            return self._agent_tool(name, args)
        if name in PROCESS_TOOLS:
            if not isinstance(args, dict):
                raise ToolError("tool input must be a JSON object")
            _check(args, {"type": "object", **PROCESS_TOOLS[name]}, "input")
            if name == "start_process":
                return self.procs.start(args["command"]), False
            if name == "process_logs":
                return self.procs.logs(args["process_id"], args.get("lines", 100)), False
            return self.procs.stop(args["process_id"]), False
        if self.mcp and self.mcp.handles(name):
            if not isinstance(args, dict):
                raise ToolError("tool input must be a JSON object")
            try:
                return self.mcp.call(name, args)
            except MCPError as e:
                raise ToolError(str(e))
        if name == "browser":
            if not isinstance(args, dict):
                raise ToolError("tool input must be a JSON object")
            _check(args, {"type": "object", **BROWSER_SCHEMA}, "input")
            try:
                return self.browser.run(args), False
            except BrowserError as e:
                raise ToolError(str(e))
            except Exception as e:  # Playwright timeouts and navigation errors: report them, keep going
                raise ToolError(f"{type(e).__name__}: " + "\n".join(str(e).splitlines()[:6]))
        if name == "generate_image":
            if not isinstance(args, dict):
                raise ToolError("tool input must be a JSON object")
            _check(args, {"type": "object", **images.SCHEMA}, "input")
            try:
                made = images.generate(self.root, **args)
            except images.ImageError as e:
                raise ToolError(str(e))
            blocks = [{"type": "text", "text": "Saved " + ", ".join(m["path"] for m in made) + f" ({made[0]['model']})"}]
            for m in made:
                preview = images.preview_block(self.root / m["path"])
                if preview:
                    blocks.append(preview)
            return blocks, False
        if name == "generate_video":
            if not isinstance(args, dict):
                raise ToolError("tool input must be a JSON object")
            _check(args, {"type": "object", **motion.SCHEMA}, "input")
            seen = set()

            def status(text):
                if text not in seen:
                    seen.add(text)
                    self.display.notice(f"Bowers Motion: {text}…")
            try:
                made = motion.generate(self.root, on_status=status, should_stop=self.cancelled.is_set, **args)
            except motion.MotionError as e:
                raise ToolError(str(e))
            return (f"Saved {made['path']} ({made['label']}, {made['resolution']} {made['aspect']}, "
                    f"{made['seconds'] or 'auto'}s, made in {made['seconds_taken']}s). You can't watch it; "
                    "describe it from the prompt and tell the person where it is."), False
        if name == "system_check":
            sections = args.get("sections") if isinstance(args, dict) else None
            if sections is not None and (not isinstance(sections, list) or any(x not in care.SECTIONS for x in sections)):
                raise ToolError(f"sections must be a list of: {', '.join(care.SECTIONS)}")
            return care.check(sections), False
        if name == "code_intel":
            if not isinstance(args, dict):
                raise ToolError("tool input must be a JSON object")
            _check(args, {"type": "object", **LSP_SCHEMA}, "input")
            try:
                return self.lsp.run(args), False
            except LSPError as e:
                raise ToolError(str(e))
        if name == "bash" and self.sandbox is not None:
            validate(name, args)
            return tools.bash(self.root, sandbox=self.sandbox, **args), False
        return run_tool(self.root, name, args), False

    def set_sandbox(self, on: bool) -> str:
        """Turn sandboxed commands on or off. Raises sandbox.SandboxUnavailable if it can't be done here."""
        self.sandbox = Sandbox.from_settings(self.root, self.ext.settings) if on else None
        self.procs.sandbox = self.sandbox
        if self.browser is None:
            self.browser = Browser(self.root)
        if self.lsp is None:
            self.lsp = LSPManager(self.root, self.ext.lsp_servers)
        return self.sandbox.describe() if self.sandbox else "sandbox off: commands run with your normal access"

    def _agent_tool(self, name: str, args: dict) -> tuple[str, bool]:
        if name == "update_plan":
            self.plan = args["items"]
            self.display.plan(self.plan)
            return "plan updated", False
        if name == "delegate":
            return self._delegate(args["description"], args["prompt"], args.get("agent"), args.get("background", False))
        if name == "load_skill":
            skill = self.ext.skills.get(args["name"])
            if not skill:
                raise ToolError(f"no skill named {args['name']!r}; available: {', '.join(self.ext.skills) or 'none'}")
            return skill.load(), False
        if name == "ask_user":
            ask = getattr(self.display, "ask", None)
            if ask is None:
                return "No one can answer questions right now. Choose sensible defaults and say what you chose.", False
            self.notify_user("Bowers has a question for you")
            with self._confirm_lock:
                answers = ask(args["questions"])
            if answers is None:
                return "The user dismissed the questions. Choose sensible defaults, or ask in plain text.", False
            return "\n\n".join(f"Q: {q['question']}\nA: {a}" for q, a in zip(args["questions"], answers)), False
        if name == "exit_plan_mode":
            if self.active_mode != "plan":
                return "Plan mode isn't on; go ahead with the work.", False
            review = getattr(self.display, "review_plan", None)
            if review:
                self.notify_user("Bowers has a plan ready for you to review")
            decision, feedback = review(args["plan"]) if review else ("approve", "")
            if decision == "approve_auto":
                self.set_mode("auto")
                return "The user approved the plan and turned on auto mode. Carry it out now.", False
            if decision == "approve":
                self.set_mode("ask")
                return "The user approved the plan. Carry it out now.", False
            return f"The user wants changes to the plan before you start: {feedback or '(no details)'}. " \
                   "Revise it and present it again with exit_plan_mode.", False
        raise ToolError(f"unknown tool {name}")

    def last_text(self) -> str:
        """The text of Claude's final reply in the conversation (empty if the last turn failed)."""
        if not self.messages or self.messages[-1]["role"] != "assistant":
            return ""
        return "".join(_block(b, "text", "") or "" for b in self.messages[-1]["content"]
                       if _block(b, "type") == "text").strip()

    # ------------------------------------------------------------- helpers

    def _make_helper(self, description: str, agent_name: str | None):
        agent_type = None
        if agent_name:
            agent_type = self.ext.agents.get(agent_name)
            if agent_type is None:
                raise ToolError(f"no helper type {agent_name!r}; available: {', '.join(self.ext.agents) or 'none'}")
        helper = Agent(root=self.root, model=(agent_type.model if agent_type and agent_type.model else self.model),
                       effort=self.effort, auto_approve=self.auto_approve, mode=self.mode if self.mode != "plan" else "ask",
                       web=self.web, exclude_tools=self.exclude_tools, client=self.claude_client, mcp=self.mcp,
                       procs=self.procs, helper=True, always_allowed=self.always_allowed, ext=self.ext, sandbox=self.sandbox,
                       browser=self.browser, lsp=self.lsp,
                       agent_type=agent_type, display=HelperDisplay(self.display, description),
                       confirm=self._locked_confirm)
        helper.cancelled = self.cancelled  # stopping the lead agent stops its helpers
        helper._log_parent, helper._log_by = self, description
        return helper

    def _delegate(self, description: str, prompt: str, agent_name: str | None = None,
                  background: bool = False) -> tuple[str, bool]:
        helper = self._make_helper(description, agent_name)
        if background:
            hid = next(self._ids)
            self._background_running += 1

            def work():
                report, failed = self._run_helper(helper, prompt)
                self._background.put((hid, description, report, failed))
                self._background_running -= 1
                self.display.notice(f"Background helper finished: {description}")
                if not self._running and self.on_background_done:
                    self.on_background_done()
            threading.Thread(target=work, daemon=True).start()
            return (f"Helper #{hid} ({description}) is working in the background. Its report will be delivered to "
                    "you automatically when it finishes; carry on with other work meanwhile."), False
        return self._run_helper(helper, prompt)

    def _run_helper(self, helper: "Agent", prompt: str) -> tuple[str, bool]:
        helper.run(prompt)
        for round_ in range(MAX_STOP_HOOK_ROUNDS):  # SubagentStop hooks can send a helper back to work
            if not self.ext.hooks or not helper.last_text():
                break
            verdict = self.ext.run_hooks("SubagentStop", {"stop_hook_active": round_ > 0, "session_id": self.session_id,
                                                          "agent_type": getattr(helper.agent_type, "name", "general"),
                                                          "last_message": helper.last_text()[:20_000]})
            if not (verdict.block and verdict.reason):
                break
            helper.run(f"<system-reminder>Before finishing: {verdict.reason}</system-reminder>")
        for key in self.usage:
            self.usage[key] += helper.usage[key]
        report = helper.last_text()
        if not report:
            return "The helper stopped before finishing and gave no report.", True
        return report, False

    def _locked_confirm(self, name: str, args: dict) -> str:
        self.notify_user(f"Bowers needs your permission to use {TOOL_ALIASES.get(name, name)}")
        with self._confirm_lock:  # helpers run in parallel; ask the user one question at a time
            return (self.confirm or self.display.confirm)(name, args)

    def notify_user(self, message: str) -> None:
        """Bowers is waiting for the person: run Notification hooks and let the display alert them."""
        if self.ext.hooks:
            self.ext.run_hooks("Notification", {"message": message, "session_id": self.session_id})
        alert = getattr(self.display, "alert", None)
        if alert:
            alert(message)

    def _take_background_reports(self) -> list[dict]:
        blocks = []
        while True:
            try:
                hid, description, report, failed = self._background.get_nowait()
            except queue.Empty:
                return blocks
            status = "failed" if failed else "finished"
            blocks.append({"type": "text", "text": f"<background-helper id=\"{hid}\" description=\"{description}\" "
                                                   f"status=\"{status}\">\n{report}\n</background-helper>"})

    def has_background_reports(self) -> bool:
        return not self._background.empty()

    # ------------------------------------------------------------- session state

    def compact(self, focus: str = "") -> str:
        """Replace the conversation with Claude's summary of it, to free up room. Returns the summary.

        (Very long sessions are also summarized automatically, on Claude's side, as they go.)"""
        if len(self.messages) < 2:
            raise ValueError("nothing to summarize yet")
        if self.client is None:
            raise ValueError(NO_KEY)
        if self.ext.hooks:
            verdict = self.ext.run_hooks("PreCompact", {"trigger": "manual", "custom_instructions": focus,
                                                        "session_id": self.session_id})
            if verdict.block:
                raise ValueError(f"a PreCompact hook stopped it: {verdict.reason or 'no reason given'}")
        ask = COMPACT_PROMPT + (f"\nPay special attention to: {focus}" if focus else "")
        with self.client.beta.messages.stream(
            model=self.model, max_tokens=16_000, system=self.system, tools=self.tools,
            tool_choice={"type": "none"}, messages=self.messages + [{"role": "user", "content": ask}],
            thinking={"type": "adaptive"}, output_config={"effort": "medium"}, context_management={"edits": [{"type": "compact_20260112"}]},
            betas=BETAS,
        ) as stream:
            for _ in stream:
                self._check_cancel()
            response = stream.get_final_message()
        self._track_usage(response.usage)
        summary = "".join(getattr(b, "text", "") for b in response.content if getattr(b, "type", "") == "text").strip()
        if not summary:
            raise ValueError("Claude didn't return a summary; nothing was changed")
        self.messages[:] = [
            {"role": "user", "content": f"<conversation-summary>\nThis conversation was summarized to save room. "
                                        f"What happened so far:\n\n{summary}\n</conversation-summary>"},
            {"role": "assistant", "content": [{"type": "text", "text": "Got it. I'll continue from this summary."}]},
        ]
        self.turns.clear()  # undo points from before the summary can't be reached any more
        self.save_session()
        return summary

    def context_report(self) -> dict:
        """What's taking up the context window (estimates from text size, plus the API's real count)."""
        def tokens(value) -> int:
            return len(json.dumps(value, default=str)) // 4

        system_parts = {"Instructions files and memory": tokens(instructions.system_section(self.root)) + tokens(memory.load(self.root))}
        system_parts["Bowers' own instructions"] = max(tokens(self.system) - sum(system_parts.values()), 0)
        mcp_names = {t["name"] for t in self.tools if t["name"].startswith("mcp__")}
        parts = {**system_parts,
                 "Tools": tokens([t for t in self.tools if t["name"] not in mcp_names]),
                 "MCP tools": tokens([t for t in self.tools if t["name"] in mcp_names])}
        chat = {"Your messages": 0, "Claude's replies": 0, "Tool results": 0}
        for m in self.messages:
            blocks = m["content"] if isinstance(m["content"], list) else [{"type": "text", "text": m["content"]}]
            for b in blocks:
                kind = _block(b, "type")
                if kind == "tool_result":
                    chat["Tool results"] += tokens(_block(b, "content"))
                elif m["role"] == "user":
                    chat["Your messages"] += tokens(_block(b, "text", "")) if kind == "text" else 1500
                else:
                    chat["Claude's replies"] += tokens(sessions.plain(b))
        parts.update(chat)
        return {"parts": parts, "estimated": sum(parts.values()), "measured": self.context_used,
                "window": self._window_size(), "messages": len(self.messages)}

    def _window_size(self) -> int | None:
        if not hasattr(self, "_window"):
            try:
                self._window = int(self.client.models.retrieve(self.model).max_input_tokens)
            except Exception:  # offline, an old SDK, or a router that doesn't list models
                self._window = None
        return self._window

    def end_session(self, reason: str = "other") -> None:
        """Run SessionEnd hooks (on exit, /clear, or a new chat)."""
        if self.ext.hooks and self._session_started:
            self.ext.run_hooks("SessionEnd", {"reason": reason, "session_id": self.session_id})

    def reset(self):
        self.end_session("clear")
        self._folders_read.clear()
        self.messages.clear()
        self.turns.clear()
        self.plan = []
        self.bookmarks = []
        self.session_id = sessions.new_id()
        self.session_name = ""
        self.created = time.time()
        self._session_started = False

    def rewind(self, turn: int) -> tuple[str, list[str]]:
        """Go back to just before user turn `turn` (0-based): restore files and drop that turn and later ones.

        Returns the text of that turn's message (to edit and resend) and the files that were restored."""
        if not 0 <= turn < len(self.turns):
            raise CheckpointError("no such turn")
        entry = self.turns[turn]
        if not entry["checkpoint"]:
            raise CheckpointError("there's no file snapshot for that point, so it can't be restored")
        restored = self.checkpoints.restore(entry["checkpoint"])
        del self.messages[entry["index"]:]
        del self.turns[turn:]
        self.save_session()
        return entry["text"], restored

    def bookmark(self, text: str) -> None:
        self.bookmarks.append({"text": text, "time": time.time()})
        self.save_session()

    def session_data(self) -> dict:
        title = next((t["text"].splitlines()[0][:80] for t in self.turns if t["text"].strip()), "")
        return {"id": self.session_id, "name": self.session_name, "title": title, "root": str(self.root),
                "model": self.model, "created": self.created, "messages": sessions.plain(self.messages),
                "turns": self.turns, "plan": self.plan, "bookmarks": self.bookmarks, "usage": self.usage}

    def save_session(self) -> None:
        if self.save and not self.helper and self.messages:
            sessions.save(self.session_data())

    def resume(self, session_id: str) -> dict:
        """Load a saved conversation into this agent."""
        data = sessions.load(session_id)
        self.session_id, self.session_name = data["id"], data.get("name", "")
        self.messages = data["messages"]
        self.turns, self.plan = data.get("turns", []), data.get("plan", [])
        self.bookmarks, self.created = data.get("bookmarks", []), data.get("created", time.time())
        self.usage = {**self.usage, **data.get("usage", {})}
        self._session_started = True
        return data

    def rename(self, name: str) -> None:
        self.session_name = name.strip()
        self.save_session()

    # ------------------------------------------------------------- running

    def stop(self):
        """Cancel the running turn (safe to call from another thread)."""
        self.cancelled.set()

    def _check_cancel(self):
        if self.cancelled.is_set():
            raise TurnAborted("stopped; this turn was discarded")

    def _expand_mentions(self, text: str) -> list[dict]:
        """@path mentions of files or folders in the project become attached text blocks."""
        blocks, seen = [], set()
        for m in re.finditer(r"(?<![\w@/])@([\w./~-]+[\w/])", text):
            rel = m.group(1)
            path = (self.root / rel).resolve()
            if rel in seen or not path.is_relative_to(self.root.resolve()) or not path.exists():
                continue
            seen.add(rel)
            if path.is_dir():
                entries = sorted(p.name + ("/" if p.is_dir() else "") for p in path.iterdir() if not p.name.startswith("."))
                blocks.append({"type": "text", "text": f"<folder path=\"{rel}\">\n" + "\n".join(entries[:300]) + "\n</folder>"})
            else:
                data = path.read_bytes()[:MAX_MENTION_BYTES]
                try:
                    content = data.decode()
                except UnicodeDecodeError:
                    continue
                blocks.append({"type": "text", "text": f"<file path=\"{rel}\">\n{content}\n</file>"})
            if len(blocks) >= 10:
                break
        return blocks

    def run(self, user_input: str | list) -> None:
        """Run one user turn to completion. On failure or interrupt, roll the history back.

        user_input is text, or a list of content blocks (e.g. images followed by text). Text starting with
        /name runs that command; @path mentions attach files."""
        turn_start = len(self.messages)
        text = user_input if isinstance(user_input, str) else " ".join(
            b.get("text", "") for b in user_input if b.get("type") == "text")
        self._running = True
        try:
            if not self.helper:
                self.cancelled.clear()
                expanded = self.ext.expand(text) if isinstance(user_input, str) else None
                if expanded:
                    user_input, cmd = expanded
                    self.display.notice(f"Running /{cmd.name}")
            extra = self._turn_context(text) if not self.helper else []
            if extra is None:
                return  # a hook blocked the prompt
            if not self.helper:
                self.turns.append({"index": turn_start, "text": text,
                                   "checkpoint": self.checkpoints.snapshot(text.splitlines()[0] if text else "task")})
                self.turn_events = []
                self._log("turn_start", text=text)
            if extra:
                base = [{"type": "text", "text": user_input}] if isinstance(user_input, str) else list(user_input)
                user_input = base + extra
            self.messages.append({"role": "user", "content": user_input})
            self._loop()
        except KeyboardInterrupt:
            self.display.warn("interrupted; this turn was discarded")
            del self.messages[turn_start:]
        except TurnAborted as e:
            self.display.error(str(e))
            del self.messages[turn_start:]
        except anthropic.AuthenticationError:
            self.display.error(NO_KEY.replace("No API key was found", "The API key was rejected"))
            del self.messages[turn_start:]
        except anthropic.APIError as e:
            self.display.error(f"API error: {e}")
            del self.messages[turn_start:]
        except anthropic.CredentialsError as e:  # e.g. a named profile that doesn't exist
            self.display.error(f"{NO_KEY} ({e})")
            del self.messages[turn_start:]
        except anthropic.AnthropicError as e:
            self.display.error(f"Error talking to Claude: {e}")
            del self.messages[turn_start:]
        except TypeError as e:
            if "authentication method" not in str(e):
                raise
            self.display.error(NO_KEY)  # the SDK found no credentials at all
            del self.messages[turn_start:]
        finally:
            self._running = False
            if not self.helper and self.turn_events:
                ok = len(self.messages) > turn_start
                self._log("turn_end", ok=ok, usage=dict(self.usage))
                if ok:
                    self._observe(text)
            self.save_session()
            self.display.turn_done(self.usage)

    def _turn_context(self, text: str) -> list[dict] | None:
        """Extra blocks for this user turn: hook context, @mentions, mode reminders, background reports.
        None means a UserPromptSubmit hook blocked the prompt."""
        extra = []
        if getattr(self, "voice_turn", False):  # spoken through Bowers Aether's voice mode
            self.voice_turn = False
            extra.append({"type": "text", "text": VOICE_NOTE})
        if self.ext.hooks:
            if not self._session_started:
                start = self.ext.run_hooks("SessionStart", {"source": "startup", "session_id": self.session_id})
                if start.context:
                    extra.append({"type": "text", "text": f"<session-context>\n{start.context}\n</session-context>"})
            submit = self.ext.run_hooks("UserPromptSubmit", {"prompt": text, "session_id": self.session_id})
            if submit.block:
                self.display.error(f"A hook blocked this message: {submit.reason or 'no reason given'}")
                return None
            if submit.context:
                extra.append({"type": "text", "text": f"<hook-context>\n{submit.context}\n</hook-context>"})
        self._session_started = True
        extra += self._expand_mentions(text)
        if self.active_mode == "plan":
            extra.append({"type": "text", "text": PLAN_MODE_NOTE})
        extra += self._take_background_reports()
        return extra

    def _loop(self) -> None:
        json_retries = 0
        stop_rounds = 0
        while True:
            reports = self._take_background_reports()
            if reports:  # helpers that finished while we worked: hand their reports over now
                last = self.messages[-1]
                content = last["content"] if isinstance(last["content"], list) else [{"type": "text", "text": last["content"]}]
                last["content"] = content + reports
            try:
                response = self._stream_with_retries()
            except ValueError as e:  # tool input arrived as JSON the SDK couldn't parse
                json_retries += 1
                if json_retries > MAX_JSON_RETRIES:
                    raise TurnAborted(f"repeated malformed tool input: {e}")
                self.display.warn("malformed tool input; retrying")
                continue

            self._track_usage(response.usage)
            stop = response.stop_reason
            if any(getattr(b, "type", None) == "compaction" for b in response.content):
                self.display.notice("Summarized the earlier conversation to make room, and kept going.")

            if stop == "refusal":
                raise TurnAborted("Claude declined this request; the turn was discarded.")

            self.messages.append({"role": "assistant", "content": response.content})
            said = "".join(getattr(b, "text", "") or "" for b in response.content if getattr(b, "type", None) == "text").strip()
            if said:
                self._log("reply", text=said)

            if stop == "pause_turn":
                continue
            if stop == "model_context_window_exceeded":
                self.display.warn("context window is full; use /clear to start fresh")
                return

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                if stop == "max_tokens":
                    self.display.warn("response hit the output limit")
                    return
                if self.ext.hooks and stop_rounds < MAX_STOP_HOOK_ROUNDS and not self.helper:
                    verdict = self.ext.run_hooks("Stop", {"stop_hook_active": stop_rounds > 0,
                                                          "session_id": self.session_id})
                    if verdict.block and verdict.reason:
                        stop_rounds += 1
                        self.display.notice(f"A hook asked Bowers to keep going: {verdict.reason}")
                        self.messages.append({"role": "user", "content": f"<system-reminder>Before finishing: "
                                              f"{verdict.reason}</system-reminder>"})
                        continue
                return

            results = {}
            helpers = [b for b in tool_uses if b.name == "delegate" and not (isinstance(b.input, dict) and b.input.get("background"))]
            for block in tool_uses:
                if stop == "max_tokens" and block is tool_uses[-1]:
                    # The last tool input was likely cut off mid-stream; don't run it.
                    results[block.id] = _error_result(block.id, "Your tool input was cut off by the output limit. "
                                                                "Retry with smaller pieces (e.g. write the file in parts).")
                elif block not in helpers:
                    results[block.id] = self._execute(block)
            todo = [b for b in helpers if b.id not in results]
            if todo:  # helpers run in parallel
                with ThreadPoolExecutor(max_workers=min(MAX_HELPERS, len(todo))) as pool:
                    for block, result in zip(todo, pool.map(self._execute, todo)):
                        results[block.id] = result
            self.messages.append({"role": "user", "content": [results[b.id] for b in tool_uses]})

    def _stream_with_retries(self):
        for attempt in range(MAX_RETRIES + 1):
            try:
                return self._stream_once()
            except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.OverloadedError,
                    anthropic.ServiceUnavailableError, anthropic.APIConnectionError) as e:
                if attempt == MAX_RETRIES or isinstance(e, anthropic.AuthenticationError):
                    raise
                delay = _retry_after(e) or min(60, 2 ** (attempt + 1))
                reason = "rate limit reached" if isinstance(e, anthropic.RateLimitError) else \
                         "connection problem" if isinstance(e, anthropic.APIConnectionError) else "Claude is busy"
                self.display.notice(f"{reason}; trying again in {delay:.0f}s ({attempt + 1}/{MAX_RETRIES})")
                end = time.monotonic() + delay
                while time.monotonic() < end:
                    self._check_cancel()
                    time.sleep(min(0.2, max(0.0, end - time.monotonic())))

    def _stream_once(self):
        if self.model_error:
            raise TurnAborted(f"{self.model_error} (or switch models with /model)")
        if self.client is None:
            raise TurnAborted(f"{NO_KEY} ({self.client_error})")
        if self.sandbox_error:
            raise TurnAborted(f"Your settings turn the sandbox on, but it can't run here: {self.sandbox_error} "
                              "Fix that, or set \"sandbox\": {\"enabled\": false} to work without it.")
        printer = self.display.stream()
        with self.client.beta.messages.stream(
            model=self.model,
            max_tokens=64_000,
            system=self.system,
            tools=self.tools,
            messages=self.messages,
            thinking={"type": "adaptive", "display": "updates"},
            output_config={"effort": self.effort},
            cache_control={"type": "ephemeral"},
            context_management={"edits": [{"type": "compact_20260112"}]},
            fallbacks="default",
            betas=BETAS,
        ) as stream:
            for event in stream:
                self._check_cancel()
                printer.handle(event)
            response = stream.get_final_message()
        printer.finish()
        return response

    def _approved(self, name: str, args: dict, call_id: str, hook_decision: str | None,
                  rule: str | None = None) -> tuple[bool, str]:
        """Whether a tool call may run, asking the user if needed. Returns (ok, message if not).

        rule is what the settings' permission rules say: "ask" always asks, "allow" skips the question."""
        if hook_decision == "allow":
            return True, ""
        mutating = self._mutating(name) or (name == "browser" and self.browser_needs_ok(args))
        if not mutating and rule != "ask":
            return True, ""
        mode = self.active_mode
        if mode == "plan" and mutating:
            return False, ("Plan mode is on, so nothing can be changed yet. Finish researching and present your "
                           "plan with exit_plan_mode.")
        if hook_decision != "ask" and rule != "ask":
            if mode == "yolo" or rule == "allow" or name in self.always_allowed:
                return True, ""
            if mode == "auto" and name == "bash" and self.sandbox and self.sandbox.auto_allow \
                    and not self.sandbox.excludes(str(args.get("command", ""))) \
                    and not automode.DANGEROUS.search(str(args.get("command", ""))):
                note = getattr(self.display, "auto_approved", None)
                if note:
                    note(call_id, "runs in the sandbox")
                return True, ""
            if mode == "auto":
                verdict, reason = automode.classify(self.claude_client, name, args, self.root)
                if verdict == "allow":
                    note = getattr(self.display, "auto_approved", None)
                    if note:
                        note(call_id, reason)
                    return True, ""
        answer = self._locked_confirm(name, args)
        self._check_cancel()
        if answer == "always":
            if name in ("bash", "start_process") or name == "browser":
                # remember this kind of command (npm test, git status...), not every shell command
                remembered = suggest_rule(name, args)
                self.ext.permissions.add("allow", [remembered], self.root)
                self.display.notice(f"Allowed {remembered} for this session (/allow {remembered} keeps it)")
            else:
                self.always_allowed.add(name)
        elif answer != "yes":
            return False, getattr(self.display, "declined_message", "The user declined this tool call. Ask what they want instead.")
        return True, ""

    def _log(self, kind: str, **data) -> None:
        """Add a step to the session's event log (helpers' steps go to the agent that started them)."""
        if self._log_parent is not None:
            return self._log_parent._log(kind, **{"by": self._log_by, **data})
        event = {"t": time.time(), "kind": kind, **data}
        with self._log_lock:
            self.turn_events.append(event)
        if self.save and not self.helper:
            events.append(self.session_id, event)

    def _observe(self, request: str) -> None:
        """Let the observer check a turn that changed something (see observer.py)."""
        if self.ext.settings.get("observer", True) is False or self.claude_client is None:
            return
        if not observer.worth_checking(self.turn_events):
            return
        model = self.ext.settings.get("observerModel") or models.current("haiku")
        result = observer.check(self.claude_client, model, request, self.last_text(), self.turn_events,
                                observer.diff(self.root))
        if result is None:
            return
        self.observations = result["findings"]
        if self.profile == "aether":  # Aether learns: it keeps the preferences it notices
            for f in [f for f in result["findings"] if f["kind"] == "remember" and (f["action"] or f["text"])][:2]:
                try:
                    saved = instructions.add_note(self.root, f["action"] or f["text"], "user")
                    self.display.notice(f"Aether will remember: {f['action'] or f['text']} (saved in {saved.name})")
                except OSError:
                    pass
            self.observations = [f for f in self.observations if f["kind"] != "remember"]
            result = {**result, "findings": self.observations}
            self.reload_instructions()
        self._log("observer", **result)
        show = getattr(self.display, "observer", None)
        if show:
            show(result)
        else:
            self.display.notice(observer.format_text(result))

    def _execute(self, block) -> dict:
        args = block.input
        logged = {k: v if isinstance(v, (int, float, bool)) or len(json.dumps(v, default=str)) <= 1000 else events.clip(v, 1000)
                  for k, v in args.items()} if isinstance(args, dict) else events.clip(args, 1000)
        self._log("tool_call", id=block.id, name=block.name, args=logged,
                  mutating=bool(self._mutating(block.name)) if isinstance(args, dict) else False)
        start = time.monotonic()
        result = self._execute_step(block)
        content = result.get("content")
        text = content if isinstance(content, str) else "\n".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text") \
            if isinstance(content, list) else ""
        self._log("tool_result", id=block.id, name=block.name, ok=not result.get("is_error"),
                  output=events.clip(text), ms=int((time.monotonic() - start) * 1000))
        return result

    def _execute_step(self, block) -> dict:
        self._check_cancel()
        args = block.input
        self.display.tool_call(block.name, args, id=block.id)
        decision = None
        rule, rule_text = self.ext.permissions.check(block.name, args) if self.ext.permissions else (None, "")
        if rule == "deny":
            message = (f"Blocked by the permission rule {rule_text} in your settings. Don't try to get around it; "
                       "tell the user if you need it.")
            self.display.tool_output(message, is_error=True, id=block.id)
            return _error_result(block.id, message)
        if self.ext.hooks and isinstance(args, dict):
            pre = self.ext.run_hooks("PreToolUse", {"tool_name": TOOL_ALIASES.get(block.name, block.name),
                                                    "tool_input": hook_tool_input(block.name, args),
                                                    "session_id": self.session_id}, tool=block.name)
            if pre.block or pre.decision == "deny":
                message = f"A hook blocked this: {pre.reason or 'no reason given'}"
                self.display.tool_output(message, is_error=True, id=block.id)
                return _error_result(block.id, message)
            decision = pre.decision
        ok, why = self._approved(block.name, args if isinstance(args, dict) else {}, block.id, decision, rule)
        if not ok:
            self.display.tool_output(why, is_error=True, id=block.id)
            return _error_result(block.id, why)
        try:
            output, failed = self._run_tool(block.name, args)
        except ToolError as e:
            self.display.tool_output(str(e), is_error=True, id=block.id)
            return _error_result(block.id, str(e))
        except TurnAborted:
            raise
        except Exception as e:  # tool bugs shouldn't kill the session
            self.display.tool_output(repr(e), is_error=True, id=block.id)
            return _error_result(block.id, f"{type(e).__name__}: {e}")
        if block.name in ("read_file", "write_file", "edit_file") and not failed and isinstance(output, str):
            output += instructions.folder_instructions(self.root, args.get("path", ""), self._folders_read)
        if block.name in ("write_file", "edit_file") and not failed and self.lsp.available() \
                and self.ext.settings.get("codeIntelligence", True) is not False:
            errors = self.lsp.errors_after_edit(args.get("path", ""))
            if errors:
                output = f"{output}\n\n{errors}"
        # output is text, or content blocks (text and screenshots) from the browser
        shown = output if isinstance(output, str) else "\n".join(b["text"] for b in output if b.get("type") == "text")
        if self.ext.hooks and isinstance(args, dict):
            post = self.ext.run_hooks("PostToolUse", {"tool_name": TOOL_ALIASES.get(block.name, block.name),
                                                      "tool_input": hook_tool_input(block.name, args),
                                                      "tool_response": shown[:20_000], "session_id": self.session_id},
                                      tool=block.name)
            feedback = "\n".join(x for x in (post.reason if post.block else "", post.context) if x)
            if feedback:
                shown = f"{shown}\n\n[hook feedback]\n{feedback}"
                output = shown if isinstance(output, str) else output + [{"type": "text", "text": f"[hook feedback]\n{feedback}"}]
        self.display.tool_output(shown, is_error=failed, id=block.id)
        if not isinstance(output, str):
            show_image = getattr(self.display, "tool_image", None)
            for b in output:
                if b.get("type") == "image" and show_image:
                    show_image(b["source"]["data"], b["source"]["media_type"], id=block.id)
        result = {"type": "tool_result", "tool_use_id": block.id, "content": output}
        return {**result, "is_error": True} if failed else result

    def _track_usage(self, usage) -> None:
        self.context_used = ((usage.input_tokens or 0) + (usage.cache_read_input_tokens or 0)
                             + (getattr(usage, "cache_creation_input_tokens", 0) or 0) + (usage.output_tokens or 0))
        self.usage["input"] += usage.input_tokens or 0
        self.usage["output"] += usage.output_tokens or 0
        self.usage["cache_read"] += usage.cache_read_input_tokens or 0


def _retry_after(error) -> float | None:
    response = getattr(error, "response", None)
    try:
        value = response.headers.get("retry-after") if response is not None else None
        return min(120.0, float(value)) if value else None
    except (TypeError, ValueError):
        return None


def _error_result(tool_use_id: str, message: str) -> dict:
    return {"type": "tool_result", "tool_use_id": tool_use_id, "content": message, "is_error": True}


class _QuietStream:
    def handle(self, event):
        pass

    def finish(self):
        pass


class HelperDisplay:
    """What a helper agent shows: its tool calls (labelled with the helper), not its streamed text."""

    def __init__(self, parent, name: str):
        self.parent, self.name = parent, name

    def stream(self):
        return _QuietStream()

    def tool_call(self, name, args, id=None):
        self.parent.tool_call(name, args, id=id, helper=self.name)

    def tool_output(self, output, is_error=False, id=None):
        self.parent.tool_output(output, is_error=is_error, id=id, helper=self.name)

    def warn(self, msg):
        self.parent.warn(f"{self.name}: {msg}")

    def error(self, msg):
        self.parent.warn(f"{self.name}: {msg}")

    def notice(self, msg):
        self.parent.notice(f"{self.name}: {msg}")

    def plan(self, items):
        pass  # the lead agent owns the plan

    def confirm(self, name, args):
        return self.parent.confirm(name, args)

    def ask(self, questions):
        ask = getattr(self.parent, "ask", None)
        return ask(questions) if ask else None

    def auto_approved(self, call_id, reason):
        note = getattr(self.parent, "auto_approved", None)
        if note:
            note(call_id, reason)

    def turn_done(self, usage):
        pass
