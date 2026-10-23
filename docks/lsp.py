"""Code intelligence through language servers (the same ones editors use): go to definition, find references,
type info, an outline of a file, and the errors in it.

Bowers starts a server the first time a file of its language is touched. Built in: Python (pyright, basedpyright
or pylsp), TypeScript/JavaScript (typescript-language-server), Go (gopls), Rust (rust-analyzer), C/C++ (clangd).
Add others in a plugin's .lsp.json or settings.json, in Claude Code's format:

    {"lspServers": {"elixir": {"command": "elixir-ls", "args": [], "extensionToLanguage": {".ex": "elixir"}}}}

After Claude edits a file, the errors the server reports for it are added to the edit's result.
"""

import atexit
import json
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

BUILTIN_SERVERS = [
    ("python", ["pyright-langserver", "--stdio"], {".py": "python", ".pyi": "python"}),
    ("python", ["basedpyright-langserver", "--stdio"], {".py": "python", ".pyi": "python"}),
    ("python", ["pylsp"], {".py": "python"}),
    ("typescript", ["typescript-language-server", "--stdio"],
     {".ts": "typescript", ".tsx": "typescriptreact", ".js": "javascript", ".jsx": "javascriptreact",
      ".mjs": "javascript", ".cjs": "javascript"}),
    ("go", ["gopls"], {".go": "go"}),
    ("rust", ["rust-analyzer"], {".rs": "rust"}),
    ("c", ["clangd"], {".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp", ".cxx": "cpp"}),
]
SEVERITY = {1: "error", 2: "warning", 3: "info", 4: "hint"}
SYMBOL_KINDS = {5: "class", 6: "method", 9: "constructor", 10: "enum", 11: "interface", 12: "function",
                13: "variable", 14: "constant", 23: "struct", 26: "type"}
ACTIONS = ["definition", "references", "hover", "symbols", "diagnostics", "search"]

SCHEMA = {
    "description": (
        "Code intelligence from the project's language server (the one editors use). Faster and more accurate "
        "than grep for code: definition (where a symbol is defined), references (every place it's used, before "
        "renaming or changing it), hover (its type and docs), symbols (outline of a file), diagnostics (type and "
        "syntax errors in a file), search (find a class or function by name across the project). Give path and "
        "symbol, plus line (1-based) when the name appears more than once."),
    "properties": {
        "action": {"type": "string", "enum": ACTIONS},
        "path": {"type": "string"},
        "symbol": {"type": "string"},
        "line": {"type": "integer"},
        "query": {"type": "string", "description": "for search"},
    },
    "required": ["action"],
}


class LSPError(Exception):
    pass


@dataclass
class ServerSpec:
    name: str
    command: list
    extensions: dict  # ".py" -> "python"
    env: dict = field(default_factory=dict)


def _uri(path: Path) -> str:
    return path.resolve().as_uri()


def _path(uri: str) -> Path:
    return Path(unquote(urlparse(uri).path))


class Client:
    """One running language server, spoken to over stdin/stdout with JSON-RPC."""

    def __init__(self, spec: ServerSpec, root: Path):
        self.spec, self.root = spec, root
        self.proc = subprocess.Popen(spec.command, cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, env={**os.environ, **spec.env})
        self._ids = iter(range(1, 1 << 30))
        self._pending: dict[int, dict] = {}
        self._lock = threading.Lock()
        self.diagnostics: dict[str, list] = {}
        self._diag_event = threading.Condition()
        self.versions: dict[str, int] = {}
        self.started = time.monotonic()
        threading.Thread(target=self._read, daemon=True).start()
        self.request("initialize", {
            "processId": os.getpid(), "rootUri": _uri(root), "rootPath": str(root),
            "workspaceFolders": [{"uri": _uri(root), "name": root.name}],
            "capabilities": {
                "textDocument": {
                    "synchronization": {"didSave": True},
                    "publishDiagnostics": {"relatedInformation": False},
                    "definition": {}, "references": {}, "hover": {"contentFormat": ["plaintext", "markdown"]},
                    "documentSymbol": {"hierarchicalDocumentSymbolSupport": True},
                },
                "workspace": {"symbol": {}, "configuration": True, "workspaceFolders": True},
            },
        }, timeout=60)
        self.notify("initialized", {})

    # -- wire

    def _send(self, message: dict) -> None:
        body = json.dumps(message).encode()
        with self._lock:
            self.proc.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode() + body)
            self.proc.stdin.flush()

    def _read(self) -> None:
        out = self.proc.stdout
        while True:
            length = None
            while True:
                line = out.readline()
                if not line:
                    return self._fail_all()
                line = line.strip()
                if not line:
                    break
                if line.lower().startswith(b"content-length:"):
                    length = int(line.split(b":")[1])
            if length is None:
                continue
            try:
                message = json.loads(out.read(length))
            except json.JSONDecodeError:
                continue
            self._handle(message)

    def _fail_all(self):
        for slot in list(self._pending.values()):
            slot["error"] = {"message": "the language server stopped"}
            slot["done"].set()

    def _handle(self, message: dict) -> None:
        if "id" in message and "method" in message:  # the server asks us something
            method = message["method"]
            if method == "workspace/configuration":
                result = [None for _ in message.get("params", {}).get("items", [])]
            elif method == "workspace/workspaceFolders":
                result = [{"uri": _uri(self.root), "name": self.root.name}]
            else:
                result = None
            self._send({"jsonrpc": "2.0", "id": message["id"], "result": result})
        elif "id" in message:
            slot = self._pending.get(message["id"])
            if slot:
                slot["result"], slot["error"] = message.get("result"), message.get("error")
                slot["done"].set()
        elif message.get("method") == "textDocument/publishDiagnostics":
            params = message["params"]
            with self._diag_event:
                self.diagnostics[params["uri"]] = params.get("diagnostics", [])
                self._diag_event.notify_all()

    def request(self, method: str, params: dict, timeout: float = 20):
        rid = next(self._ids)
        slot = {"done": threading.Event(), "result": None, "error": None}
        self._pending[rid] = slot
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        if not slot["done"].wait(timeout):
            self._pending.pop(rid, None)
            raise LSPError(f"{self.spec.name} language server didn't answer {method} in {timeout:.0f}s")
        self._pending.pop(rid, None)
        if slot["error"]:
            raise LSPError(f"{self.spec.name}: {slot['error'].get('message', slot['error'])}")
        return slot["result"]

    def notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    # -- documents

    def sync(self, path: Path) -> str:
        """Tell the server the file's current text. Returns its URI."""
        uri = _uri(path)
        text = path.read_text(errors="replace")
        language = self.spec.extensions.get(path.suffix, self.spec.name)
        with self._diag_event:
            self.diagnostics.pop(uri, None)
        if uri not in self.versions:
            self.versions[uri] = 1
            self.notify("textDocument/didOpen", {"textDocument": {"uri": uri, "languageId": language,
                                                                  "version": 1, "text": text}})
        else:
            self.versions[uri] += 1
            self.notify("textDocument/didChange", {"textDocument": {"uri": uri, "version": self.versions[uri]},
                                                   "contentChanges": [{"text": text}]})
            self.notify("textDocument/didSave", {"textDocument": {"uri": uri}})
        return uri

    def wait_diagnostics(self, uri: str, timeout: float) -> list | None:
        end = time.monotonic() + timeout
        with self._diag_event:
            while uri not in self.diagnostics:
                left = end - time.monotonic()
                if left <= 0:
                    return None
                self._diag_event.wait(left)
            return self.diagnostics[uri]

    def close(self) -> None:
        try:
            self.request("shutdown", None, timeout=3)
            self.notify("exit", None)
        except Exception:
            pass
        try:
            self.proc.terminate()
        except OSError:
            pass


class LSPManager:
    def __init__(self, root: Path, extra: dict | None = None):
        self.root = root.resolve()
        self.specs = self._specs(extra or {})
        self.clients: dict[str, Client] = {}
        self.failed: dict[str, str] = {}
        self._lock = threading.Lock()
        atexit.register(self.shutdown)

    @staticmethod
    def _specs(extra: dict) -> list[ServerSpec]:
        specs = []
        for name, spec in extra.items():  # configured ones come first
            if not isinstance(spec, dict) or not spec.get("command"):
                continue
            command = [spec["command"], *spec.get("args", [])]
            if shutil.which(command[0]) or os.path.exists(command[0]):
                specs.append(ServerSpec(name, command, spec.get("extensionToLanguage") or {}, spec.get("env") or {}))
        seen = {ext for s in specs for ext in s.extensions}
        for name, command, exts in BUILTIN_SERVERS:
            if shutil.which(command[0]) and not set(exts) <= seen:
                specs.append(ServerSpec(name, command, {e: l for e, l in exts.items() if e not in seen}))
                seen |= set(exts)
        return specs

    def available(self) -> bool:
        return bool(self.specs)

    def spec_for(self, path: Path) -> ServerSpec | None:
        return next((s for s in self.specs if path.suffix in s.extensions), None)

    def client_for(self, path: Path) -> Client:
        spec = self.spec_for(path)
        if spec is None:
            known = ", ".join(sorted({e for s in self.specs for e in s.extensions})) or "none"
            raise LSPError(f"no language server for {path.suffix or 'this file'} files (have: {known}); use grep instead")
        key = " ".join(spec.command)
        with self._lock:
            if key in self.failed:
                raise LSPError(self.failed[key])
            if key not in self.clients:
                try:
                    self.clients[key] = Client(spec, self.root)
                except (OSError, LSPError) as e:
                    self.failed[key] = f"couldn't start {spec.command[0]}: {e}"
                    raise LSPError(self.failed[key])
            return self.clients[key]

    def _file(self, path: str) -> Path:
        p = Path(path)
        p = (p if p.is_absolute() else self.root / p).resolve()
        if not p.is_file():
            raise LSPError(f"no such file: {path}")
        return p

    def _rel(self, p: Path) -> str:
        try:
            return str(p.relative_to(self.root))
        except ValueError:
            return str(p)

    def _position(self, path: Path, symbol: str | None, line: int | None) -> dict:
        lines = path.read_text(errors="replace").splitlines()
        if not symbol:
            if not line:
                raise LSPError("give symbol (and line if it appears more than once)")
            return {"line": max(line - 1, 0), "character": 0}
        word = re.compile(rf"(?<![\w$]){re.escape(symbol)}(?![\w$])")
        order = range(len(lines))
        if line:  # look on that line first, then nearby
            near = sorted(range(max(0, line - 6), min(len(lines), line + 5)), key=lambda i: abs(i - (line - 1)))
            order = near + [i for i in order if i not in near]
        for i in order:
            m = word.search(lines[i])
            if m:
                return {"line": i, "character": m.start()}
        raise LSPError(f"{symbol!r} isn't in {self._rel(path)}" + (f" near line {line}" if line else ""))

    def _where(self, location: dict) -> str:
        uri = location.get("uri") or location.get("targetUri")
        rng = location.get("range") or location.get("targetSelectionRange") or {}
        p = _path(uri)
        n = rng.get("start", {}).get("line", 0)
        try:
            text = p.read_text(errors="replace").splitlines()[n].strip()
        except (OSError, IndexError):
            text = ""
        return f"{self._rel(p)}:{n + 1}: {text[:160]}"

    def errors_after_edit(self, path: str, timeout: float = 8) -> str:
        """Errors in a file Claude just changed, or "" (no server, slow server, or no errors)."""
        try:
            p = self._file(path)
            if self.spec_for(p) is None:
                return ""
            client = self.client_for(p)
            uri = client.sync(p)
            diags = client.wait_diagnostics(uri, timeout)
        except (LSPError, OSError):
            return ""
        errors = [d for d in diags or [] if d.get("severity", 1) == 1]
        if not errors:
            return ""
        lines = [f"line {d['range']['start']['line'] + 1}: {d.get('message', '').splitlines()[0]}" for d in errors[:20]]
        more = f"\n…and {len(errors) - 20} more" if len(errors) > 20 else ""
        return f"{client.spec.command[0]} reports {len(errors)} error(s) in this file now:\n" + "\n".join(lines) + more

    def run(self, args: dict) -> str:
        action = args["action"]
        if action == "search":
            if not args.get("query"):
                raise LSPError("search needs query")
            client = self._any_client(args.get("path"))
            found = client.request("workspace/symbol", {"query": args["query"]}) or []
            while not found and time.monotonic() - client.started < 20:  # still reading the project
                time.sleep(1)
                found = client.request("workspace/symbol", {"query": args["query"]}) or []
            out = [f"{SYMBOL_KINDS.get(s.get('kind'), 'symbol')} {s['name']}  {self._where(s['location'])}"
                   for s in found[:50] if "location" in s and "uri" in s["location"]]
            return "\n".join(out) or f"no symbols match {args['query']!r}"
        if not args.get("path"):
            raise LSPError(f"{action} needs path")
        p = self._file(args["path"])
        client = self.client_for(p)
        uri = client.sync(p)
        if action == "diagnostics":
            diags = client.wait_diagnostics(uri, 30)
            if diags is None:
                return "the language server didn't report on this file in time"
            if not diags:
                return f"no problems in {self._rel(p)}"
            return "\n".join(f"line {d['range']['start']['line'] + 1} [{SEVERITY.get(d.get('severity', 1))}]: "
                             f"{d.get('message', '')}" for d in diags[:60])
        if action == "symbols":
            found = client.request("textDocument/documentSymbol", {"textDocument": {"uri": uri}}) or []
            out = []

            def walk(items, depth):
                for s in items:
                    rng = s.get("selectionRange") or s.get("range") or s.get("location", {}).get("range", {})
                    out.append(f"{'  ' * depth}{SYMBOL_KINDS.get(s.get('kind'), 'symbol')} {s['name']}  "
                               f"line {rng.get('start', {}).get('line', 0) + 1}")
                    walk(s.get("children") or [], depth + 1)
            walk(found, 0)
            return "\n".join(out[:300]) or "no symbols"
        position = self._position(p, args.get("symbol"), args.get("line"))
        doc = {"textDocument": {"uri": uri}, "position": position}
        if action == "definition":
            found = client.request("textDocument/definition", doc) or []
            found = [found] if isinstance(found, dict) else found
            return "\n".join(self._where(x) for x in found[:20]) or "no definition found"
        if action == "references":
            params = {**doc, "context": {"includeDeclaration": True}}
            found = client.request("textDocument/references", params) or []
            # A server that just started may not have read the whole project yet: ask again until it settles.
            while time.monotonic() - client.started < 20:
                time.sleep(1)
                again = client.request("textDocument/references", params) or []
                if len(again) == len(found):
                    break
                found = again
            listed = "\n".join(self._where(x) for x in found[:100])
            return (f"{len(found)} reference(s):\n{listed}" + ("\n…" if len(found) > 100 else "")) if found else "no references found"
        if action == "hover":
            found = client.request("textDocument/hover", doc)
            if not found:
                return "nothing to show"
            contents = found.get("contents")
            if isinstance(contents, dict):
                return contents.get("value", "")[:4000]
            if isinstance(contents, list):
                return "\n".join(c if isinstance(c, str) else c.get("value", "") for c in contents)[:4000]
            return str(contents)[:4000]
        raise LSPError(f"unknown action {action!r}")

    def _any_client(self, path: str | None) -> Client:
        if path:
            return self.client_for(self._file(path))
        if self.clients:
            return next(iter(self.clients.values()))
        for spec in self.specs:  # start the server for the project's most common language
            for ext in spec.extensions:
                sample = next((f for f in self.root.rglob(f"*{ext}") if ".git" not in f.parts
                               and "node_modules" not in f.parts), None)
                if sample:
                    client = self.client_for(sample)
                    client.sync(sample)
                    return client
        raise LSPError("no language server for this project's files")

    def shutdown(self) -> None:
        for client in list(self.clients.values()):
            client.close()
        self.clients.clear()
