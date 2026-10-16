"""File checkpoints: a snapshot of the project before every task, so any task can be undone.

Snapshots live in a separate git store under ~/.docks/checkpoints/, never in the project's own .git,
so your history, branches and staging area are untouched. Files your .gitignore excludes, and the
usual heavy folders (node_modules, virtualenvs, build output), are left out.
Only files inside the project can be restored; effects of commands outside it (installed packages,
databases, pushes) can't be undone.
"""

import hashlib
import os
import subprocess
import time
from pathlib import Path

EXCLUDES = ["node_modules/", ".venv/", "venv/", "__pycache__/", "dist/", "build/", ".next/", ".git/",
            ".docks/", "*.pyc", ".DS_Store"]
MAX_FILE_BYTES = 20_000_000


class CheckpointError(Exception):
    pass


class Checkpoints:
    def __init__(self, root: Path):
        self.root = root
        self.home = Path(os.environ.get("DOCKS_HOME", Path.home() / ".docks")).resolve()
        self.store = self.home / "checkpoints" / hashlib.sha256(str(root).encode()).hexdigest()[:16]
        self.ready = False
        # Snapshotting a whole home folder or drive would be slow and huge; skip it there.
        self.enabled = root.resolve() not in (Path.home().resolve(), Path(root.anchor))

    def _git(self, *args: str, check: bool = True) -> str:
        env = {**os.environ, "GIT_DIR": str(self.store), "GIT_WORK_TREE": str(self.root),
               "GIT_AUTHOR_NAME": "docks", "GIT_AUTHOR_EMAIL": "docks@localhost",
               "GIT_COMMITTER_NAME": "docks", "GIT_COMMITTER_EMAIL": "docks@localhost"}
        proc = subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false", *args],
                              cwd=self.root, env=env, capture_output=True, text=True, timeout=120)
        if check and proc.returncode != 0:
            raise CheckpointError((proc.stderr or proc.stdout).strip())
        return proc.stdout.strip()

    def _init(self) -> None:
        if self.ready:
            return
        if not (self.store / "HEAD").exists():
            self.store.mkdir(parents=True, exist_ok=True)
            self._git("init", "-q")
            (self.store / "info").mkdir(exist_ok=True)
            excludes = list(EXCLUDES)
            if self.home.is_relative_to(self.root.resolve()):  # never snapshot our own store
                excludes.append(f"/{self.home.relative_to(self.root.resolve()).as_posix()}/")
            (self.store / "info" / "exclude").write_text("\n".join(excludes) + "\n")
        self.ready = True

    def snapshot(self, label: str) -> str | None:
        """Record the current files. Returns a checkpoint id, or None if snapshots aren't possible here."""
        if not self.enabled:
            return None
        try:
            self._init()
            self._git("add", "-A", ".")
            big = [p for p in self._git("diff", "--cached", "--name-only").splitlines()
                   if (self.root / p).is_file() and (self.root / p).stat().st_size > MAX_FILE_BYTES]
            if big:
                self._git("rm", "-q", "--cached", "--", *big)
            self._git("commit", "-q", "--allow-empty", "-m", f"{time.strftime('%H:%M:%S')} {label[:80]}")
            return self._git("rev-parse", "HEAD")
        except (CheckpointError, OSError, subprocess.TimeoutExpired):
            return None  # not fatal: Docks still works, just without undo here

    def restore(self, checkpoint: str) -> list[str]:
        """Put every file back as it was at the checkpoint. Returns the paths that changed."""
        self._init()
        now = self.snapshot("before restore")
        if not now:
            raise CheckpointError("couldn't record the current state, so nothing was restored")
        changed = self._git("diff", "--name-status", "--no-renames", checkpoint, now).splitlines()
        for line in changed:
            status, path = line.split("\t", 1)
            target = self.root / path
            if status == "A":  # created after the checkpoint
                target.unlink(missing_ok=True)
                parent = target.parent
                while parent != self.root and parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent
        if any(not line.startswith("A\t") for line in changed):
            self._git("checkout", checkpoint, "--", ".")  # rewrites modified and deleted files
        self.snapshot("after restore")
        return [line.split("\t", 1)[1] for line in changed]
