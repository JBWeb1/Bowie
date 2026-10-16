"""Lessons Docks saves for itself, loaded into every future session."""

import os
from datetime import date
from pathlib import Path

MAX_CHARS = 20_000


def global_path() -> Path:
    return Path(os.environ.get("DOCKS_HOME", Path.home() / ".docks")) / "memory.md"


def project_path(root: Path) -> Path:
    return root / ".docks" / "memory.md"


def remember(root: Path, note: str, scope: str = "project") -> str:
    path = global_path() if scope == "global" else project_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(f"- ({date.today()}) {note.strip()}\n")
    return f"saved to {scope} memory"


def load(root: Path) -> str:
    sections = []
    for title, path in (("Lessons from past sessions", global_path()),
                        ("Lessons about this project", project_path(root))):
        if path.is_file():
            text = path.read_text()
            # Keep the newest lessons if the file has grown past the cap
            sections.append(f"{title}:\n{text[-MAX_CHARS:]}")
    return "\n\n".join(sections)
