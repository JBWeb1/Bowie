"""`bowers web`: run the agent from a browser.

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

from .. import github, models
from ..agent import Agent
from ..checkpoints import CheckpointError
from ..sandbox import SandboxUnavailable, engine as sandbox_engine, unavailable_reason as sandbox_reason
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
        agent.on_background_done = self._background_done
        self.github_login = {}  # a sign-in through GitHub in progress
        from ..pr_watch import Watcher
        self.pr_watcher = Watcher(lambda u: self.publish({"type": "pr_update", "text": "; ".join(u["changes"]),
                                                           "url": u["url"], "title": u["title"]}))
        self.pr_watcher.start()

    def start_github_login(self) -> dict:
        """Begin signing in on github.com; a thread waits for the person to approve and reports back."""
        flow = github.start_device_login()
        self.github_login = {"user_code": flow["user_code"], "verification_uri": flow["verification_uri"], "status": "waiting"}

        def wait():
            import time
            deadline = time.monotonic() + flow["expires_in"]
            while time.monotonic() < deadline:
                time.sleep(flow["interval"])
                try:
                    info = github.poll_device_login(flow)
                except github.GitHubError as e:
                    self.github_login = {"status": "error", "error": str(e)}
                    self.publish({"type": "github_login", **self.github_login})
                    return
                if info:
                    self.github_login = {"status": "connected", "login": info["login"]}
                    self.publish({"type": "github_login", **self.github_login})
                    return
            self.github_login = {"status": "error", "error": "the sign-in code expired; start again"}
            self.publish({"type": "github_login", **self.github_login})
        threading.Thread(target=wait, daemon=True).start()
        return self.github_login

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

    def start_turn(self, text: str, images: list | None = None, auto: bool = False) -> bool:
        with self.lock:
            if self.busy:
                return False
            self.busy = True
        images = images or []
        self.publish({"type": "user", "text": text, "auto": auto,
                      "images": [f"data:{i['media_type']};base64,{i['data']}" for i in images]})
        content = [{"type": "image", "source": {"type": "base64", **i}} for i in images]
        content = content + [{"type": "text", "text": text}] if content else text
        threading.Thread(target=self._run, args=(content,), daemon=True).start()
        return True

    def _run(self, content) -> None:
        try:
            self.agent.run(content)
        except Exception as e:  # never let a task die silently in the browser
            self.publish({"type": "error", "text": f"Something went wrong: {type(e).__name__}: {e}"})
        finally:
            with self.lock:
                self.busy = False
            self.publish({"type": "idle"})

    def _background_done(self) -> None:
        # A background helper finished while Bowers was idle: continue the task with its report.
        if self.agent.has_background_reports():
            self.start_turn("A background helper finished; its report is attached. Continue the task with it.", auto=True)

    def resume(self, session_id: str) -> dict:
        """Load a saved conversation and show it in every open browser."""
        data = self.agent.resume(session_id)
        with self.lock:
            self.history = history_from_messages(self.agent.messages, self.agent.turns)
            for q in self.subscribers:
                q.put({"type": "rewound"})
        return data

    def new_chat(self) -> None:
        self.agent.reset()
        with self.lock:
            self.history.clear()
        self.publish({"type": "cleared"})

    def rewind(self, turn: int):
        """Restore files and conversation to before the user's `turn`-th message, and replay the log to browsers."""
        text, restored = self.agent.rewind(turn)
        with self.lock:
            starts = [i for i, e in enumerate(self.history) if e["type"] == "user"]
            if turn < len(starts):
                del self.history[starts[turn]:]
            for q in self.subscribers:
                q.put({"type": "rewound"})
        return text, restored

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
            self.answer(approval_id, None)

    def state(self) -> dict:
        a = self.agent
        return {"root": str(a.root), "model": a.profile or a.model, "model_label": a.model_label, "effort": a.effort, "auto_approve": a.auto_approve,
                "mode": a.active_mode, "busy": self.busy, "usage": a.usage, "processes": a.procs.list(),
                "plan": a.plan, "turns": [bool(t["checkpoint"]) for t in a.turns],
                "mcp": a.mcp.summary() if a.mcp else [], "extensions": a.ext.summary(),
                "session": {"id": a.session_id, "name": a.session_name}, "bookmarks": a.bookmarks,
                "models": [{"id": c["id"], "label": c["label"], "note": c["note"], "group": c["group"]} for c in models.choices()],
                "output_style": a.output_style,
                "output_styles": [{"name": "default", "description": "Bowers as usual"}] +
                                 [{"name": k, "description": v.description} for k, v in a.ext.output_styles.items()],
                "sandbox": {"on": a.sandbox is not None, "available": sandbox_engine() is not None,
                            "reason": "" if sandbox_engine() else sandbox_reason()},
                "permissions": a.ext.permissions.summary(), "context_used": a.context_used}


def history_from_messages(messages: list, turns: list) -> list[dict]:
    """Rebuild the browser's event log from a saved conversation."""
    from ..agent import _block
    events, starts = [], {t["index"] for t in turns}
    for i, msg in enumerate(messages):
        content = msg["content"]
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content
        if msg["role"] == "user":
            if i in starts:
                text = next((_block(b, "text") for b in blocks if _block(b, "type") == "text"), "")
                images = [f"data:{_block(b, 'source')['media_type']};base64,{_block(b, 'source')['data']}"
                          for b in blocks if _block(b, "type") == "image" and _block(b, "source", {}).get("type") == "base64"]
                events.append({"type": "user", "text": text, "images": images})
            for b in blocks:
                if _block(b, "type") == "tool_result":
                    raw = _block(b, "content")
                    out = raw if isinstance(raw, str) else "".join(_block(x, "text", "") for x in raw or [])
                    events.append({"type": "tool_output", "text": _clip(out, 20_000), "error": bool(_block(b, "is_error")),
                                   "id": _block(b, "tool_use_id")})
                    for x in ([] if isinstance(raw, str) else raw or []):  # browser screenshots
                        if _block(x, "type") == "image" and _block(x, "source", {}).get("type") == "base64":
                            events.append({"type": "tool_image", "data": _block(x, "source")["data"],
                                           "media": _block(x, "source")["media_type"], "id": _block(b, "tool_use_id")})
        else:
            for b in blocks:
                kind = _block(b, "type")
                if kind == "text" and _block(b, "text"):
                    events.append({"type": "text", "id": uuid.uuid4().hex[:8], "text": _block(b, "text")})
                elif kind == "tool_use":
                    args = _block(b, "input") or {}
                    if _block(b, "name") == "update_plan":
                        events.append({"type": "plan", "items": args.get("items", [])})
                        continue
                    events.append({"type": "tool_call", "name": _block(b, "name"), "id": _block(b, "id"),
                                   "summary": _clip(_summarize_args(_block(b, "name"), args), 300),
                                   "args": {k: _clip(v) for k, v in args.items()}, "helper": None})
    events.append({"type": "idle"})
    return events


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
        self.local = threading.local()  # which tool call this thread is on (helpers run in parallel)

    def stream(self):
        return WebStream(self.session)

    def tool_call(self, name: str, args: dict, id=None, helper=None) -> None:
        self.local.id = id
        self.session.publish({"type": "tool_call", "name": name, "summary": _clip(_summarize_args(name, args), 300),
                              "args": {k: _clip(v) for k, v in args.items()}, "id": id, "helper": helper})

    def tool_output(self, output: str, is_error: bool = False, id=None, helper=None) -> None:
        self.session.publish({"type": "tool_output", "text": _clip(output, 20_000), "error": is_error, "id": id})

    def tool_image(self, data: str, media_type: str, id=None) -> None:
        self.session.publish({"type": "tool_image", "data": data, "media": media_type, "id": id})

    def notice(self, msg: str) -> None:
        self.session.publish({"type": "notice", "text": msg})

    def plan(self, items: list) -> None:
        self.session.publish({"type": "plan", "items": items})

    def warn(self, msg: str) -> None:
        self.session.publish({"type": "warn", "text": msg})

    def error(self, msg: str) -> None:
        self.session.publish({"type": "error", "text": msg})

    def _wait(self, event: dict, default):
        """Publish a request to the browser and wait for the user's answer (or a stop)."""
        request_id = uuid.uuid4().hex[:12]
        entry = {"event": threading.Event(), "answer": default}
        self.session.approvals[request_id] = entry
        self.session.publish({**event, "id": request_id, "call": getattr(self.local, "id", None)})
        while not entry["event"].wait(0.5):
            if self.session.agent.cancelled.is_set():
                break
        self.session.approvals.pop(request_id, None)
        return request_id, entry["answer"]

    def confirm(self, name: str, args: dict) -> str:
        request_id, answer = self._wait({"type": "approval", "name": name,
                                         "args": {k: _clip(v, 20_000) for k, v in args.items()}}, "no")
        answer = answer if answer in ("yes", "no", "always") else "no"
        self.session.publish({"type": "approval_done", "id": request_id, "answer": answer,
                              "call": getattr(self.local, "id", None)})
        return answer

    def ask(self, questions: list):
        request_id, answer = self._wait({"type": "question", "questions": questions}, None)
        ok = isinstance(answer, list) and len(answer) == len(questions)
        self.session.publish({"type": "question_done", "id": request_id, "answers": answer if ok else None})
        return [str(a) for a in answer] if ok else None

    def review_plan(self, plan_text: str):
        request_id, answer = self._wait({"type": "plan_review", "plan": plan_text}, None)
        decision = answer.get("decision") if isinstance(answer, dict) else "reject"
        decision = decision if decision in ("approve", "approve_auto", "reject") else "reject"
        feedback = str(answer.get("feedback", "")) if isinstance(answer, dict) else ""
        self.session.publish({"type": "plan_review_done", "id": request_id, "decision": decision})
        return decision, feedback

    def auto_approved(self, call_id, reason: str) -> None:
        self.session.publish({"type": "auto_approved", "call": call_id, "reason": reason})

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
        server_version = "Bowers"

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
            if path == "/api/commands":
                return self._json(200, session.agent.ext.summary())
            if path == "/api/sessions":
                from .. import sessions
                return self._json(200, {"sessions": sessions.list_sessions(root),
                                         "current": session.agent.session_id})
            if path == "/api/git":
                return self._json(200, github.status(root))
            if path == "/api/images":
                from .. import images
                return self._json(200, {"available": images.available(), "images": images.gallery(root),
                                         "models": {"fast": images.FAST, "detailed": images.DETAILED},
                                         "sizes": list(images.SIZES), "qualities": list(images.QUALITIES)})
            if path == "/api/github/account":
                return self._json(200, {"account": github.whoami(), "device_login": bool(github.device_client_id()),
                                         "login": session.github_login, "web": github.WEB})
            if path.startswith("/api/github/") or path == "/api/context-repos":
                from urllib.parse import parse_qs
                from .. import context_repos, pr_watch
                q = {k: v[0] for k, v in parse_qs(query).items()}
                try:
                    if path == "/api/github/repos":
                        return self._json(200, {"repos": github.my_repos(q.get("q", ""))})
                    if path == "/api/github/branches":
                        repo = github.repo_of(root)
                        current = github.git(root, "rev-parse", "--abbrev-ref", "HEAD", check=False)
                        return self._json(200, {**github.branches(repo), "current": current, "repo": repo})
                    if path == "/api/github/prs":
                        try:
                            here = github.pull_requests(github.repo_of(root))
                        except github.GitHubError:
                            here = []
                        return self._json(200, {"here": here, "mine": github.my_pull_requests(),
                                                 "watched": [{"repo": w["repo"], "number": w["number"]} for w in pr_watch.watched()]})
                    if path == "/api/context-repos":
                        return self._json(200, {"repos": context_repos.items(root)})
                except github.GitHubError as e:
                    return self._json(400, {"error": str(e)})
            if path == "/api/context":
                return self._json(200, session.agent.context_report())
            if path == "/api/doctor":
                from .. import doctor
                a = session.agent
                return self._json(200, {"results": doctor.check(a.root, a.ext, a.mcp, a)})
            if path == "/api/memory":
                from .. import instructions
                files = [*instructions.user_files(), instructions.project_file(root), instructions.local_file(root),
                         *sorted(session.agent._folders_read)]
                return self._json(200, {"files": [{"path": str(f), "text": f.read_text(errors="replace")[:20_000]}
                                                  for f in files if f]})
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
                    return self._json(409, {"error": "Bowers is still working; stop it or wait"})
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
                    return self._json(409, {"error": "Bowers is still working; stop it or wait"})
                return self._json(202, {"ok": True})
            if path == "/api/rewind":
                if session.busy:
                    return self._json(409, {"error": "stop the current task first"})
                turn = body.get("turn")
                if not isinstance(turn, int):
                    return self._json(400, {"error": "which message?"})
                try:
                    text, restored = session.rewind(turn)
                except CheckpointError as e:
                    return self._json(409, {"error": str(e)})
                return self._json(200, {"text": text, "restored": restored})
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
                    return self._json(409, {"error": "this project folder isn't empty; run `bowers clone` instead"})
                try:
                    github.clone(str(body.get("repo", "")), root)
                except github.GitHubError as e:
                    return self._json(400, {"error": str(e)})
                session.publish({"type": "notice", "text": f"Cloned {github.parse_repo(body['repo'])}"})
                return self._json(200, github.status(root))
            if path == "/api/respond":  # answers to questions and plan reviews
                entry = session.approvals.get(str(body.get("id")))
                if not entry:
                    return self._json(404, {"error": "that question was already answered"})
                return self._json(200, {"ok": session.answer(str(body.get("id")), body.get("answer"))})
            if path == "/api/sessions/resume":
                if session.busy:
                    return self._json(409, {"error": "stop the current task first"})
                try:
                    data = session.resume(str(body.get("id", "")))
                except (FileNotFoundError, KeyError, ValueError) as e:
                    return self._json(404, {"error": str(e)})
                return self._json(200, {"ok": True, "name": data.get("name") or data.get("title")})
            if path == "/api/sessions/rename":
                session.agent.rename(str(body.get("name", ""))[:100])
                return self._json(200, {"ok": True})
            if path == "/api/bookmark":
                text = str(body.get("text", "")).strip()
                if not text:
                    return self._json(400, {"error": "nothing to bookmark"})
                session.agent.bookmark(text[:50_000])
                return self._json(200, {"bookmarks": session.agent.bookmarks})
            if path == "/api/hooks/approve":
                session.agent.ext.approve_hooks(str(body.get("file", "")))
                return self._json(200, session.agent.ext.summary())
            if path == "/api/approve":
                answer = body.get("answer") if body.get("answer") in ("yes", "no", "always") else "no"
                return self._json(200, {"ok": session.answer(str(body.get("id")), answer)})
            if path == "/api/stop":
                session.stop()
                return self._json(200, {"ok": True})
            if path == "/api/clear":
                if session.busy:
                    return self._json(409, {"error": "stop the current task first"})
                session.new_chat()
                return self._json(200, {"ok": True})
            if path in ("/api/images/generate", "/api/images/delete"):
                from .. import images
                if path == "/api/images/delete":
                    images.forget(root, str(body.get("path", "")), bool(body.get("delete_file")))
                    return self._json(200, {"images": images.gallery(root)})
                try:
                    made = images.generate(root, str(body.get("prompt", "")), str(body.get("path", "")),
                                           str(body.get("size", "auto")), str(body.get("quality", "auto")),
                                           str(body.get("background", "auto")), int(body.get("n", 1) or 1),
                                           [str(x) for x in body.get("edit") or []], bool(body.get("detailed")))
                except images.ImageError as e:
                    return self._json(400, {"error": str(e)})
                except (TypeError, ValueError):
                    return self._json(400, {"error": "check the image options"})
                return self._json(200, {"made": made, "images": images.gallery(root)})
            if path.startswith("/api/github/") or path == "/api/context-repos":
                from .. import context_repos, pr_watch
                try:
                    if path == "/api/github/login":
                        if body.get("token"):
                            info = github.save_token(str(body["token"]))
                            return self._json(200, {"account": info})
                        return self._json(200, {"login": session.start_github_login()})
                    if path == "/api/github/logout":
                        github.logout()
                        return self._json(200, {"account": github.whoami()})
                    if path == "/api/github/switch":
                        if session.busy:
                            return self._json(409, {"error": "Bowers is working; wait for it to finish first"})
                        name = github.switch_branch(root, str(body.get("branch", "")))
                        session.publish({"type": "notice", "text": f"Switched to branch {name}"})
                        return self._json(200, {"branch": name})
                    if path == "/api/github/watch":
                        repo, number = str(body.get("repo", "")), int(body.get("number", 0))
                        pr_watch.watch(repo, number, bool(body.get("on", True)))
                        return self._json(200, {"watched": [{"repo": w["repo"], "number": w["number"]} for w in pr_watch.watched()]})
                    if path == "/api/context-repos":
                        action = body.get("action")
                        if action == "add":
                            context_repos.add(root, str(body.get("repo", "")), str(body.get("branch", "")))
                        elif action == "remove":
                            context_repos.remove(root, str(body.get("repo", "")))
                        elif action == "sync":
                            context_repos.sync(root, force=True)
                        a = session.agent
                        a.ext.permissions.add("deny", context_repos.deny_rules(root), root)
                        a.reload_instructions()
                        return self._json(200, {"repos": context_repos.items(root)})
                except (github.GitHubError, ValueError) as e:
                    return self._json(400, {"error": str(e)})
                return self._json(404, {"error": "not found"})
            if path == "/api/memory":
                from .. import instructions
                text = str(body.get("text", "")).strip()
                if not text.lstrip("#").strip():
                    return self._json(400, {"error": "nothing to remember"})
                scope = body.get("scope") if body.get("scope") in ("project", "local", "user") else "project"
                saved = instructions.add_note(root, text, scope)
                session.agent.reload_instructions()
                return self._json(200, {"path": str(saved), "name": saved.name})
            if path == "/api/compact":
                if session.busy:
                    return self._json(409, {"error": "Bowers is working; wait for it to finish first"})
                try:
                    session.agent.compact(str(body.get("focus", "")))
                except ValueError as e:
                    return self._json(400, {"error": str(e)})
                except Exception as e:  # API trouble
                    return self._json(502, {"error": f"couldn't summarize: {e}"})
                session.publish({"type": "notice", "text": "Summarized the conversation to free up room; "
                                                           "earlier messages can no longer be undone."})
                return self._json(200, session.state())
            if path == "/api/permissions":
                from ..permissions import parse
                kind, rule = body.get("kind"), str(body.get("rule", "")).strip()
                if kind not in ("allow", "ask", "deny") or not parse(rule, root):
                    return self._json(400, {"error": "a rule looks like Bash(npm test:*), Edit(src/**) or Read(./.env)"})
                session.agent.ext.save_rule(kind, rule)
                return self._json(200, session.state())
            if path == "/api/settings":
                a = session.agent
                if isinstance(body.get("output_style"), str):
                    try:
                        a.set_output_style(body["output_style"])
                    except ValueError as e:
                        return self._json(400, {"error": str(e)})
                if isinstance(body.get("sandbox"), bool):
                    try:
                        a.set_sandbox(body["sandbox"])
                    except SandboxUnavailable as e:
                        return self._json(400, {"error": str(e)})
                if isinstance(body.get("auto_approve"), bool):
                    a.set_mode("yolo" if body["auto_approve"] else "ask")
                if body.get("mode") in ("ask", "auto", "plan", "yolo"):
                    a.set_mode(body["mode"])
                if body.get("effort") in ("low", "medium", "high", "xhigh", "max"):
                    a.effort = body["effort"]
                if isinstance(body.get("model"), str) and body["model"].strip():
                    try:
                        a.set_model(body["model"])
                    except ValueError as e:
                        return self._json(400, {"error": str(e)})
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
    print(f"Bowers is running in your browser: {url}")
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
