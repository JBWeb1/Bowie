"""The Knowledge Graph (Bowers Aether): how your projects, files, memories, tools, history and goals connect,
plus a code map of which files in the project import which.

Everything is read from what Bowers already keeps on your computer; nothing is sent anywhere to build it.
"""

import json
import os
import re
import subprocess
import time
from collections import Counter
from pathlib import Path

from . import images, instructions, motion, sessions

CODE_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte", ".go", ".rs", ".java", ".rb", ".php", ".cs", ".dart", ".swift", ".kt"}
KINDS = {"image": {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}, "video": {".mp4", ".webm", ".mov"},
         "doc": {".md", ".txt", ".pdf", ".docx", ".pptx", ".xlsx", ".csv"}}
MAX_FILES = 4000


def project_files(root: Path) -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=root,
                             capture_output=True, text=True, timeout=10).stdout.splitlines()
        if out:
            return out[:MAX_FILES]
    except (OSError, subprocess.SubprocessError):
        pass
    found = []
    for dirpath, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "venv", ".venv", "dist", "build", "__pycache__")]
        for n in names:
            found.append(str(Path(dirpath, n).relative_to(root)))
            if len(found) >= MAX_FILES:
                return found
    return found


def _n(count: int, word: str) -> str:
    return f"{count:,} {word}{'' if count == 1 else 's'}"


def _memories(root: Path) -> list[str]:
    notes = []
    for f in [*instructions.user_files(), instructions.project_file(root), instructions.local_file(root)]:
        if f and f.is_file():
            for line in f.read_text(errors="replace").splitlines():
                line = line.strip()
                if line.startswith(("- ", "* ")) and len(line) > 4:
                    notes.append(line[2:].strip()[:120])
    return notes[-30:]


def overview(root: Path, agent=None, profile_name: str = "") -> dict:
    """The hub-and-spoke map of everything Bowers knows about you and this project."""
    from .web import library
    files = project_files(root)
    exts = Counter(Path(f).suffix.lower() for f in files)
    kinds = {k: sum(exts[e] for e in v) for k, v in KINDS.items()}
    kinds["code"] = sum(exts[e] for e in CODE_EXT)
    langs = [e.lstrip(".") for e, _ in Counter({e: c for e, c in exts.items() if e in CODE_EXT}).most_common(4)]
    projects = library.projects(root)
    recent = sessions.list_sessions(None, limit=8)
    pics, vids = images.gallery(root), motion.gallery(root)
    mcp = agent.mcp.summary() if agent is not None and agent.mcp else []
    plan = agent.plan if agent is not None else []
    from . import context_repos, github
    try:
        gh = github.whoami()
    except Exception:
        gh = None
    tools = [s["name"] for s in mcp] + (["GitHub"] if gh else []) + [c.get("repo", "") for c in context_repos.items(root)][:3]
    memories = _memories(root)
    goals = [{"text": p.get("text", ""), "done": p.get("status") == "done"} for p in plan][:6]
    nodes = [
        {"id": "you", "kind": "you", "title": profile_name or "You", "sub": "Creator · Builder · Dreamer", "link": "Personal Context"},
        {"id": "memories", "kind": "memories", "title": "Memories", "sub": _n(len(memories), "note"), "items": memories[-5:], "link": "Personal Context"},
        {"id": "projects", "kind": "projects", "title": "Projects", "sub": _n(len(projects), "project"),
         "items": [p["name"] for p in projects[:6]], "link": "Project Context", "page": "projects"},
        {"id": "files", "kind": "files", "title": "Files & Assets", "sub": _n(len(files), "file"),
         "counts": kinds, "link": "Content", "page": "library"},
        {"id": "tools", "kind": "tools", "title": "Tools & Apps", "sub": ", ".join(tools[:4]) or "Connect apps in Explore",
         "items": tools, "link": "Integrations", "page": "explore"},
        {"id": "knowledge", "kind": "knowledge", "title": "Knowledge", "sub": _n(kinds["doc"], "document"),
         "items": [f for f in files if Path(f).suffix.lower() in KINDS["doc"]][:6], "link": "Information"},
        {"id": "goals", "kind": "goals", "title": "Goals", "sub": f"{sum(not g['done'] for g in goals)} active",
         "goals": goals, "link": "Intent", "page": "tasks"},
        {"id": "motion", "kind": "motion", "title": "Bowers Motion", "sub": f"{_n(len(vids), 'video')} · {_n(len(pics), 'image')}",
         "media": [m["path"] for m in (vids + pics)[:5]], "link": "Creative Output", "page": "motion"},
        {"id": "forge", "kind": "forge", "title": "Bowers Forge", "sub": _n(kinds["code"], "code file") + (f" · {', '.join(langs)}" if langs else ""),
         "link": "Build Output", "page": "forge"},
        {"id": "history", "kind": "history", "title": "History", "sub": _n(len(recent), "recent chat"),
         "items": [s["name"] for s in recent[:5]], "link": "Timeline"},
    ]
    code = code_map(root, files)
    connections = len(nodes) + len(code["edges"]) + len(memories) + len(projects)
    return {"center": {"title": "Bowie", "sub": "AI Knowledge Core"}, "nodes": nodes,
            "recent": [{"title": s["name"], "kind": "Chat", "time": s["updated"]} for s in recent[:4]],
            "stats": {"projects": len(projects), "files": len(files), "connections": connections, "updated": time.time()},
            "code": code}


IMPORT_PATTERNS = [
    re.compile(r"^\s*from\s+(\.+[\w.]*|[\w.]+)\s+import\s+([\w*, ()]+)", re.M),   # python
    re.compile(r"^\s*import\s+([\w.]+)", re.M),                                   # python
    re.compile(r"""(?:import|export)\s[^'"]*?from\s+['"]([^'"]+)['"]"""),           # js/ts
    re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)"""),                          # js
    re.compile(r"""import\(\s*['"]([^'"]+)['"]\s*\)"""),                           # dynamic import
]


def _resolve(src: str, target: str, known: set[str]) -> str | None:
    base = Path(src).parent
    if target.startswith("."):
        if "/" in target or target in (".", ".."):  # js relative path
            cand = os.path.normpath(base / target)
            for suffix in ("", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".vue", ".svelte", "/index.ts", "/index.js", "/index.tsx"):
                if cand + suffix in known:
                    return cand + suffix
            return None
        dots = len(target) - len(target.lstrip("."))  # python relative module
        pkg = base
        for _ in range(dots - 1):
            pkg = pkg.parent
        mod = target.lstrip(".").replace(".", "/")
        cand = str(pkg / mod) if mod else str(pkg)
    else:
        cand = target.replace(".", "/")
    for option in (cand + ".py", cand + "/__init__.py"):
        option = os.path.normpath(option)
        if option in known:
            return option
        for k in known:  # src/ layouts: match by suffix
            if k.endswith("/" + option):
                return k
    return None


def code_map(root: Path, files: list[str] | None = None, limit: int = 400) -> dict:
    """Which code files import which (Python and JavaScript/TypeScript), for the graph's code view."""
    files = files if files is not None else project_files(root)
    code = [f for f in files if Path(f).suffix.lower() in CODE_EXT][:limit]
    known = set(code)
    edges = set()
    for f in code:
        try:
            text = (root / f).read_text(errors="replace")[:200_000]
        except OSError:
            continue
        for pat in IMPORT_PATTERNS:
            for m in pat.finditer(text):
                targets = [m.group(1)]
                if pat is IMPORT_PATTERNS[0] and m.group(1).strip(".") == "":  # from . import a, b
                    targets = [m.group(1) + name.strip() for name in m.group(2).replace("(", "").replace(")", "").split(",") if name.strip() and name.strip() != "*"]
                for t in targets:
                    hit = _resolve(f, t, known)
                    if hit and hit != f:
                        edges.add((f, hit))
    degree = Counter([a for a, _ in edges] + [b for _, b in edges])
    nodes = [{"id": f, "group": f.split("/")[0] if "/" in f else ".", "degree": degree[f]} for f in code if degree[f] or len(code) <= 60]
    return {"nodes": nodes, "edges": [list(e) for e in sorted(edges)]}


def as_json(data: dict) -> str:
    return json.dumps(data)
