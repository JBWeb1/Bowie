"""Extensions: slash commands, custom agents, skills and hooks, in Claude Code's plugin formats.

Where they come from (later ones override earlier ones with the same name):
  built-in            docks/builtin/commands/*.md
  your folders        ~/.claude/{commands,agents,skills}, ~/.docks/{commands,agents,skills}
  installed plugins   ~/.docks/plugins/<plugin>/  (a folder with .claude-plugin/plugin.json)
  this project        <project>/.claude/..., <project>/.docks/...

  commands/<name>.md        -> /name           (plugin commands are /plugin:name)
  agents/<name>.md          -> a helper type for the delegate tool
  skills/<name>/SKILL.md    -> know-how Claude loads when it's relevant
  hooks/hooks.json, settings.json "hooks"  -> commands run on events (PreToolUse, PostToolUse,
                               UserPromptSubmit, SessionStart, Stop)

Hooks run code, so a project's own hooks (from a repo you cloned) only run after you approve them.
"""

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import mcp as trust_store
from .permissions import Permissions, exclude_from_git, local_settings_file

BUILTIN = Path(__file__).parent / "builtin"
HOOK_EVENTS = ("PreToolUse", "PostToolUse", "UserPromptSubmit", "SessionStart", "Stop")
# Claude Code's tool names, so hook matchers written for it work here too.
TOOL_ALIASES = {"bash": "Bash", "write_file": "Write", "edit_file": "Edit", "read_file": "Read", "glob": "Glob",
                "grep": "Grep", "web_fetch": "WebFetch", "web_search": "WebSearch", "delegate": "Task",
                "update_plan": "TodoWrite", "ask_user": "AskUserQuestion", "start_process": "Bash"}
MODEL_ALIASES = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5",
                 "fable": "claude-fable-5-1"}


def docks_home() -> Path:
    return Path(os.environ.get("DOCKS_HOME", Path.home() / ".docks"))


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))


def plugins_dir() -> Path:
    return docks_home() / "plugins"


# ------------------------------------------------------------------ frontmatter


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """A small YAML-frontmatter reader: `key: value` lines, quoted strings, [a, b] lists, folded lines."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    meta, key = {}, None
    for line in text[3:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m and not line.startswith((" ", "\t")):
            key, value = m.group(1), m.group(2).strip()
            if value in (">", "|", ">-", "|-"):
                value = ""
            elif value.startswith("[") and value.endswith("]"):
                value = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
            else:
                value = value.strip("'\"")
            meta[key] = value
        elif key is not None:  # continuation of the previous value
            extra = line.strip()
            if extra.startswith("- "):
                prev = meta[key] if isinstance(meta[key], list) else ([] if not meta[key] else [meta[key]])
                meta[key] = prev + [extra[2:].strip().strip("'\"")]
            else:
                meta[key] = (meta[key] + " " + extra).strip() if isinstance(meta[key], str) else meta[key]
    body = text[end + 4:].lstrip("\n")
    return meta, body


def _as_list(value) -> list[str] | None:
    if value in (None, "", "*"):
        return None
    if isinstance(value, list):
        return value
    return [v.strip() for v in str(value).split(",") if v.strip()]


# ------------------------------------------------------------------ items


@dataclass
class Command:
    name: str
    description: str
    body: str
    source: str           # builtin | user | plugin:<name> | project
    argument_hint: str = ""
    root: Path | None = None  # the plugin's folder, for ${CLAUDE_PLUGIN_ROOT}

    @property
    def trusted(self) -> bool:
        return self.source != "project"


@dataclass
class AgentType:
    name: str
    description: str
    prompt: str
    tools: list[str] | None = None
    model: str | None = None
    source: str = "user"


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    source: str = "user"

    def load(self) -> str:
        _, body = parse_frontmatter((self.path / "SKILL.md").read_text())
        others = sorted(str(p.relative_to(self.path)) for p in self.path.rglob("*") if p.is_file() and p.name != "SKILL.md")
        extra = f"\n\nOther files in this skill (read them with read_file from {self.path}):\n" + "\n".join(others) if others else ""
        return body + extra


@dataclass
class Hook:
    event: str
    matcher: str
    command: str
    source: str
    root: Path | None = None
    timeout: int = 60
    spec_file: str = ""


@dataclass
class OutputStyle:
    name: str
    description: str
    prompt: str
    source: str
    keep_coding_instructions: bool = False


@dataclass
class HookResult:
    block: bool = False         # stop this action (or for Stop: keep working)
    reason: str = ""
    decision: str | None = None  # PreToolUse: allow | deny | ask
    context: str = ""           # extra text for Claude


@dataclass
class Extensions:
    root: Path
    commands: dict = field(default_factory=dict)
    agents: dict = field(default_factory=dict)
    skills: dict = field(default_factory=dict)
    hooks: list = field(default_factory=list)
    pending_hooks: list = field(default_factory=list)  # project hook files waiting for approval
    plugins: list = field(default_factory=list)
    plugin_mcp: dict = field(default_factory=dict)     # MCP servers that plugins ship
    permissions: Permissions | None = None              # allow / ask / deny rules from every settings file
    settings: dict = field(default_factory=dict)        # other settings (outputStyle, statusLine, sandbox, ...)
    output_styles: dict = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path) -> "Extensions":
        ext = cls(root=root, permissions=Permissions(root))
        ext._scan_dir(BUILTIN, "builtin")
        for base in (claude_home(), docks_home()):
            ext._scan_dir(base, "user")
            ext._load_settings(base / "settings.json", "user")
        for plugin in installed_plugins():
            if plugin["enabled"]:
                ext._load_plugin(Path(plugin["path"]))
        for base in (root / ".claude", root / ".docks"):
            ext._scan_dir(base, "project")
            for name in ("settings.json", "settings.local.json"):
                ext._load_settings(base / name, "project")
        return ext

    # -- scanning

    def _scan_dir(self, base: Path, source: str, prefix: str = "", plugin_root: Path | None = None) -> None:
        cmd_dir = base / "commands"
        if cmd_dir.is_dir():
            for f in sorted(cmd_dir.rglob("*.md")):
                meta, body = parse_frontmatter(f.read_text(errors="replace"))
                parts = f.relative_to(cmd_dir).with_suffix("").parts
                name = prefix + ":".join(parts)
                first = next((l.strip() for l in body.splitlines() if l.strip()), "")
                self.commands[name] = Command(name, meta.get("description") or first[:100], body, source,
                                              meta.get("argument-hint", ""), plugin_root)
        agent_dir = base / "agents"
        if agent_dir.is_dir():
            for f in sorted(agent_dir.glob("*.md")):
                meta, body = parse_frontmatter(f.read_text(errors="replace"))
                name = meta.get("name") or f.stem
                self.agents[name] = AgentType(name, meta.get("description", ""), body, _as_list(meta.get("tools")),
                                              MODEL_ALIASES.get(meta.get("model", ""), None) if meta.get("model") != "inherit" else None,
                                              source)
        style_dir = base / "output-styles"
        if style_dir.is_dir():
            for f in sorted(style_dir.glob("*.md")):
                meta, body = parse_frontmatter(f.read_text(errors="replace"))
                name = meta.get("name") or f.stem
                self.output_styles[name.lower()] = OutputStyle(
                    name, meta.get("description", ""), body.strip(), source,
                    str(meta.get("keep-coding-instructions", "false")).lower() == "true")
        skill_dir = base / "skills"
        if skill_dir.is_dir():
            for f in sorted(skill_dir.glob("*/SKILL.md")):
                meta, _ = parse_frontmatter(f.read_text(errors="replace"))
                name = meta.get("name") or f.parent.name
                self.skills[name] = Skill(name, meta.get("description", ""), f.parent, source)

    def _load_plugin(self, path: Path) -> None:
        manifest = path / ".claude-plugin" / "plugin.json"
        try:
            info = json.loads(manifest.read_text())
        except (OSError, json.JSONDecodeError):
            return
        name = info.get("name") or path.name
        self.plugins.append(name)
        self._scan_dir(path, f"plugin:{name}", prefix=f"{name}:", plugin_root=path)
        hooks_file = path / "hooks" / "hooks.json"
        if hooks_file.is_file():
            self._add_hooks(hooks_file, f"plugin:{name}", path)
        mcp_file = path / ".mcp.json"
        if mcp_file.is_file():
            try:
                servers = json.loads(mcp_file.read_text()).get("mcpServers", {})
            except json.JSONDecodeError:
                servers = {}
            for server, spec in servers.items():
                self.plugin_mcp[f"{name}-{server}"] = json.loads(
                    json.dumps(spec).replace("${CLAUDE_PLUGIN_ROOT}", str(path)))

    def _load_settings(self, path: Path, source: str) -> None:
        if not path.is_file():
            return
        self._add_hooks(path, source, path.parent.parent if source == "project" else None)
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return
        base = path.parent.parent if source == "project" else self.root
        perms = data.get("permissions") if isinstance(data.get("permissions"), dict) else {}
        # Rules that only take power away are always honored. Ones that let a cloned repo run things
        # on its own (allow rules, a status line command, a hands-off mode) wait for the user's OK.
        risky = {k: v for k, v in (("allow", perms.get("allow")), ("statusLine", data.get("statusLine")),
                                   ("defaultMode", perms.get("defaultMode"))) if v}
        if source == "project" and risky and not trust_store.is_trusted(self.root, f"settings:{path.name}", risky):
            self.pending_hooks.append({"file": str(path), "name": f"settings:{path.name}", "spec": risky})
            data = {k: v for k, v in data.items() if k != "statusLine"}
            perms = {k: v for k, v in perms.items() if k not in ("allow", "defaultMode")}
        self._apply_settings(data, perms, base)

    def _apply_settings(self, data: dict, perms: dict, base: Path) -> None:
        for kind in ("allow", "ask", "deny"):
            self.permissions.add(kind, perms.get(kind), base)
        if perms.get("defaultMode"):
            self.permissions.default_mode = perms["defaultMode"]
        for key, value in data.items():
            if key in ("hooks", "permissions"):
                continue
            if isinstance(value, dict) and isinstance(self.settings.get(key), dict):
                self.settings[key] = {**self.settings[key], **value}
            else:
                self.settings[key] = value

    def save_rule(self, kind: str, rule: str) -> Path:
        """Remember a permission rule for this project in .claude/settings.local.json (kept out of git)."""
        path = local_settings_file(self.root)
        try:
            data = json.loads(path.read_text()) if path.is_file() else {}
        except json.JSONDecodeError:
            data = {}
        perms = data.setdefault("permissions", {})
        rules = perms.setdefault(kind, [])
        if rule not in rules:
            rules.append(rule)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n")
        exclude_from_git(self.root, ".claude/settings.local.json")
        risky = {k: v for k, v in (("allow", perms.get("allow")), ("statusLine", data.get("statusLine")),
                                   ("defaultMode", perms.get("defaultMode"))) if v}
        if risky:  # the user wrote these rules themselves
            trust_store.trust(self.root, f"settings:{path.name}", risky)
        self.permissions.add(kind, [rule], self.root)
        return path

    def _add_hooks(self, path: Path, source: str, root: Path | None) -> None:
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return
        spec = data.get("hooks", data if any(k in HOOK_EVENTS for k in data) else {})
        if not spec:
            return
        if source == "project" and not trust_store.is_trusted(self.root, f"hooks:{path.name}", spec):
            self.pending_hooks.append({"file": str(path), "name": f"hooks:{path.name}", "spec": spec})
            return
        for event, groups in spec.items():
            if event not in HOOK_EVENTS or not isinstance(groups, list):
                continue
            for group in groups:
                for h in group.get("hooks", []):
                    if h.get("type", "command") == "command" and h.get("command"):
                        self.hooks.append(Hook(event, group.get("matcher", ""), h["command"], source,
                                               root, int(h.get("timeout", 60)), str(path)))

    def approve_hooks(self, file: str) -> None:
        """Approve a project's hooks, or the parts of its settings that need an OK."""
        for pending in [p for p in self.pending_hooks if p["file"] == file]:
            trust_store.trust(self.root, pending["name"], pending["spec"])
            self.pending_hooks.remove(pending)
            if pending["name"].startswith("settings:"):
                spec = pending["spec"]
                data = {"statusLine": spec["statusLine"]} if spec.get("statusLine") else {}
                self._apply_settings(data, {k: spec[k] for k in ("allow", "defaultMode") if k in spec},
                                     Path(file).parent.parent)
            else:
                self._add_hooks(Path(file), "project", self.root)

    # -- commands

    def find_command(self, name: str) -> Command | None:
        """By full name, or by the short name of a namespaced command ('greet' for 'demo:greet') when only one has it."""
        if name in self.commands:
            return self.commands[name]
        short = [c for key, c in self.commands.items() if key.rsplit(":", 1)[-1] == name]
        return short[0] if len(short) == 1 else None

    def expand(self, text: str) -> tuple[str, Command] | None:
        """'/name args' -> the command's prompt, or None if text isn't a known command."""
        m = re.match(r"^/([\w:.-]+)(?:\s+(.*))?$", text.strip(), re.S)
        cmd = m and self.find_command(m.group(1))
        if not cmd:
            return None
        args = (m.group(2) or "").strip()
        body = cmd.body.replace("$ARGUMENTS", args)
        words = args.split()
        body = re.sub(r"\$(\d)", lambda x: words[int(x.group(1)) - 1] if 0 < int(x.group(1)) <= len(words) else "", body)
        if cmd.root:
            body = body.replace("${CLAUDE_PLUGIN_ROOT}", str(cmd.root))
        if cmd.trusted:
            body = re.sub(r"!`([^`]+)`", lambda x: _run_inline(x.group(1), self.root), body)
        if "$ARGUMENTS" not in cmd.body and args:
            body += f"\n\nArguments: {args}"
        return body, cmd

    # -- hooks

    def run_hooks(self, event: str, payload: dict, tool: str | None = None) -> HookResult:
        result = HookResult()
        for hook in self.hooks:
            if hook.event != event or (tool and not _matches(hook.matcher, tool)):
                continue
            env = {**os.environ, "CLAUDE_PROJECT_DIR": str(self.root)}
            if hook.root:
                env["CLAUDE_PLUGIN_ROOT"] = str(hook.root)
            command = hook.command.replace("${CLAUDE_PLUGIN_ROOT}", str(hook.root or "")).replace(
                "$CLAUDE_PROJECT_DIR", str(self.root)).replace("${CLAUDE_PROJECT_DIR}", str(self.root))
            data = {"hook_event_name": event, "cwd": str(self.root), "session_id": payload.get("session_id", ""), **payload}
            try:
                proc = subprocess.run(command, shell=True, cwd=self.root, input=json.dumps(data), env=env,
                                      capture_output=True, text=True, timeout=hook.timeout)
            except subprocess.TimeoutExpired:
                continue
            if proc.returncode == 2:  # Claude Code's convention: exit 2 blocks, stderr says why
                result.block, result.decision = True, "deny"
                result.reason = (result.reason + "\n" + proc.stderr.strip()).strip()
                continue
            if proc.returncode != 0:
                continue
            out = proc.stdout.strip()
            try:
                parsed = json.loads(out) if out.startswith("{") else None
            except json.JSONDecodeError:
                parsed = None
            if parsed is None:
                if out and event in ("UserPromptSubmit", "SessionStart"):
                    result.context = (result.context + "\n" + out).strip()
                continue
            specific = parsed.get("hookSpecificOutput") or {}
            if parsed.get("decision") == "block" or parsed.get("continue") is False:
                result.block = True
                result.reason = (result.reason + "\n" + (parsed.get("reason") or parsed.get("stopReason") or "")).strip()
            decision = specific.get("permissionDecision")
            if decision in ("allow", "deny", "ask") and result.decision != "deny":
                result.decision = decision
                if decision == "deny":
                    result.block = True
                    result.reason = (result.reason + "\n" + specific.get("permissionDecisionReason", "")).strip()
            if specific.get("additionalContext"):
                result.context = (result.context + "\n" + specific["additionalContext"]).strip()
        return result

    def summary(self) -> dict:
        return {"plugins": self.plugins,
                "commands": [{"name": c.name, "description": c.description, "hint": c.argument_hint, "source": c.source}
                             for c in sorted(self.commands.values(), key=lambda c: c.name)],
                "agents": [{"name": a.name, "description": a.description} for a in self.agents.values()],
                "skills": [{"name": s.name, "description": s.description} for s in self.skills.values()],
                "hooks": len(self.hooks),
                "pending_hooks": [p["file"] for p in self.pending_hooks]}


def _matches(matcher: str, tool: str) -> bool:
    if matcher in ("", "*"):
        return True
    names = {tool, TOOL_ALIASES.get(tool, tool)}
    try:
        return any(re.fullmatch(matcher, n) for n in names)
    except re.error:
        return matcher in names


def hook_tool_input(tool: str, args: dict) -> dict:
    """Docks' tool arguments in the shape Claude Code hooks expect."""
    out = dict(args)
    if "path" in out and tool in ("write_file", "edit_file", "read_file"):
        out["file_path"] = out.pop("path")
    return out


def _run_inline(command: str, root: Path) -> str:
    try:
        proc = subprocess.run(command, shell=True, cwd=root, capture_output=True, text=True, timeout=30)
        return (proc.stdout + proc.stderr).strip()[:20_000]
    except subprocess.TimeoutExpired:
        return f"({command} timed out)"


# ------------------------------------------------------------------ installing plugins


def _state_path() -> Path:
    return docks_home() / "plugins.json"


def _state() -> dict:
    try:
        return json.loads(_state_path().read_text())
    except (OSError, json.JSONDecodeError):
        return {"disabled": []}


def installed_plugins() -> list[dict]:
    disabled = set(_state().get("disabled", []))
    out = []
    if plugins_dir().is_dir():
        for path in sorted(plugins_dir().iterdir()):
            manifest = path / ".claude-plugin" / "plugin.json"
            if manifest.is_file():
                try:
                    info = json.loads(manifest.read_text())
                except json.JSONDecodeError:
                    info = {}
                out.append({"name": path.name, "path": str(path), "enabled": path.name not in disabled,
                            "description": info.get("description", ""), "version": info.get("version", "")})
    return out


def set_enabled(name: str, enabled: bool) -> None:
    state = _state()
    disabled = set(state.get("disabled", []))
    (disabled.discard if enabled else disabled.add)(name)
    state["disabled"] = sorted(disabled)
    _state_path().parent.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(json.dumps(state, indent=2))


def find_plugins(folder: Path) -> list[Path]:
    """Plugin folders inside a checkout: the folder itself, plugins listed in a marketplace.json, or any
    folder that has .claude-plugin/plugin.json."""
    found = []
    market = folder / ".claude-plugin" / "marketplace.json"
    if market.is_file():
        try:
            for entry in json.loads(market.read_text()).get("plugins", []):
                src = entry.get("source")
                if isinstance(src, str) and (folder / src).is_dir():
                    found.append((folder / src).resolve())
        except json.JSONDecodeError:
            pass
    for manifest in folder.rglob(".claude-plugin/plugin.json"):
        if ".git" not in manifest.parts:
            found.append(manifest.parent.parent.resolve())
    return sorted(set(found))


def install(source: str, only: str | None = None) -> list[str]:
    """Install plugins from owner/repo, a git URL or a local folder. Returns the installed names."""
    from . import github
    local = Path(source).expanduser()
    if local.is_dir():
        checkout = local.resolve()
    else:
        repo = github.parse_repo(source)
        url = source if source.startswith(("http://", "https://", "git@")) else (f"https://github.com/{repo}.git" if repo else None)
        if not url:
            raise ValueError(f"not a folder, GitHub repo or git URL: {source}")
        checkout = docks_home() / "plugin-sources" / re.sub(r"[^\w.-]", "-", repo or url)
        if checkout.exists():
            subprocess.run(["git", "-C", str(checkout), "pull", "-q", "--ff-only"], capture_output=True, timeout=300)
        else:
            checkout.parent.mkdir(parents=True, exist_ok=True)
            proc = subprocess.run(["git", "clone", "-q", "--depth", "1", url, str(checkout)], capture_output=True,
                                  text=True, timeout=600)
            if proc.returncode != 0:
                raise ValueError(f"couldn't download {source}: {proc.stderr.strip()}")
    installed = []
    for folder in find_plugins(checkout):
        try:
            name = json.loads((folder / ".claude-plugin" / "plugin.json").read_text()).get("name") or folder.name
        except json.JSONDecodeError:
            name = folder.name
        if only and name != only:
            continue
        dest = plugins_dir() / re.sub(r"[^\w.-]", "-", name)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(folder, dest, ignore=shutil.ignore_patterns(".git"))
        installed.append(dest.name)
    if not installed:
        raise ValueError(f"no plugins found in {source}" + (f" named {only}" if only else ""))
    return installed


def remove(name: str) -> bool:
    dest = plugins_dir() / name
    if not dest.is_dir():
        return False
    shutil.rmtree(dest)
    set_enabled(name, True)  # forget any disabled flag
    return True
