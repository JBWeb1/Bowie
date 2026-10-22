"""Permission rules: which tool calls run without asking, which always ask, and which never run.

Written in Claude Code's settings.json format, so the same rules work in both:

    {"permissions": {
        "allow": ["Bash(npm test:*)", "Bash(git status)", "Edit(src/**)", "WebFetch(domain:docs.python.org)"],
        "ask":   ["Bash(git push:*)"],
        "deny":  ["Read(./.env)", "Read(**/*.pem)", "Bash(curl:*)", "mcp__github__delete_repo"],
        "defaultMode": "acceptEdits"}}

A rule is a tool name (Claude Code's or Docks'), optionally with a specifier in parentheses:
- Bash(cmd)        exactly that command; Bash(prefix:*) anything starting with it; * is a wildcard.
                   Commands joined with && ; || or | must have every part allowed, and any denied part
                   denies the whole command.
- Read/Edit(path)  gitignore-style patterns: `src/**`, `*.env` (any folder), `./x` or `x` (from the project),
                   `/x` (from the project root), `~/x` (home), `//x` (an absolute path). Edit covers every
                   tool that changes files; Read covers reading and searching.
- WebFetch(domain:example.com)
- mcp__server (every tool of that server) or mcp__server__tool

deny beats ask beats allow.
"""

import fnmatch
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

# Docks tool -> the Claude Code rule names that cover it
RULE_NAMES = {
    "bash": ("Bash",), "start_process": ("Bash",),
    "read_file": ("Read",), "glob": ("Read", "Glob"), "grep": ("Read", "Grep"),
    "write_file": ("Edit", "Write"), "edit_file": ("Edit",),
    "web_fetch": ("WebFetch",), "web_search": ("WebSearch",),
    "browser": ("Browser",), "code_intel": ("LSP",), "delegate": ("Task",), "generate_image": ("ImageGen",),
}
FILE_TOOLS = {"read_file", "glob", "grep", "write_file", "edit_file"}
SHELL_TOOLS = {"bash", "start_process"}
RULE = re.compile(r"^\s*([\w-]+)\s*(?:\((.*)\))?\s*$", re.S)
SPLIT = re.compile(r"&&|\|\||;|\||\n")


@dataclass
class Rule:
    text: str
    tool: str
    spec: str | None
    base: Path  # what relative path patterns are relative to


def parse(text: str, base: Path) -> Rule | None:
    m = RULE.match(text or "")
    if not m:
        return None
    spec = m.group(2)
    return Rule(text.strip(), m.group(1), spec.strip() if spec is not None else None, base)


def _glob_regex(pattern: str) -> re.Pattern:
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out + r"(?:/.*)?$")  # a folder pattern covers everything inside it


def path_matches(spec: str, path: Path, base: Path) -> bool:
    if spec.startswith("//"):
        pattern = spec[1:]
    elif spec.startswith("~/"):
        pattern = str(Path.home()) + spec[1:]
    elif spec.startswith("/"):
        pattern = str(base) + spec
    elif spec.startswith("./"):
        pattern = f"{base}/{spec[2:]}"
    elif "/" not in spec.rstrip("/"):
        pattern = f"**/{spec}"  # like .gitignore: a bare name matches in any folder
    else:
        pattern = f"{base}/{spec}"
    if not pattern.startswith("/") and not pattern.startswith("**"):
        pattern = f"{base}/{pattern}"
    text = str(path)
    if pattern.startswith("**/"):
        return bool(_glob_regex(pattern).match(text)) or bool(_glob_regex(pattern[3:]).match(path.name))
    return bool(_glob_regex(pattern).match(text))


def _command_matches(spec: str, command: str) -> bool:
    command = " ".join(command.split())
    if spec.endswith(":*"):
        prefix = " ".join(spec[:-2].split())
        return command == prefix or command.startswith(prefix + " ")
    spec = " ".join(spec.split())
    if "*" in spec:
        return fnmatch.fnmatchcase(command, spec)
    return command == spec


def command_parts(command: str) -> list[str]:
    return [p.strip() for p in SPLIT.split(command) if p.strip()]


@dataclass
class Permissions:
    root: Path
    allow: list = field(default_factory=list)
    ask: list = field(default_factory=list)
    deny: list = field(default_factory=list)
    default_mode: str | None = None

    def add(self, kind: str, rules: list, base: Path) -> None:
        for text in rules or []:
            rule = parse(text, base) if isinstance(text, str) else None
            if rule:
                getattr(self, kind).append(rule)

    def _names(self, tool: str) -> set:
        return {tool, *RULE_NAMES.get(tool, ())}

    def _hits(self, rule: Rule, tool: str, args: dict, part: str | None = None) -> bool:
        if tool.startswith("mcp__") and rule.spec is None:
            return tool == rule.tool or tool.startswith(rule.tool + "__")
        if rule.tool not in self._names(tool):
            return False
        if rule.spec is None or rule.spec in ("", "*"):
            return True
        if tool in SHELL_TOOLS:
            return _command_matches(rule.spec, part if part is not None else str(args.get("command", "")))
        if tool in FILE_TOOLS:
            raw = args.get("path") or "."
            target = (Path(raw) if Path(raw).is_absolute() else self.root / raw).resolve()
            return path_matches(rule.spec, target, rule.base)
        if tool == "web_fetch" and rule.spec.startswith("domain:"):
            host = urlparse(str(args.get("url", ""))).hostname or ""
            domain = rule.spec[7:].lower()
            return host == domain or host.endswith("." + domain)
        if tool == "browser" and rule.spec.startswith("domain:"):
            host = urlparse(str(args.get("url", ""))).hostname or ""
            return host == rule.spec[7:].lower()
        return False

    def check(self, tool: str, args: dict) -> tuple[str | None, str]:
        """("deny" | "ask" | "allow" | None, the rule that decided)."""
        if not isinstance(args, dict):
            args = {}
        parts = command_parts(str(args.get("command", ""))) if tool in SHELL_TOOLS else [None]
        parts = parts or [""]
        for kind in ("deny", "ask"):
            for rule in getattr(self, kind):
                if any(self._hits(rule, tool, args, p) for p in parts):
                    return kind, rule.text
        if tool in SHELL_TOOLS:  # every piece of a compound command must be allowed
            decided = []
            for p in parts:
                rule = next((r for r in self.allow if self._hits(r, tool, args, p)), None)
                if rule is None:
                    return None, ""
                decided.append(rule.text)
            return "allow", ", ".join(dict.fromkeys(decided))
        for rule in self.allow:
            if self._hits(rule, tool, args):
                return "allow", rule.text
        return None, ""

    def summary(self) -> dict:
        return {k: [r.text for r in getattr(self, k)] for k in ("allow", "ask", "deny")}


def suggest_rule(tool: str, args: dict) -> str:
    """The rule to remember when the user says "always allow" for this call."""
    names = RULE_NAMES.get(tool)
    if tool in SHELL_TOOLS:
        first = command_parts(str(args.get("command", "")))
        words = first[0].split() if first else []
        # the program plus its sub-command or script (git status, npm run build, python3 manage.py), no flags
        size = 3 if len(words) > 1 and words[1] in ("run", "exec", "x", "-m") else 2
        words = [w for w in words[:size] if re.fullmatch(r"[\w./@+-]+", w) and not (w.startswith("-") and w != "-m")]
        return f"Bash({' '.join(words)}:*)" if words else "Bash"
    return names[0] if names else tool


def is_local_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "0.0.0.0", "::1") or host.endswith(".localhost") or url.startswith("file:")


def local_settings_file(root: Path) -> Path:
    return root / ".claude" / "settings.local.json"


def exclude_from_git(root: Path, relative: str) -> None:
    """Keep a personal file out of commits without touching the shared .gitignore."""
    exclude = root / ".git" / "info" / "exclude"
    if not exclude.parent.is_dir():
        return
    try:
        lines = exclude.read_text().splitlines() if exclude.is_file() else []
        if relative not in lines:
            exclude.write_text("\n".join(lines + [relative]) + "\n")
    except OSError:
        pass

