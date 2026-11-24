"""Bowers access keys: Bowers' own security keys, for letting another device, app or script use your Bowers.

A key looks like `bwk_…`. It unlocks Bowers (Bowers Router, and later Bowers Cloud), not Claude or any other
service: Bowers then answers with the model it has (Bowers Local, or a key in your vault). Only a fingerprint
(SHA-256) is stored, so a key is shown once when it's made; revoke it any time and it stops working at once.
"""

import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

PREFIX = "bwk_"


def _path() -> Path:
    return Path(os.environ.get("DOCKS_HOME", Path.home() / ".docks")) / "access-keys.json"


def _load() -> list[dict]:
    try:
        return json.loads(_path().read_text())
    except (OSError, ValueError):
        return []


def _save(keys: list[dict]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(keys, f, indent=1)


def _digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create(name: str) -> str:
    """Make a new key. Returns it; this is the only time it can be seen."""
    name = (name or "").strip()[:60] or "Unnamed"
    key = PREFIX + secrets.token_urlsafe(32)
    keys = _load()
    keys.append({"id": key[:12], "name": name, "sha256": _digest(key), "created": int(time.time()), "last_used": None})
    _save(keys)
    return key


def listing() -> list[dict]:
    return [{k: v for k, v in key.items() if k != "sha256"} for key in _load()]


def revoke(key_id: str) -> bool:
    keys = _load()
    kept = [k for k in keys if k["id"] != key_id]
    _save(kept)
    return len(kept) < len(keys)


def any_keys() -> bool:
    return bool(_load())


def verify(given: str) -> bool:
    """Whether `given` is a live access key (constant-time comparison); notes when it was last used."""
    if not given or not given.startswith(PREFIX):
        return False
    digest, keys, found = _digest(given), _load(), None
    for k in keys:
        if hmac.compare_digest(k["sha256"], digest):
            found = k
    if found:
        found["last_used"] = int(time.time())
        _save(keys)
    return found is not None
