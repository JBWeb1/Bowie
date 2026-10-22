"""Long-running processes the agent starts: dev servers, watchers, bots.

Each process keeps its recent output, and the first local URL it prints (like
http://localhost:5173) is picked up so the preview can show the running app.
"""

import atexit
import itertools
import os
import re
import signal
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

URL_RE = re.compile(r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1?\]):(\d{2,5})[^\s'\")\]]*")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


class Proc:
    def __init__(self, pid_id: int, command: str, root: Path, on_change=None, sandbox=None):
        self.id, self.command = pid_id, command
        self.lines = deque(maxlen=2000)
        self.url = None
        self.on_change = on_change
        argv = sandbox.argv(command, server=True) if sandbox else None
        self.popen = subprocess.Popen(argv or command, shell=argv is None, cwd=root, stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True,
                                      errors="replace", start_new_session=True,
                                      env={**os.environ, "FORCE_COLOR": "0", "BROWSER": "none"})
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self.popen.stdout:
            line = ANSI_RE.sub("", line.rstrip("\n"))
            self.lines.append(line)
            if not self.url and (m := URL_RE.search(line)):
                self.url = f"http://localhost:{m.group(1)}/"
                if self.on_change:
                    self.on_change(self)
        self.popen.wait()
        if self.on_change:
            self.on_change(self)

    @property
    def running(self) -> bool:
        return self.popen.poll() is None

    def tail(self, n: int = 60) -> str:
        return "\n".join(list(self.lines)[-n:])

    def stop(self) -> None:
        if self.running:
            try:
                os.killpg(self.popen.pid, signal.SIGTERM)  # the whole group: npm + vite + esbuild…
                self.popen.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(self.popen.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def info(self) -> dict:
        return {"id": self.id, "command": self.command, "url": self.url, "running": self.running,
                "exit_code": None if self.running else self.popen.returncode}


class ProcessManager:
    def __init__(self, root: Path, on_change=None):
        self.root = root
        self.procs: dict[int, Proc] = {}
        self.ids = itertools.count(1)
        self.on_change = on_change
        self.sandbox = None  # set by the agent when commands are sandboxed
        atexit.register(self.stop_all)

    def start(self, command: str, wait: float = 15) -> str:
        proc = Proc(next(self.ids), command, self.root, self._changed, self.sandbox)
        self.procs[proc.id] = proc
        # Give it a moment: dev servers print their URL within a few seconds; crashes show up fast too.
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline and proc.running and not proc.url:
            time.sleep(0.2)
        if not proc.running:
            return f"process {proc.id} exited with code {proc.popen.returncode}:\n{proc.tail()}"
        where = f"serving at {proc.url} (shown in the user's preview)" if proc.url else "running (no URL seen yet)"
        return f"process {proc.id} is {where}\n--- output so far ---\n{proc.tail(40)}"

    def _changed(self, proc: Proc) -> None:
        if self.on_change:
            self.on_change(proc.info())

    def logs(self, process_id: int, lines: int = 100) -> str:
        proc = self.procs.get(process_id)
        if not proc:
            return f"no process {process_id}"
        state = "running" if proc.running else f"exited with code {proc.popen.returncode}"
        return f"process {process_id} ({proc.command}) is {state}\n{proc.tail(lines)}"

    def stop(self, process_id: int) -> str:
        proc = self.procs.get(process_id)
        if not proc:
            return f"no process {process_id}"
        proc.stop()
        return f"stopped process {process_id}"

    def stop_all(self) -> None:
        for proc in self.procs.values():
            proc.stop()

    def list(self) -> list[dict]:
        return [p.info() for p in self.procs.values()]
