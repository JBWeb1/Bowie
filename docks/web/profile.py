"""What Bowers knows about you for the greeting: your name. Saved in ~/.docks/profile.json."""

import json
import os
from pathlib import Path


def path() -> Path:
    return Path(os.environ.get("DOCKS_HOME", Path.home() / ".docks")) / "profile.json"


def load() -> dict:
    try:
        data = json.loads(path().read_text())
        return {"name": str(data.get("name", ""))[:60]}
    except (OSError, json.JSONDecodeError, AttributeError):
        return {"name": ""}


def save(name: str) -> dict:
    data = {"name": " ".join(name.split())[:60]}
    path().parent.mkdir(parents=True, exist_ok=True)
    path().write_text(json.dumps(data) + "\n")
    return data
