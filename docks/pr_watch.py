"""Watch pull requests: Docks checks them every couple of minutes and tells you when checks pass or fail, a
review comes in, new comments arrive, or the PR is merged or closed. The list is saved in ~/.docks/watched-prs.json.
"""

import json
import os
import threading
from pathlib import Path

from . import github

EVERY = 120  # seconds


def path() -> Path:
    return Path(os.environ.get("DOCKS_HOME", Path.home() / ".docks")) / "watched-prs.json"


def watched() -> list[dict]:
    try:
        data = json.loads(path().read_text())
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save(items: list[dict]) -> None:
    path().parent.mkdir(parents=True, exist_ok=True)
    path().write_text(json.dumps(items, indent=2) + "\n")


def watch(repo: str, number: int, on: bool = True) -> list[dict]:
    items = [i for i in watched() if not (i["repo"] == repo and i["number"] == number)]
    if on:
        try:
            state = github.pull_request_state(repo, number)
        except github.GitHubError:
            state = {}
        items.append({"repo": repo, "number": number, "last": state})
    _save(items)
    return items


def describe(old: dict, new: dict) -> list[str]:
    """What changed between two snapshots of a PR, in plain words."""
    out, name = [], f"{new['repo']}#{new['number']}"
    if new["state"] != old.get("state"):
        out.append(f"{name} was {new['state']}" if new["state"] in ("merged", "closed") else f"{name} is {new['state']} again")
    if new["checks"] != old.get("checks") and new["checks"] in ("success", "failure"):
        out.append(f"checks {'passed' if new['checks'] == 'success' else 'failed'} on {name}")
    if new["review"] and new["review"] != old.get("review"):
        out.append(f"{name}: {new['review']}")
    if new.get("comments", 0) > old.get("comments", 0):
        n = new["comments"] - old.get("comments", 0)
        out.append(f"{n} new comment{'s' if n > 1 else ''} on {name}")
    return out


def check_once() -> list[dict]:
    """Refresh every watched PR. Returns [{repo, number, title, url, changes: [...]}] for the ones that changed."""
    items, updates = watched(), []
    for item in items:
        try:
            new = github.pull_request_state(item["repo"], item["number"])
        except github.GitHubError:
            continue
        changes = describe(item.get("last") or {}, new) if item.get("last") else []
        if changes:
            updates.append({"repo": new["repo"], "number": new["number"], "title": new["title"], "url": new["url"],
                            "changes": changes})
        item["last"] = new
    _save([i for i in items if i.get("last", {}).get("state") not in ("merged", "closed")])  # done ones stop
    return updates


class Watcher:
    """Checks watched PRs in the background and calls on_update(update) for each change."""

    def __init__(self, on_update, every: int = EVERY):
        self.on_update, self.every = on_update, every
        self._stop = threading.Event()
        self._thread = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True, name="docks-pr-watch")
            self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self.every):
            if not watched() or not github.token():
                continue
            for update in check_once():
                try:
                    self.on_update(update)
                except Exception:
                    pass

    def stop(self) -> None:
        self._stop.set()
