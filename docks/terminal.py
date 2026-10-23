"""Terminal niceties: the status line, notifications, vim mode and keyboard shortcuts.

Status line: a line above the prompt. The built-in one shows the model, git branch, mode and context use.
Use your own with a command in settings.json (Claude Code's format); it gets the session as JSON on stdin
and its first line of output is shown:

    {"statusLine": {"type": "command", "command": "~/.docks/statusline.sh"}}     ("type": "none" hides it)

Notifications: when Bowers needs you (a permission, a question, a plan) or finishes a task that took a while,
the terminal rings its bell and sends a desktop notification (iTerm2, kitty, WezTerm, Ghostty, Windows Terminal
and others show it). Turn off with {"notifications": false}.

Keys: {"editorMode": "vim"} (or /vim) for vi keys. Shortcuts go in ~/.docks/keybindings.json, each sending a
command or text:  {"ctrl+g": "/commit", "alt+r": "/review", "shift+tab": "/mode next"}
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from . import ui

LONG_TASK = 30  # seconds; tasks longer than this notify when they finish
DEFAULT_KEYS = {"shift+tab": "/mode next"}


def _settings(agent) -> dict:
    return agent.ext.settings if agent.ext else {}


# ---------------------------------------------------------------- status line

def _branch(root: Path) -> str:
    try:
        return subprocess.run(["git", "branch", "--show-current"], cwd=root, capture_output=True,
                              text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def status_data(agent) -> dict:
    window = getattr(agent, "_window", None)
    return {"session_id": agent.session_id, "session_name": agent.session_name, "cwd": str(agent.root),
            "model": {"id": agent.model, "display_name": agent.model},
            "workspace": {"current_dir": str(agent.root), "project_dir": str(agent.root)},
            "mode": agent.active_mode, "output_style": {"name": agent.output_style},
            "context": {"used": agent.context_used, "window": window},
            "usage": dict(agent.usage), "sandbox": agent.sandbox is not None}


def status_line(agent) -> str:
    spec = _settings(agent).get("statusLine")
    if isinstance(spec, dict) and spec.get("type") == "none":
        return ""
    if isinstance(spec, dict) and spec.get("command"):
        try:
            proc = subprocess.run(os.path.expanduser(spec["command"]), shell=True, cwd=agent.root,
                                  input=json.dumps(status_data(agent)), capture_output=True, text=True, timeout=3)
            return (proc.stdout.strip().splitlines() or [""])[0]
        except (OSError, subprocess.SubprocessError):
            return ui.dim("(status line command failed)")
    parts = [agent.model_label]
    branch = _branch(agent.root)
    if branch:
        parts.append(f"⎇ {branch}")
    parts.append(f"mode {agent.active_mode}")
    if agent.output_style != "default":
        parts.append(f"style {agent.output_style}")
    if agent.sandbox is not None:
        parts.append("sandboxed")
    if agent.context_used:
        window = getattr(agent, "_window", None)
        used = agent.context_used
        parts.append(f"context {used / window:.0%}" if window else
                     f"context {used // 1000}k" if used >= 1000 else f"context {used} tokens")
    return ui.dim(" · ".join(parts))


# ---------------------------------------------------------------- notifications

def notify(message: str, title: str = "Bowers", out=None) -> None:
    out = out or sys.stdout
    if not out.isatty():
        return
    clean = message.replace("\x07", "").replace("\x1b", "").replace(";", ",")
    # bell, then OSC 9 (iTerm2, Windows Terminal, WezTerm, Ghostty) and OSC 777 (kitty, foot, rxvt)
    out.write(f"\x07\x1b]9;{title}: {clean}\x07\x1b]777;notify;{title};{clean}\x07")
    out.flush()


def notifications_on(agent) -> bool:
    return _settings(agent).get("notifications", True) is not False


# ---------------------------------------------------------------- keys

def _readline():
    try:
        import readline
        return readline
    except ImportError:
        return None


def _key(spec: str) -> str | None:
    """'ctrl+g' -> '\\C-g', 'alt+r' -> '\\er', 'shift+tab' -> '\\e[Z' (readline key names)."""
    spec = spec.lower().replace(" ", "")
    if spec in ("shift+tab", "backtab"):
        return r"\e[Z"
    mods, _, key = spec.rpartition("+")
    if len(key) != 1:
        return None
    if mods in ("ctrl", "control", "c"):
        return rf"\C-{key}"
    if mods in ("alt", "meta", "option", "m"):
        return rf"\e{key}"
    return None


def keybindings_path() -> Path:
    return Path(os.environ.get("DOCKS_HOME", Path.home() / ".docks")) / "keybindings.json"


def setup_keys(agent) -> list[str]:
    """Apply vim mode and shortcuts to readline. Returns notes about anything that couldn't be applied."""
    rl = _readline()
    if rl is None:
        return []
    libedit = "libedit" in (rl.__doc__ or "")
    vim = _settings(agent).get("editorMode") == "vim"
    if libedit:  # macOS's built-in Python
        rl.parse_and_bind("bind -v" if vim else "bind -e")
        return []
    rl.parse_and_bind(f"set editing-mode {'vi' if vim else 'emacs'}")
    keys = dict(DEFAULT_KEYS)
    notes = []
    try:
        custom = json.loads(keybindings_path().read_text()) if keybindings_path().is_file() else {}
        keys.update({k: v for k, v in custom.items() if isinstance(v, str)})
    except json.JSONDecodeError as e:
        notes.append(f"keybindings.json isn't valid JSON: {e}")
    for spec, action in keys.items():
        key = _key(spec)
        if key is None:
            notes.append(f"unknown key {spec!r} in keybindings.json (use ctrl+x, alt+x or shift+tab)")
            continue
        text = action.replace("\\", "\\\\").replace('"', '\\"')
        # clear what's typed (it stays in the kill ring: ctrl+y brings it back), then send the action
        rl.parse_and_bind(f'"{key}": "\\C-a\\C-k{text}\\n"')
    return notes


def save_setting(agent, key: str, value) -> Path:
    """Change a setting now and remember it in ~/.docks/settings.json."""
    path = Path(os.environ.get("DOCKS_HOME", Path.home() / ".docks")) / "settings.json"
    try:
        data = json.loads(path.read_text()) if path.is_file() else {}
    except json.JSONDecodeError:
        data = {}
    data[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    agent.ext.settings[key] = value
    return path


def set_vim(agent, on: bool) -> Path:
    """Turn vim mode on or off and remember it in ~/.docks/settings.json."""
    path = save_setting(agent, "editorMode", "vim" if on else "normal")
    setup_keys(agent)
    return path

