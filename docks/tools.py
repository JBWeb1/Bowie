"""Tools the agent can call: shell, file I/O, search."""

import fnmatch
import os
import re
import subprocess
from pathlib import Path

from . import github, memory

MAX_OUTPUT = 30_000  # chars returned to the model per tool call
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}


class ToolError(Exception):
    pass


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    half = MAX_OUTPUT // 2
    return f"{text[:half]}\n\n... [{len(text) - MAX_OUTPUT} chars truncated] ...\n\n{text[-half:]}"


def _resolve(root: Path, path: str) -> Path:
    p = Path(path)
    return (p if p.is_absolute() else root / p).resolve()


def bash(root: Path, command: str, timeout: int = 120, sandbox=None) -> str:
    argv = sandbox.argv(command) if sandbox else None  # a sandbox.Sandbox, when commands are sandboxed
    try:
        proc = subprocess.run(
            argv or command, shell=argv is None, cwd=root, capture_output=True, text=True,
            timeout=min(max(timeout, 1), 600),
        )
    except subprocess.TimeoutExpired:
        raise ToolError(f"command timed out after {timeout}s")
    out = proc.stdout + (f"\n[stderr]\n{proc.stderr}" if proc.stderr else "")
    return _truncate(f"{out}\n[exit code {proc.returncode}]".strip())


def read_file(root: Path, path: str, offset: int = 1, limit: int = 2000) -> str:
    p = _resolve(root, path)
    if not p.is_file():
        raise ToolError(f"not a file: {path}")
    lines = p.read_text(errors="replace").splitlines()
    start = max(offset, 1) - 1
    chunk = lines[start:start + limit]
    numbered = "\n".join(f"{i:>6}\t{line}" for i, line in enumerate(chunk, start + 1))
    if start + limit < len(lines):
        numbered += f"\n... ({len(lines) - start - limit} more lines; use offset to read on)"
    return _truncate(numbered or "(empty file)")


def write_file(root: Path, path: str, content: str) -> str:
    p = _resolve(root, path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"wrote {len(content)} chars to {p.relative_to(root) if p.is_relative_to(root) else p}"


def edit_file(root: Path, path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    p = _resolve(root, path)
    if not p.is_file():
        raise ToolError(f"not a file: {path}")
    text = p.read_text()
    count = text.count(old_string)
    if count == 0:
        raise ToolError("old_string not found; read the file and copy the text exactly")
    if count > 1 and not replace_all:
        raise ToolError(f"old_string occurs {count} times; add context to make it unique or set replace_all")
    p.write_text(text.replace(old_string, new_string) if replace_all else text.replace(old_string, new_string, 1))
    return f"edited {path} ({count if replace_all else 1} replacement(s))"


def _walk(base: Path):
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            yield Path(dirpath) / name


def glob(root: Path, pattern: str, path: str = ".") -> str:
    base = _resolve(root, path)
    hits = [str(f.relative_to(base)) for f in _walk(base)
            if fnmatch.fnmatch(str(f.relative_to(base)), pattern) or fnmatch.fnmatch(f.name, pattern)]
    return _truncate("\n".join(hits[:1000]) or "(no matches)")


def grep(root: Path, pattern: str, path: str = ".", file_glob: str = "*") -> str:
    try:
        rx = re.compile(pattern)
    except re.error as e:
        raise ToolError(f"bad regex: {e}")
    base = _resolve(root, path)
    files = [base] if base.is_file() else _walk(base)
    hits = []
    for f in files:
        if not fnmatch.fnmatch(f.name, file_glob):
            continue
        try:
            for n, line in enumerate(f.read_text(errors="strict").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{f.relative_to(root) if f.is_relative_to(root) else f}:{n}: {line[:300]}")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable
        if len(hits) >= 500:
            break
    return _truncate("\n".join(hits) or "(no matches)")


# name -> (function, mutates?, schema)
TOOLS = {
    "bash": (bash, True, {
        "description": "Run a shell command in the project directory. Use for builds, tests, git, installing packages, running code.",
        "properties": {
            "command": {"type": "string"},
            "timeout": {"type": "integer", "description": "Seconds, default 120, max 600"},
        },
        "required": ["command"],
    }),
    "read_file": (read_file, False, {
        "description": "Read a text file with line numbers.",
        "properties": {
            "path": {"type": "string"},
            "offset": {"type": "integer", "description": "1-based line to start at"},
            "limit": {"type": "integer", "description": "Max lines, default 2000"},
        },
        "required": ["path"],
    }),
    "write_file": (write_file, True, {
        "description": "Create or overwrite a file with the full content. Creates parent directories.",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
    }),
    "edit_file": (edit_file, True, {
        "description": "Replace an exact string in a file. old_string must match exactly and be unique unless replace_all is set.",
        "properties": {
            "path": {"type": "string"},
            "old_string": {"type": "string"},
            "new_string": {"type": "string"},
            "replace_all": {"type": "boolean"},
        },
        "required": ["path", "old_string", "new_string"],
    }),
    "remember": (memory.remember, False, {
        "description": "Save a short lesson for future sessions: a mistake to avoid, a fix that worked, "
                       "a user preference, how this project builds or tests. Use scope 'global' for lessons "
                       "that apply to any project. Don't save things that are obvious from the code.",
        "properties": {
            "note": {"type": "string"},
            "scope": {"type": "string", "enum": ["project", "global"]},
        },
        "required": ["note"],
    }),
    "github_issue": (github.github_issue, False, {
        "description": "Read a GitHub issue (title, body, labels, comments) from this repo's origin.",
        "properties": {"number": {"type": "integer"}},
        "required": ["number"],
    }),
    "github_pr": (github.github_pr, False, {
        "description": "Read a GitHub pull request: description, comments and the full diff.",
        "properties": {"number": {"type": "integer"}},
        "required": ["number"],
    }),
    "create_pull_request": (github.create_pull_request, True, {
        "description": "Push the current branch and open a pull request. Commit all changes on a feature branch first.",
        "properties": {
            "title": {"type": "string"},
            "body": {"type": "string", "description": "Markdown: what changed and why"},
            "base": {"type": "string", "description": "Target branch; default is the repo's default branch"},
            "draft": {"type": "boolean"},
        },
        "required": ["title"],
    }),
    "github_comment": (github.github_comment, True, {
        "description": "Post a comment on a GitHub issue or pull request.",
        "properties": {"number": {"type": "integer"}, "body": {"type": "string"}},
        "required": ["number", "body"],
    }),
    "review_pull_request": (github.review_pull_request, True, {
        "description": "Post a review on a pull request: a summary plus optional inline comments on lines of the new code.",
        "properties": {
            "number": {"type": "integer"},
            "body": {"type": "string", "description": "Review summary"},
            "comments": {"type": "array", "items": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "line": {"type": "integer"}, "body": {"type": "string"}},
                "required": ["path", "line", "body"],
            }},
            "verdict": {"type": "string", "enum": ["COMMENT", "APPROVE", "REQUEST_CHANGES"]},
        },
        "required": ["number", "body"],
    }),
    "glob": (glob, False, {
        "description": "Find files by glob pattern, e.g. '**/*.py' or '*.md'.",
        "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}},
        "required": ["pattern"],
    }),
    "grep": (grep, False, {
        "description": "Search file contents with a regex. Returns path:line: text.",
        "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string"},
            "file_glob": {"type": "string", "description": "Filter file names, e.g. '*.ts'"},
        },
        "required": ["pattern"],
    }),
}

_TYPES = {"string": str, "integer": int, "boolean": bool, "array": list, "object": dict}


def tool_definitions() -> list[dict]:
    return [
        {
            "name": name,
            "description": spec["description"],
            "eager_input_streaming": True,
            "input_schema": {
                "type": "object",
                "properties": spec["properties"],
                "required": spec["required"],
                "additionalProperties": False,
            },
        }
        for name, (_, _, spec) in TOOLS.items()
    ]


def _check(value, schema: dict, label: str) -> None:
    expected = _TYPES[schema["type"]]
    if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
        raise ToolError(f"{label} must be {schema['type']}")
    if "enum" in schema and value not in schema["enum"]:
        raise ToolError(f"{label} must be one of {schema['enum']}")
    if schema["type"] == "array" and "items" in schema:
        for i, item in enumerate(value):
            _check(item, schema["items"], f"{label}[{i}]")
    if schema["type"] == "object" and "properties" in schema:
        for key in schema.get("required", []):
            if key not in value:
                raise ToolError(f"{label} is missing {key}")
        for key, item in value.items():
            if key not in schema["properties"]:
                raise ToolError(f"{label} has unexpected field {key}")
            _check(item, schema["properties"][key], f"{label}.{key}")


def validate(name: str, args: object) -> None:
    """Inputs stream eagerly, so the API does not validate them; check here."""
    if name not in TOOLS:
        raise ToolError(f"unknown tool: {name}")
    if not isinstance(args, dict):
        raise ToolError("tool input must be a JSON object")
    spec = TOOLS[name][2]
    _check(args, {"type": "object", **spec}, "input")


def run_tool(root: Path, name: str, args: dict) -> str:
    validate(name, args)
    try:
        return TOOLS[name][0](root, **args)
    except github.GitHubError as e:
        raise ToolError(str(e))


def is_mutating(name: str) -> bool:
    return name in TOOLS and TOOLS[name][1]
