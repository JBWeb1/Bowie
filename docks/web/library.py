"""Projects and the library of things you've made, for the browser's Projects and Library pages.

Projects: folders you've worked in with Bowers (from saved conversations), plus new ones made from the page in
~/Bowers Projects. Library: what's in the open project that you'd want to find again: generated images,
pictures, web pages, documents, and code you bookmarked.
"""

import os
import re
import subprocess
import time
from pathlib import Path

from .. import images, sessions
from ..tools import SKIP_DIRS

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
DOC_EXT = {".md", ".pdf", ".docx", ".txt", ".pptx", ".xlsx", ".csv"}
MAX_FILES = 4000


def projects_home() -> Path:
    return Path(os.environ.get("BOWERS_PROJECTS", Path.home() / "Bowers Projects"))


def _git_files(root: Path) -> list[str] | None:
    if not (root / ".git").exists():
        return None
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=root,
                             capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.splitlines() if out.returncode == 0 else None


def _walk(root: Path, limit: int = MAX_FILES):
    """The project's files, skipping what git ignores (or heavy and hidden folders when it isn't a git repo)."""
    tracked = _git_files(root)
    if tracked is not None:
        for rel in tracked[:limit]:
            parts = rel.split("/")
            if not any(p.startswith(".") or p in SKIP_DIRS for p in parts) and (root / rel).is_file():
                yield root / rel
        return
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if name.startswith("."):
                continue
            yield Path(dirpath) / name
            count += 1
            if count >= limit:
                return


def thumbnail_file(root: Path) -> Path | None:
    """A picture that represents a project: its newest generated image, else any image near the top."""
    root = root.expanduser()
    if not root.is_dir():
        return None
    made = images.gallery(root)
    if made:
        return root / made[0]["path"]
    for p in _walk(root, 400):
        if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp") and p.stat().st_size > 4000:
            return p
    return None


def projects(current: Path) -> list[dict]:
    seen = {}
    for s in sessions.list_sessions(None, limit=1000):
        root = s.get("root")
        if not root:
            continue
        item = seen.setdefault(root, {"root": root, "conversations": 0, "updated": 0})
        item["conversations"] += 1
        item["updated"] = max(item["updated"], s.get("updated", 0))
    home = projects_home()
    if home.is_dir():
        for d in home.iterdir():
            if d.is_dir() and not d.name.startswith("."):
                seen.setdefault(str(d), {"root": str(d), "conversations": 0, "updated": d.stat().st_mtime})
    seen.setdefault(str(current), {"root": str(current), "conversations": 0, "updated": time.time()})
    out = []
    for item in seen.values():
        path = Path(item["root"])
        if not path.is_dir():
            continue
        files = sum(1 for _ in _walk(path, 999))
        out.append({**item, "name": path.name, "files": files, "current": str(path) == str(current),
                    "thumbnail": thumbnail_file(path) is not None})
    out.sort(key=lambda p: (not p["current"], -p["updated"]))
    return out


def new_project(name: str) -> Path:
    name = re.sub(r"[^\w .-]+", "", name).strip(" .")
    if not name:
        raise ValueError("give the project a name")
    target = projects_home() / name
    if target.exists():
        raise ValueError(f"there's already a project called {name}")
    target.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=target, capture_output=True)
    (target / "README.md").write_text(f"# {name}\n\nMade with Bowers.\n")
    return target


def _bookmark_items(agent) -> list[dict]:
    out = []
    for b in agent.bookmarks:
        code = re.findall(r"```(\w*)\n(.*?)```", b["text"], re.S)
        out.append({"kind": "code" if code else "document", "title": (b["text"].strip().splitlines() or ["Bookmark"])[0][:80],
                    "detail": "Bookmarked reply", "text": b["text"], "updated": b.get("created", time.time()),
                    "source": "bookmark"})
    return out


def items(root: Path, agent=None) -> list[dict]:
    """Everything worth finding again in this project, newest first."""
    out, made = [], {i["path"]: i for i in images.gallery(root)}
    for rel, info in made.items():
        out.append({"kind": "design", "title": info["prompt"][:80], "path": rel, "detail": "Made with Bowers",
                    "updated": info.get("created", 0), "source": "generated"})
    for p in _walk(root):
        rel = str(p.relative_to(root))
        if rel in made:
            continue
        ext = p.suffix.lower()
        kind = ("image" if ext in IMAGE_EXT else "website" if ext == ".html" and rel.count("/") <= 2
                else "document" if ext in DOC_EXT and p.name.lower() not in ("license.md", "changelog.md") else None)
        if kind:
            out.append({"kind": kind, "title": p.stem if kind != "website" else (rel if p.name != "index.html" else (p.parent.name if rel != "index.html" else root.name)),
                        "path": rel, "detail": rel, "updated": p.stat().st_mtime, "source": "file"})
    if agent is not None:
        out += _bookmark_items(agent)
    out.sort(key=lambda i: -i["updated"])
    return out[:300]


def tasks(session) -> list[dict]:
    """Conversations with a plan, as tasks: progress, status and what's left. The open one is live."""
    agent, out, seen = session.agent, [], set()

    def entry(data: dict, live: bool) -> dict | None:
        plan = data.get("plan") or []
        if not plan and not live:
            return None
        done = sum(1 for i in plan if i.get("status") == "done")
        progress = round(100 * done / len(plan)) if plan else 0
        if live and session.approvals:
            status = "pending"
        elif live and session.busy:
            status = "active"
        elif plan and done == len(plan):
            status = "completed"
        elif done or (live and plan):
            status = "active"
        else:
            status = "not_started"
        root = data.get("root") or ""
        return {"id": data["id"], "title": data.get("name") or data.get("title") or "Untitled", "project": Path(root).name,
                "root": root, "progress": progress, "status": status, "plan": plan, "updated": data.get("updated", time.time()),
                "model": data.get("model", ""), "live": live}

    if agent.messages or agent.plan:
        current = entry({**agent.session_data(), "updated": time.time()}, True)
        if current:
            out.append(current)
            seen.add(agent.session_id)
    for s in sessions.list_sessions(None, limit=60):
        if s["id"] in seen:
            continue
        try:
            data = sessions.load(s["id"])
        except (OSError, ValueError):
            continue
        item = entry({**data, "updated": s["updated"]}, False)
        if item:
            out.append(item)
    return out
