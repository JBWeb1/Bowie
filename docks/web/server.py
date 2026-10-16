"""`docks web`: run the agent from a browser.

Two servers: the app (UI + API) and a static preview of the project on the
next port. They are different origins, so a page being previewed can never
reach the API. The API requires a per-run token sent in a header; the token
reaches the browser in the URL fragment, which is never sent to the server
or written to logs.
"""

import functools
import json
import mimetypes
import queue
import secrets
import threading
import uuid
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path

from .. import github
from ..agent import Agent
from ..tools import SKIP_DIRS
from ..ui import _summarize_args

MAX_HISTORY = 20_000
MAX_IMAGES = 5
MAX_IMAGE_B64 = 7_000_000  # ~5 MB of image data
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
MAX_FILE_BYTES = 300_000


def _clip(value, limit=4000):
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + f"\n… ({len(value) - limit} more chars)"
    return value


class Session:
    """One agent plus everything the browser needs: an event log and pending approvals."""

    def __init__(self, agent: Agent):
        self.agent = agent
        self.lock = threading.Lock()
        self.history = []
        self.subscribers = []
        self.approvals = {}
        self.busy = False
        agent.display = WebDisplay(self)
        agent.procs.on_change = lambda info: self.publish({"type": "process", **info})

    def publish(self, event: dict) -> None:
        with self.lock:
            last = self.history[-1] if self.history else None
            if (last and event["type"] in ("text", "progress") and last["type"] == event["type"]
                    and last.get("id") == event.get("id")):
                self.history[-1] = {**last, "text": last["text"] + event["text"]}  # merge deltas for replay
            else:
                self.history.append(event)
                del self.history[:-MAX_HISTORY]
            for q in self.subscribers:
                q.put(event)

    def subscribe(self):
        q = queue.Queue()
        with self.lock:
            backlog = list(self.history)
            self.subscribers.append(q)
        return backlog, q

    def unsubscribe(self, q) -> None:
        with self.lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    def start_turn(self, text: str, images: list | None = None) -> bool:
        with self.lock:
            if self.busy:
                return False
            self.busy = True
        images = images or []
        self.publish({"type": "user", "text": text,
                      "images": [f"data:{i['media_type']};base64,{i['data']}" for i in images]})
        content = [{"type": "image", "source": {"type": "base64", **i}} for i in images]
        content = content + [{"type": "text", "text": text}] if content else text
        threading.Thread(target=self._run, args=(content,), daemon=True).start()
        return True

    def _run(self, content) -> None:
        try:
            self.agent.run(content)
        finally:
            with self.lock:
                self.busy = False
            self.publish({"type": "idle"})

    def answer(self, approval_id: str, answer: str) -> bool:
        entry = self.approvals.get(approval_id)
        if not entry:
            return False
        entry["answer"] = answer
        entry["event"].set()
        return True

    def stop(self) -> None:
        self.agent.stop()
        for approval_id in list(self.approvals):
            self.answer(approval_id, "no")

    def state(self) -> dict:
        a = self.agent
        return {"root": str(a.root), "model": a.model, "effort": a.effort, "auto_approve": a.auto_approve,
                "busy": self.busy, "usage": a.usage, "processes": a.procs.list(),
                "mcp": a.mcp.summary() if a.mcp else []}


class WebStream:
    def __init__(self, session: Session):
        self.session = session
        self.block = None

    def handle(self, event) -> None:
        if event.type == "text" and event.text:
            self._emit("text", event.text)
        elif event.type == "thinking" and event.thinking:
            self._emit("progress", event.thinking)
        elif event.type == "content_block_stop":
            self.block = None
            block = event.content_block
            if block.type == "server_tool_use":
                self.session.agent.display.tool_call(block.name, block.input if isinstance(block.input, dict) else {})

    def _emit(self, kind: str, text: str) -> None:
        if self.block is None or self.block[0] != kind:
            self.block = (kind, uuid.uuid4().hex[:8])
        self.session.publish({"type": kind, "id": self.block[1], "text": text})

    def finish(self) -> None:
        self.block = None


class WebDisplay:
    """Implements the same interface as ui.TerminalUI, but publishes to the browser."""

    def __init__(self, session: Session):
        self.session = session

    def stream(self):
        return WebStream(self.session)

    def tool_call(self, name: str, args: dict) -> None:
        self.session.publish({"type": "tool_call", "name": name, "summary": _clip(_summarize_args(name, args), 300),
                              "args": {k: _clip(v) for k, v in args.items()}})

    def tool_output(self, output: str, is_error: bool = False) -> None:
        self.session.publish({"type": "tool_output", "text": _clip(output, 20_000), "error": is_error})

    def warn(self, msg: str) -> None:
        self.session.publish({"type": "warn", "text": msg})

    def error(self, msg: str) -> None:
        self.session.publish({"type": "error", "text": msg})

    def confirm(self, name: str, args: dict) -> str:
        approval_id = uuid.uuid4().hex[:12]
        entry = {"event": threading.Event(), "answer": "no"}
        self.session.approvals[approval_id] = entry
        self.session.publish({"type": "approval", "id": approval_id, "name": name,
                              "args": {k: _clip(v, 20_000) for k, v in args.items()}})
        while not entry["event"].wait(0.5):
            if self.session.agent.cancelled.is_set():
                break
        self.session.approvals.pop(approval_id, None)
        self.session.publish({"type": "approval_done", "id": approval_id, "answer": entry["answer"]})
        return entry["answer"]

    def turn_done(self, usage: dict) -> None:
        self.session.publish({"type": "usage", "usage": dict(usage)})


def list_files(root: Path, limit: int = 3000) -> list[str]:
    out = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts) or not path.is_file():
            continue
        out.append(rel.as_posix())
        if len(out) >= limit:
            break
    return out


def make_handler(session: Session, token: str, preview: dict):
    page = resources.files("docks.web").joinpath("app.html").read_text()
    root = session.agent.root

    class Handler(BaseHTTPRequestHandler):
        server_version = "Docks"

        def log_message(self, *args):
            pass

        def _json(self, status: int, obj) -> None:
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.send_header("cache-control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            return secrets.compare_digest(self.headers.get("x-docks-token", ""), token)

        def _body(self) -> dict:
            length = int(self.headers.get("content-length", 0))
            if length > 40_000_000:
                return {}
            try:
                return json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return {}

        def do_GET(self):
            path, _, query = self.path.partition("?")
            if path == "/":
                body = page.encode()
                self.send_response(200)
                self.send_header("content-type", "text/html; charset=utf-8")
                self.send_header("content-length", str(len(body)))
                self.send_header("cache-control", "no-store")
                self.end_headers()
                return self.wfile.write(body)
            if not self._authorized():
                return self._json(401, {"error": "missing or wrong token; open the link printed in your terminal"})
            if path == "/api/state":
                return self._json(200, {**session.state(), "preview": preview})
            if path == "/api/files":
                return self._json(200, {"files": list_files(root)})
            if path == "/api/file":
                from urllib.parse import parse_qs
                rel = parse_qs(query).get("path", [""])[0]
                target = (root / rel).resolve()
                if not target.is_relative_to(root) or not target.is_file():
                    return self._json(404, {"error": "not found"})
                data = target.read_bytes()[:MAX_FILE_BYTES]
                try:
                    text = data.decode()
                except UnicodeDecodeError:
                    text = f"(binary file, {target.stat().st_size} bytes, {mimetypes.guess_type(target.name)[0] or 'unknown type'})"
                return self._json(200, {"path": rel, "text": text})
            if path == "/api/git":
                return self._json(200, github.status(root))
            if path == "/api/events":
                return self._events()
            self._json(404, {"error": "not found"})

        def _events(self):
            backlog, q = session.subscribe()
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("cache-control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(f"data: {json.dumps({'type': 'reset', 'state': session.state()})}\n\n".encode())
                for event in backlog:
                    self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                self.wfile.flush()
                while True:
                    try:
                        event = q.get(timeout=15)
                        self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
            except OSError:
                pass  # browser went away
            finally:
                session.unsubscribe(q)

        def do_POST(self):
            if not self._authorized():
                return self._json(401, {"error": "missing or wrong token"})
            path, body = self.path, self._body()
            if path == "/api/chat":
                text = str(body.get("message", "")).strip()
                images = body.get("images") or []
                if not text and not images:
                    return self._json(400, {"error": "empty message"})
                if not isinstance(images, list) or len(images) > MAX_IMAGES or not all(
                        isinstance(i, dict) and i.get("media_type") in IMAGE_TYPES
                        and isinstance(i.get("data"), str) and len(i["data"]) <= MAX_IMAGE_B64 for i in images):
                    return self._json(400, {"error": f"up to {MAX_IMAGES} PNG, JPEG, GIF or WebP images, 5 MB each"})
                images = [{"media_type": i["media_type"], "data": i["data"]} for i in images]
                if not session.start_turn(text or "Build what's shown in the image.", images):
                    return self._json(409, {"error": "Docks is still working; stop it or wait"})
                return self._json(202, {"ok": True})
            if path == "/api/github":
                action, number = body.get("action"), body.get("number")
                if action in ("fix", "review") and not (isinstance(number, int) and number > 0):
                    return self._json(400, {"error": "enter an issue or pull request number"})
                prompts = {"fix": lambda: github.fix_issue_prompt(number),
                           "review": lambda: github.review_pr_prompt(number), "pr": github.open_pr_prompt,
                           "deploy": github.deploy_prompt}
                if action not in prompts:
                    return self._json(400, {"error": "unknown action"})
                if not session.start_turn(prompts[action]()):
                    return self._json(409, {"error": "Docks is still working; stop it or wait"})
                return self._json(202, {"ok": True})
            if path == "/api/mcp/approve":
                if session.busy:
                    return self._json(409, {"error": "stop the current task first"})
                mgr = session.agent.mcp
                if not mgr or body.get("name") not in mgr.servers:
                    return self._json(404, {"error": "no such MCP server"})
                mgr.approve(body["name"])
                session.agent.refresh_tools()
                return self._json(200, {"mcp": mgr.summary()})
            if path == "/api/process/stop":
                session.agent.procs.stop(int(body.get("id", 0)))
                return self._json(200, {"processes": session.agent.procs.list()})
            if path == "/api/install-github":
                from ..action import install
                written = install(root)
                session.publish({"type": "notice", "text": f"Added {written.relative_to(root)}"})
                return self._json(200, {"path": str(written.relative_to(root))})
            if path == "/api/clone":
                if session.busy:
                    return self._json(409, {"error": "stop the current task first"})
                if any(p for p in root.iterdir() if p.name != ".docks"):
                    return self._json(409, {"error": "this project folder isn't empty; run `docks clone` instead"})
                try:
                    github.clone(str(body.get("repo", "")), root)
                except github.GitHubError as e:
                    return self._json(400, {"error": str(e)})
                session.publish({"type": "notice", "text": f"Cloned {github.parse_repo(body['repo'])}"})
                return self._json(200, github.status(root))
            if path == "/api/approve":
                answer = body.get("answer") if body.get("answer") in ("yes", "no", "always") else "no"
                return self._json(200, {"ok": session.answer(str(body.get("id")), answer)})
            if path == "/api/stop":
                session.stop()
                return self._json(200, {"ok": True})
            if path == "/api/clear":
                if session.busy:
                    return self._json(409, {"error": "stop the current task first"})
                session.agent.reset()
                with session.lock:
                    session.history.clear()
                session.publish({"type": "cleared"})
                return self._json(200, {"ok": True})
            if path == "/api/settings":
                a = session.agent
                if isinstance(body.get("auto_approve"), bool):
                    a.auto_approve = body["auto_approve"]
                if body.get("effort") in ("low", "medium", "high", "xhigh", "max"):
                    a.effort = body["effort"]
                if isinstance(body.get("model"), str) and body["model"].strip():
                    a.model = body["model"].strip()
                return self._json(200, session.state())
            self._json(404, {"error": "not found"})

    return Handler


class PreviewHandler(SimpleHTTPRequestHandler):
    """Static files of the project, under a secret path prefix. Dotfiles (.env, .git) are never served."""

    prefix = "/"

    def log_message(self, *args):
        pass

    def send_head(self):
        path = self.path.split("?")[0].split("#")[0]
        if not path.startswith(self.prefix) or any(p.startswith(".") for p in path.split("/") if p):
            self.send_error(404)
            return None
        self.path = "/" + self.path[len(self.prefix):]
        return super().send_head()

    def end_headers(self):
        self.send_header("cache-control", "no-store")
        super().end_headers()


def serve(agent: Agent, host: str = "127.0.0.1", port: int = 8788, open_browser: bool = True) -> None:
    session = Session(agent)
    token = secrets.token_urlsafe(24)
    shown_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    preview_prefix = f"/{secrets.token_urlsafe(12)}/"
    app = ThreadingHTTPServer((host, port), make_handler(session, token, {"port": port + 1, "prefix": preview_prefix}))
    handler = type("Preview", (PreviewHandler,), {"prefix": preview_prefix})
    preview = ThreadingHTTPServer((host, port + 1), functools.partial(handler, directory=str(agent.root)))
    for server in (app, preview):
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://{shown_host}:{port}/#token={token}"
    print(f"Docks is running in your browser: {url}")
    print(f"  project: {agent.root}")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("  warning: reachable from your network. Anyone with the link can run commands on this machine.")
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        session.stop()
    finally:
        app.shutdown()
        preview.shutdown()
