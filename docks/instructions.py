"""Instruction files ("memory"): what Docks should always know.

- Personal, for every project: ~/.docks/DOCKS.md and ~/.claude/CLAUDE.md
- The project's: DOCKS.md (or AGENTS.md / CLAUDE.md) in its root, shared with the team
- Yours, for this project only: DOCKS.local.md or CLAUDE.local.md (kept out of git)
- Folder-specific: a DOCKS.md / AGENTS.md / CLAUDE.md in a subfolder is read the first time Docks works there

Inside any of them, `@path/to/file` pulls in another file (relative to the one that mentions it; ~/ works).
Start a message with `#` to add a line to one of them.
"""

import os
import re
from pathlib import Path

from .permissions import exclude_from_git

PROJECT_FILES = ("DOCKS.md", "AGENTS.md", "CLAUDE.md")
LOCAL_FILES = ("DOCKS.local.md", "CLAUDE.local.md")
MAX_CHARS = 20_000
MAX_DEPTH = 4
IMPORT = re.compile(r"(?<![\w`@])@((?:~/|\.{1,2}/|/)?[\w.-]+(?:/[\w.-]+)*\.\w+)")


def user_files() -> list[Path]:
    home = Path(os.environ.get("DOCKS_HOME", Path.home() / ".docks"))
    claude = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    return [p for p in (home / "DOCKS.md", claude / "CLAUDE.md") if p.is_file()]


def project_file(root: Path) -> Path | None:
    return next((root / n for n in PROJECT_FILES if (root / n).is_file()), None)


def local_file(root: Path) -> Path | None:
    return next((root / n for n in LOCAL_FILES if (root / n).is_file()), None)


def read_with_imports(path: Path, depth: int = 0, seen: set | None = None) -> str:
    """The file's text, followed by any files it imports with @path (recursively, at most MAX_DEPTH deep)."""
    seen = seen if seen is not None else set()
    seen.add(path.resolve())
    try:
        text = path.read_text(errors="replace")[:MAX_CHARS]
    except OSError:
        return ""
    if depth >= MAX_DEPTH:
        return text
    imported = []
    in_code = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        for ref in IMPORT.findall(line):
            target = Path(os.path.expanduser(ref)) if ref.startswith("~/") else (path.parent / ref)
            target = target.resolve()
            if target.is_file() and target not in seen:
                body = read_with_imports(target, depth + 1, seen)
                imported.append(f'\n<imported file="{ref}">\n{body}\n</imported>')
    return text + "".join(imported)


def system_section(root: Path) -> str:
    parts = []
    for path in user_files():
        parts.append(f"Your user's personal instructions ({path}):\n{read_with_imports(path)}")
    for path, label in ((project_file(root), "Project instructions"), (local_file(root), "Personal notes for this project")):
        if path:
            parts.append(f"{label} from {path.name}:\n{read_with_imports(path)}")
    return "\n\n".join(parts)


def folder_instructions(root: Path, file_path: str, loaded: set) -> str:
    """Instructions from subfolders between the project root and `file_path` that haven't been read yet."""
    try:
        target = (root / file_path).resolve() if not Path(file_path).is_absolute() else Path(file_path).resolve()
        rel = target.relative_to(root.resolve())
    except (ValueError, OSError):
        return ""
    found = []
    folder = root.resolve()
    for part in rel.parts[:-1] if not target.is_dir() else rel.parts:
        folder = folder / part
        for name in PROJECT_FILES:
            candidate = folder / name
            if candidate.is_file() and candidate not in loaded:
                loaded.add(candidate)
                found.append(f'<folder-instructions path="{candidate.relative_to(root.resolve())}">\n'
                             f"{read_with_imports(candidate)}\n</folder-instructions>")
                break
    if not found:
        return ""
    return "\n\nInstructions for this part of the project (follow them here):\n" + "\n".join(found)


def note_path(root: Path, scope: str) -> Path:
    if scope == "user":
        return Path(os.environ.get("DOCKS_HOME", Path.home() / ".docks")) / "DOCKS.md"
    if scope == "local":
        return local_file(root) or root / "DOCKS.local.md"
    return project_file(root) or root / "DOCKS.md"


def add_note(root: Path, text: str, scope: str = "project") -> Path:
    """Append a line to an instruction file (scope: project, local or user)."""
    path = note_path(root, scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text() if path.is_file() else ""
    line = text.strip().lstrip("#").strip()
    if not line.startswith(("-", "*")):
        line = f"- {line}"
    sep = "" if not existing or existing.endswith("\n") else "\n"
    path.write_text(existing + sep + line + "\n")
    if scope == "local":
        exclude_from_git(root, path.name)
    return path
