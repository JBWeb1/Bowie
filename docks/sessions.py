"""Saved conversations: every session is written to ~/.docks/sessions/<id>.json after each turn,
so it can be listed, renamed and resumed later (`bowers --resume`, `/resume`, the browser's History)."""

import json
import os
import time
import uuid
from pathlib import Path


def sessions_dir() -> Path:
    return Path(os.environ.get("DOCKS_HOME", Path.home() / ".docks")) / "sessions"


def new_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def plain(value):
    """Turn SDK content blocks into plain JSON that can be saved and sent back to the API unchanged."""
    if hasattr(value, "model_dump"):
        data = value.model_dump(mode="json", exclude_none=True)
        data.pop("parsed_output", None)  # a client-side helper field, never part of the API shape
        return data
    if hasattr(value, "__dict__") and not isinstance(value, type):  # simple objects (and test doubles)
        return {k: plain(v) for k, v in vars(value).items() if v is not None}
    if isinstance(value, list):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    return value


def save(data: dict) -> None:
    path = sessions_dir() / f"{data['id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({**data, "updated": time.time()}))
    tmp.replace(path)  # never leave a half-written session behind


def load(session_id: str) -> dict:
    path = sessions_dir() / f"{session_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"no saved session {session_id!r}")
    return json.loads(path.read_text())


def list_sessions(root: Path | None = None, limit: int = 50) -> list[dict]:
    """Newest first. With root, only sessions for that project."""
    out = []
    folder = sessions_dir()
    if not folder.is_dir():
        return out
    for path in folder.glob("*.json"):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if root is not None and data.get("root") != str(root):
            continue
        out.append({"id": data["id"], "name": data.get("name") or data.get("title") or "Untitled",
                    "title": data.get("title", ""), "updated": data.get("updated", 0),
                    "root": data.get("root"), "turns": len(data.get("turns", []))})
    out.sort(key=lambda s: s["updated"], reverse=True)
    return out[:limit]


def find(query: str, root: Path | None = None) -> str | None:
    """A session id from an id, a unique id prefix, or a name (case-insensitive)."""
    sessions = list_sessions(root, limit=1000)
    for s in sessions:
        if s["id"] == query:
            return s["id"]
    by_name = [s for s in sessions if s["name"].lower() == query.lower()]
    if by_name:
        return by_name[0]["id"]
    by_prefix = [s for s in sessions if s["id"].startswith(query)]
    return by_prefix[0]["id"] if len(by_prefix) == 1 else None
