"""MCP (Model Context Protocol) client: give the agent the tools of any MCP server.

Servers are configured in the same format Claude Code and Claude Desktop use:
  ~/.docks/mcp.json   your servers, available in every project
  <project>/.mcp.json servers a project ships with (must be approved once, since they run commands)

  {"mcpServers": {
     "files":  {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "."]},
     "remote": {"type": "http", "url": "https://example.com/mcp", "headers": {"Authorization": "Bearer ${TOKEN}"}}
  }}
"""

import hashlib
import itertools
import json
import os
import queue
import re
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__

PROTOCOL_VERSION = "2025-06-18"
TIMEOUT = 60


class MCPError(Exception):
    pass


def user_config_path() -> Path:
    return Path(os.environ.get("DOCKS_HOME", Path.home() / ".docks")) / "mcp.json"


def project_config_path(root: Path) -> Path:
    return root / ".mcp.json"


def _trust_path() -> Path:
    return Path(os.environ.get("DOCKS_HOME", Path.home() / ".docks")) / "mcp-trust.json"


def _expand(value):
    """${VAR} -> environment value, recursively."""
    if isinstance(value, str):
        return re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


def read_config(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text()).get("mcpServers", {}) or {}
    except json.JSONDecodeError as e:
        raise MCPError(f"{path} is not valid JSON: {e}")


def write_server(path: Path, name: str, spec: dict | None) -> None:
    """Add (or with spec=None, remove) a server in a config file."""
    data = json.loads(path.read_text()) if path.is_file() else {}
    servers = data.setdefault("mcpServers", {})
    if spec is None:
        servers.pop(name, None)
    else:
        servers[name] = spec
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def _fingerprint(root: Path, name: str, spec: dict) -> str:
    return hashlib.sha256(json.dumps([str(root), name, spec], sort_keys=True).encode()).hexdigest()


def is_trusted(root: Path, name: str, spec: dict) -> bool:
    try:
        return _fingerprint(root, name, spec) in json.loads(_trust_path().read_text())
    except (OSError, json.JSONDecodeError):
        return False


def trust(root: Path, name: str, spec: dict) -> None:
    path = _trust_path()
    try:
        trusted = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        trusted = []
    trusted.append(_fingerprint(root, name, spec))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(set(trusted))))


# ------------------------------------------------------------- transports


class StdioClient:
    """JSON-RPC over a child process's stdin/stdout, one message per line."""

    def __init__(self, spec: dict, cwd: Path):
        spec = _expand(spec)
        try:
            self.proc = subprocess.Popen(
                [spec["command"], *spec.get("args", [])], cwd=cwd, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
                env={**os.environ, **spec.get("env", {})})
        except OSError as e:
            raise MCPError(f"could not start {spec['command']}: {e}")
        self.ids = itertools.count(1)
        self.waiting: dict[int, queue.Queue] = {}
        self.lock = threading.Lock()
        self.stderr_tail: list[str] = []
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._drain_stderr, daemon=True).start()

    def _send(self, msg: dict) -> None:
        with self.lock:
            try:
                self.proc.stdin.write(json.dumps(msg) + "\n")
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError):
                raise MCPError("server exited" + self._stderr_hint())

    def _read(self) -> None:
        for line in self.proc.stdout:
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue  # servers sometimes log to stdout; ignore non-JSON lines
            if "id" in msg and ("result" in msg or "error" in msg):
                q = self.waiting.get(msg["id"])
                if q:
                    q.put(msg)
            elif "id" in msg and "method" in msg:  # a request from the server
                reply = {"jsonrpc": "2.0", "id": msg["id"]}
                if msg["method"] == "ping":
                    reply["result"] = {}
                else:
                    reply["error"] = {"code": -32601, "message": "not supported by docks"}
                try:
                    self._send(reply)
                except MCPError:
                    return
        for q in list(self.waiting.values()):
            q.put(None)  # server closed: wake everyone up

    def _drain_stderr(self) -> None:
        for line in self.proc.stderr:
            self.stderr_tail = (self.stderr_tail + [line.rstrip()])[-20:]

    def _stderr_hint(self) -> str:
        return (": " + " | ".join(self.stderr_tail[-3:])) if self.stderr_tail else ""

    def request(self, method: str, params: dict | None = None, timeout: float = TIMEOUT) -> dict:
        msg_id = next(self.ids)
        q = self.waiting[msg_id] = queue.Queue()
        try:
            self._send({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}})
            try:
                reply = q.get(timeout=timeout)
            except queue.Empty:
                raise MCPError(f"{method} timed out after {timeout:.0f}s")
        finally:
            self.waiting.pop(msg_id, None)
        if reply is None:
            raise MCPError("server exited" + self._stderr_hint())
        if "error" in reply:
            raise MCPError(reply["error"].get("message", str(reply["error"])))
        return reply["result"]

    def notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()


class HttpClient:
    """Streamable HTTP transport: each JSON-RPC message is a POST; replies come back as JSON or SSE."""

    def __init__(self, spec: dict, cwd: Path):
        spec = _expand(spec)
        self.url = spec["url"]
        self.headers = spec.get("headers", {})
        self.session_id = None
        self.protocol = None
        self.ids = itertools.count(1)

    def _post(self, msg: dict, timeout: float):
        headers = {"content-type": "application/json", "accept": "application/json, text/event-stream",
                   **self.headers}
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        if self.protocol:
            headers["mcp-protocol-version"] = self.protocol
        req = urllib.request.Request(self.url, data=json.dumps(msg).encode(), headers=headers, method="POST")
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            raise MCPError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
        except urllib.error.URLError as e:
            raise MCPError(f"could not reach {self.url}: {e.reason}")

    def request(self, method: str, params: dict | None = None, timeout: float = TIMEOUT) -> dict:
        msg_id = next(self.ids)
        with self._post({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}}, timeout) as resp:
            self.session_id = resp.headers.get("mcp-session-id") or self.session_id
            if "text/event-stream" in resp.headers.get("content-type", ""):
                reply = self._from_sse(resp, msg_id)
            else:
                reply = json.loads(resp.read())
        if reply is None:
            raise MCPError(f"no reply to {method}")
        if "error" in reply:
            raise MCPError(reply["error"].get("message", str(reply["error"])))
        return reply["result"]

    @staticmethod
    def _from_sse(resp, msg_id):
        data = []
        for raw in resp:
            line = raw.decode(errors="replace").rstrip("\r\n")
            if line.startswith("data:"):
                data.append(line[5:].lstrip())
            elif not line and data:
                msg, data = json.loads("\n".join(data)), []
                if msg.get("id") == msg_id and ("result" in msg or "error" in msg):
                    return msg
        return None

    def notify(self, method: str, params: dict | None = None) -> None:
        self._post({"jsonrpc": "2.0", "method": method, "params": params or {}}, TIMEOUT).close()

    def close(self) -> None:
        pass


# --------------------------------------------------------------- servers


def _tool_name(server: str, tool: str) -> str:
    clean = lambda s: re.sub(r"[^a-zA-Z0-9_-]", "_", s)
    return f"mcp__{clean(server)}__{clean(tool)}"[:64]


class Server:
    def __init__(self, name: str, spec: dict, scope: str):
        self.name, self.spec, self.scope = name, spec, scope
        self.client = None
        self.tools: list[dict] = []
        self.status = "stopped"  # stopped | running | error | needs-approval
        self.error = ""

    def start(self, cwd: Path) -> None:
        try:
            kind = self.spec.get("type") or ("http" if "url" in self.spec else "stdio")
            self.client = (HttpClient if kind in ("http", "streamable-http") else StdioClient)(self.spec, cwd)
            init = self.client.request("initialize", {
                "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                "clientInfo": {"name": "docks", "version": __version__}}, timeout=30)
            if isinstance(self.client, HttpClient):
                self.client.protocol = init.get("protocolVersion", PROTOCOL_VERSION)
            self.client.notify("notifications/initialized")
            tools, cursor = [], None
            while True:
                page = self.client.request("tools/list", {"cursor": cursor} if cursor else {})
                tools += page.get("tools", [])
                cursor = page.get("nextCursor")
                if not cursor:
                    break
            self.tools = tools
            self.status, self.error = "running", ""
        except (MCPError, KeyError, OSError) as e:
            self.status, self.error = "error", str(e)
            self.close()

    def close(self) -> None:
        if self.client:
            self.client.close()
            self.client = None


class MCPManager:
    """Loads the configured servers, exposes their tools to the agent, and routes calls."""

    def __init__(self, root: Path, extra: dict | None = None):
        self.root = root
        self.servers: dict[str, Server] = {}
        self.routes: dict[str, tuple[Server, dict]] = {}
        for name, spec in (extra or {}).items():  # servers that installed plugins ship
            self.servers[name] = Server(name, spec, "plugin")
        for scope, path in (("user", user_config_path()), ("project", project_config_path(root))):
            for name, spec in read_config(path).items():
                self.servers[name] = Server(name, spec, scope)

    def start(self) -> None:
        threads = []
        for server in self.servers.values():
            if server.scope == "project" and not is_trusted(self.root, server.name, server.spec):
                server.status = "needs-approval"
                continue
            t = threading.Thread(target=server.start, args=(self.root,), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join(timeout=45)
        self._index()

    def approve(self, name: str) -> Server:
        server = self.servers[name]
        trust(self.root, name, server.spec)
        server.start(self.root)
        self._index()
        return server

    def _index(self) -> None:
        self.routes = {}
        for server in self.servers.values():
            if server.status == "running":
                for tool in server.tools:
                    self.routes[_tool_name(server.name, tool["name"])] = (server, tool)

    def pending_approval(self) -> list[Server]:
        return [s for s in self.servers.values() if s.status == "needs-approval"]

    def tool_definitions(self) -> list[dict]:
        defs = []
        for name, (server, tool) in self.routes.items():
            schema = tool.get("inputSchema") or {"type": "object", "properties": {}}
            schema = {**schema, "type": "object"}
            defs.append({"name": name, "description": f"[MCP server '{server.name}'] {tool.get('description', '')}"[:1024],
                         "input_schema": schema})
        return defs

    def handles(self, name: str) -> bool:
        return name in self.routes

    def is_mutating(self, name: str) -> bool:
        _, tool = self.routes[name]
        return not (tool.get("annotations") or {}).get("readOnlyHint", False)

    def call(self, name: str, args: dict) -> tuple[str, bool]:
        server, tool = self.routes[name]
        if not server.client:
            raise MCPError(f"MCP server '{server.name}' is not running")
        result = server.client.request("tools/call", {"name": tool["name"], "arguments": args}, timeout=300)
        parts = []
        for item in result.get("content", []):
            if item.get("type") == "text":
                parts.append(item["text"])
            elif item.get("type") == "resource":
                parts.append(item.get("resource", {}).get("text", f"[resource {item.get('resource', {}).get('uri')}]"))
            else:
                parts.append(f"[{item.get('type')} content]")
        if not parts and "structuredContent" in result:
            parts.append(json.dumps(result["structuredContent"], indent=2))
        return "\n".join(parts) or "(no output)", bool(result.get("isError"))

    def summary(self) -> list[dict]:
        return [{"name": s.name, "scope": s.scope, "status": s.status, "error": s.error,
                 "tools": [t["name"] for t in s.tools],
                 "command": s.spec.get("url") or " ".join([s.spec.get("command", ""), *s.spec.get("args", [])])}
                for s in self.servers.values()]

    def close(self) -> None:
        for server in self.servers.values():
            server.close()
