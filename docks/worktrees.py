"""Parallel work in git worktrees: each task gets its own copy of the repo on its own branch, so several
Bowers sessions can work at once without stepping on each other. Merge the ones you like.

    bowers -w login-page "add a login page"     # works in .docks/worktrees/login-page on branch docks/login-page
    bowers worktree list
    bowers worktree merge login-page            # into the branch you have checked out
    bowers worktree remove login-page
"""

import re
import subprocess
import time
from pathlib import Path

from .permissions import exclude_from_git

FOLDER = ".docks/worktrees"
WORDS = ["amber", "brisk", "cedar", "delta", "ember", "fable", "glade", "harbor", "indigo", "juniper",
         "kestrel", "lumen", "maple", "nimbus", "orbit", "pine", "quartz", "river", "sable", "tidal"]


class WorktreeError(Exception):
    pass


def _git(cwd: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise WorktreeError((proc.stderr or proc.stdout).strip() or f"git {' '.join(args)} failed")
    return proc.stdout.strip()


def repo_root(path: Path) -> Path:
    try:
        top = _git(path, "rev-parse", "--path-format=absolute", "--git-common-dir")
    except WorktreeError:
        raise WorktreeError(f"{path} isn't in a git repository (worktrees need git; run `git init` first)")
    return Path(top).parent  # the main checkout, even when called from inside a worktree


def _clean_name(name: str) -> str:
    name = re.sub(r"[^\w.-]+", "-", name.strip()).strip("-.")
    if not name:
        raise WorktreeError("give the worktree a name, e.g. login-page")
    return name[:60]


def new_name(repo: Path) -> str:
    taken = {w["name"] for w in list_worktrees(repo)}
    for i in range(len(WORDS) * 2):
        name = f"{WORDS[(int(time.time()) + i) % len(WORDS)]}-{i + 1}"
        if name not in taken:
            return name
    return time.strftime("task-%H%M%S")


def path_of(repo: Path, name: str) -> Path:
    return repo / FOLDER / _clean_name(name)


def create(path: Path, name: str = "") -> Path:
    """The worktree folder for `name`, made from the current commit if it doesn't exist yet."""
    repo = repo_root(path)
    name = _clean_name(name) if name else new_name(repo)
    target = path_of(repo, name)
    if target.exists():
        return target
    if not _git(repo, "rev-parse", "--verify", "-q", "HEAD", check=False):
        raise WorktreeError("this repository has no commits yet; make a first commit, then use worktrees")
    exclude_from_git(repo, f"/{FOLDER}/")
    branch = f"docks/{name}"
    exists = _git(repo, "rev-parse", "--verify", "-q", f"refs/heads/{branch}", check=False)
    if exists:
        _git(repo, "worktree", "add", str(target), branch)
    else:
        _git(repo, "worktree", "add", "-b", branch, str(target), "HEAD")
    return target


def list_worktrees(path: Path) -> list[dict]:
    repo = repo_root(path)
    out, current = [], {}
    for line in _git(repo, "worktree", "list", "--porcelain").splitlines() + [""]:
        if line.startswith("worktree "):
            current = {"path": Path(line[9:])}
        elif line.startswith("branch "):
            current["branch"] = line[7:].removeprefix("refs/heads/")
        elif not line and current:
            p = current["path"]
            if p.parent == repo / FOLDER:
                changes = _git(p, "status", "--porcelain", check=False)
                base = _git(repo, "rev-parse", "--abbrev-ref", "HEAD", check=False)
                ahead = _git(repo, "rev-list", "--count", f"{base}..{current.get('branch', 'HEAD')}", check=False)
                out.append({"name": p.name, "path": str(p), "branch": current.get("branch", "(detached)"),
                            "changed_files": len([x for x in changes.splitlines() if x.strip()]),
                            "commits_ahead": int(ahead or 0)})
            current = {}
    return out


def merge(path: Path, name: str) -> str:
    """Merge a worktree's branch into the branch checked out in the main repo. Uncommitted work is committed first."""
    repo = repo_root(path)
    target = path_of(repo, name)
    if not target.exists():
        raise WorktreeError(f"no worktree named {name!r} (see `bowers worktree list`)")
    branch = f"docks/{_clean_name(name)}"
    notes = []
    if _git(target, "status", "--porcelain"):
        _git(target, "add", "-A")
        _git(target, "commit", "-m", f"Work from Bowers worktree {name}")
        notes.append("committed its unsaved changes")
    if _git(repo, "status", "--porcelain", "--untracked-files=no"):
        raise WorktreeError("your main checkout has uncommitted changes; commit or stash them, then merge")
    base = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    proc = subprocess.run(["git", "merge", "--no-ff", "--no-edit", "-m", f"Merge Bowers worktree {name}", branch],
                          cwd=repo, capture_output=True, text=True)
    if proc.returncode != 0:
        conflicts = _git(repo, "diff", "--name-only", "--diff-filter=U", check=False)
        if conflicts:
            raise WorktreeError(f"merging {branch} into {base} has conflicts in: {', '.join(conflicts.split())}. "
                                "Resolve them (or ask Bowers to) and commit, or run `git merge --abort`.")
        raise WorktreeError((proc.stderr or proc.stdout).strip())
    if "Already up to date" in proc.stdout:
        return f"{branch} had nothing new for {base}"
    return f"merged {branch} into {base}" + (f" ({'; '.join(notes)})" if notes else "")


def remove(path: Path, name: str, force: bool = False) -> str:
    repo = repo_root(path)
    target = path_of(repo, name)
    branch = f"docks/{_clean_name(name)}"
    if target.exists():
        if _git(target, "status", "--porcelain") and not force:
            raise WorktreeError(f"{name} has uncommitted changes; merge it first, or remove it with --force to throw them away")
        _git(repo, "worktree", "remove", *(["--force"] if force else []), str(target))
    deleted = subprocess.run(["git", "branch", "-D" if force else "-d", branch], cwd=repo, capture_output=True, text=True)
    kept = "" if deleted.returncode == 0 else f" (kept branch {branch}: it has commits that aren't merged; --force deletes it)"
    return f"removed {name}{kept}"
