"""Reference repositories: other GitHub repos Bowers can read while it works on this project, like the files you
add to a Claude Project. A shared library, your API's server, a design system, the docs.

    bowers context add acme/design-system            # or: --branch v2
    bowers context list
    bowers context sync                              # pull the latest (also done on its own, hourly)
    bowers context remove acme/design-system

Each one is a shallow clone in ~/.docks/context/, refreshed before work when it's over an hour old. Claude is
told where they are and can read and search them; permission rules stop it from editing them. The list is
kept per project in .docks/context.json (out of git).
"""

import hashlib
import json
import os
import subprocess
import threading
import time
from pathlib import Path

from . import github

SYNC_EVERY = 3600


def store() -> Path:
    return Path(os.environ.get("DOCKS_HOME", Path.home() / ".docks")) / "context"


def list_path(root: Path) -> Path:
    # Kept in your Bowers folder, not the project, so a cloned repo can't plant its own list.
    key = hashlib.sha1(str(root.resolve()).encode()).hexdigest()[:16]
    return Path(os.environ.get("DOCKS_HOME", Path.home() / ".docks")) / "projects" / key / "context.json"


def _load(root: Path) -> list[dict]:
    try:
        data = json.loads(list_path(root).read_text())
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save(root: Path, items: list[dict]) -> None:
    path = list_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, indent=2) + "\n")


def folder(repo: str, branch: str = "") -> Path:
    return store() / (repo.replace("/", "__") + (f"@{branch}" if branch else ""))


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=600,
                          env={**os.environ, **github._auth_env(), "GIT_TERMINAL_PROMPT": "0"})


def _clone(repo: str, branch: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    host = github.WEB.removeprefix("https://")
    args = ["clone", "--depth", "1", "--single-branch"] + (["--branch", branch] if branch else []) + \
           [f"https://{host}/{repo}.git", str(dest)]
    proc = _git(dest.parent, *args)
    if proc.returncode != 0:
        raise github.GitHubError(f"couldn't get {repo}: {(proc.stderr or proc.stdout).strip()[:300]}")


def _pull(dest: Path) -> str:
    fetch = _git(dest, "fetch", "--depth", "1", "origin")
    if fetch.returncode != 0:
        return f"couldn't update: {fetch.stderr.strip()[:200]}"
    _git(dest, "reset", "--hard", "FETCH_HEAD")
    return "up to date"


def items(root: Path) -> list[dict]:
    out = []
    for item in _load(root):
        path = folder(item["repo"], item.get("branch", ""))
        out.append({**item, "path": str(path), "present": path.is_dir()})
    return out


def add(root: Path, spec: str, branch: str = "") -> dict:
    repo = github.parse_repo(spec)
    if not repo:
        raise github.GitHubError(f"not a GitHub repository: {spec}")
    current = _load(root)
    if any(i["repo"] == repo and i.get("branch", "") == branch for i in current):
        return next(i for i in items(root) if i["repo"] == repo)
    dest = folder(repo, branch)
    if not dest.is_dir():
        _clone(repo, branch, dest)
    entry = {"repo": repo, "branch": branch, "synced": time.time()}
    _save(root, current + [entry])
    return {**entry, "path": str(dest), "present": True}


def remove(root: Path, spec: str) -> bool:
    repo = github.parse_repo(spec) or spec
    current = _load(root)
    kept = [i for i in current if i["repo"] != repo]
    _save(root, kept)
    return len(kept) != len(current)  # the clone stays: other projects may use it


def sync(root: Path, force: bool = False) -> list[str]:
    notes, current = [], _load(root)
    for item in current:
        dest = folder(item["repo"], item.get("branch", ""))
        if not force and dest.is_dir() and time.time() - float(item.get("synced", 0)) < SYNC_EVERY:
            continue
        try:
            note = _pull(dest) if dest.is_dir() else (_clone(item["repo"], item.get("branch", ""), dest) or "downloaded")
        except github.GitHubError as e:
            note = str(e)
        item["synced"] = time.time()
        notes.append(f"{item['repo']}: {note}")
    if notes:
        _save(root, current)
    return notes


def sync_in_background(root: Path) -> threading.Thread | None:
    if not _load(root):
        return None
    thread = threading.Thread(target=lambda: sync(root), daemon=True, name="docks-context-sync")
    thread.start()
    return thread


def system_note(root: Path) -> str:
    present = [i for i in items(root) if i["present"]]
    if not present:
        return ""
    lines = "\n".join(f"- {i['repo']}{' (' + i['branch'] + ')' if i['branch'] else ''}: {i['path']}" for i in present)
    return ("\nReference repositories (read-only copies, kept in sync from GitHub). Read and search them with "
            "absolute paths when the task touches them; never edit them:\n" + lines + "\n")


def deny_rules(root: Path) -> list[str]:
    """Permission rules that keep Bowers from changing the reference copies."""
    return [f"Edit(/{i['path']}/**)" for i in items(root)]
