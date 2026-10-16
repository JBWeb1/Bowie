import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from docks import github
from docks.tools import ToolError, run_tool


class FakeGitHub:
    def __init__(self):
        self.requests = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, obj, ctype="application/json"):
                data = obj.encode() if isinstance(obj, str) else json.dumps(obj).encode()
                self.send_response(201 if self.command == "POST" else 200)
                self.send_header("content-type", ctype)
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                outer.requests.append(("GET", self.path, self.headers.get("authorization"), None))
                if self.path == "/repos/o/r":
                    return self._reply({"default_branch": "main"})
                if self.path.startswith("/repos/o/r/issues/7/comments") or self.path.startswith("/repos/o/r/issues/9/comments"):
                    return self._reply([{"user": {"login": "ann"}, "body": "still broken on Safari"}])
                if self.path == "/repos/o/r/issues/7":
                    return self._reply({"title": "Button does nothing", "state": "open", "labels": [{"name": "bug"}],
                                        "user": {"login": "bob"}, "body": "Clicking Save has no effect."})
                if self.path == "/repos/o/r/pulls/9":
                    if "diff" in self.headers.get("accept", ""):
                        return self._reply("diff --git a/x.py b/x.py\n+print('hi')\n", "text/plain")
                    return self._reply({"title": "Add greeting", "state": "open", "head": {"ref": "feat"},
                                        "base": {"ref": "main"}, "user": {"login": "cat"}, "additions": 1,
                                        "deletions": 0, "changed_files": 1, "body": "Says hi"})
                self.send_response(404)
                self.end_headers()

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                outer.requests.append(("POST", self.path, self.headers.get("authorization"), body))
                if self.path == "/repos/o/r/pulls":
                    return self._reply({"html_url": "https://github.com/o/r/pull/10"})
                if self.path.endswith("/reviews"):
                    return self._reply({"html_url": "https://github.com/o/r/pull/9#review"})
                return self._reply({"html_url": "https://github.com/o/r/issues/7#c1"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    fake = FakeGitHub()
    monkeypatch.setattr(github, "API", fake.url)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    work = tmp_path / "work"
    work.mkdir()
    git(work, "init", "-q", "-b", "main")
    git(work, "remote", "add", "origin", "https://github.com/o/r.git")
    # Send pushes for the GitHub URL to the local bare repo instead
    git(work, "config", f"url.{bare}.insteadOf", "https://github.com/o/r.git")
    (work / "app.py").write_text("print('v1')\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "init")
    git(work, "push", "-q", "origin", "main")
    return work, fake, bare


def test_parse_repo():
    assert github.parse_repo("git@github.com:o/r.git") == "o/r"
    assert github.parse_repo("https://github.com/o/r") == "o/r"
    assert github.parse_repo("https://gitlab.com/o/r") is None


def test_read_issue_and_pr(repo):
    work, fake, _ = repo
    issue = run_tool(work, "github_issue", {"number": 7})
    assert "Button does nothing" in issue and "still broken on Safari" in issue and "bug" in issue
    pr = run_tool(work, "github_pr", {"number": 9})
    assert "feat -> main" in pr and "+print('hi')" in pr
    assert all(auth == "Bearer ghp_test" for _, _, auth, _ in fake.requests)


def test_open_pull_request_pushes_branch(repo):
    work, fake, bare = repo
    with pytest.raises(ToolError, match="feature branch"):
        run_tool(work, "create_pull_request", {"title": "x"})
    git(work, "checkout", "-qb", "docks/issue-7")
    (work / "app.py").write_text("print('v2')\n")
    with pytest.raises(ToolError, match="uncommitted"):
        run_tool(work, "create_pull_request", {"title": "x"})
    git(work, "commit", "-qam", "fix")
    out = run_tool(work, "create_pull_request", {"title": "Fix save button", "body": "Fixes #7"})
    assert out == "opened https://github.com/o/r/pull/10"
    assert "docks/issue-7" in git(bare, "branch")
    post = next(r for r in fake.requests if r[0] == "POST")
    assert post[3] == {"title": "Fix save button", "body": "Fixes #7", "head": "docks/issue-7", "base": "main", "draft": False}


def test_review_with_inline_comments(repo):
    work, fake, _ = repo
    run_tool(work, "review_pull_request", {"number": 9, "body": "One bug", "verdict": "REQUEST_CHANGES",
                                           "comments": [{"path": "x.py", "line": 1, "body": "typo"}]})
    payload = fake.requests[-1][3]
    assert payload["event"] == "REQUEST_CHANGES"
    assert payload["comments"] == [{"path": "x.py", "line": 1, "side": "RIGHT", "body": "typo"}]
    with pytest.raises(ToolError, match="missing line"):
        run_tool(work, "review_pull_request", {"number": 9, "body": "b", "comments": [{"path": "x.py", "body": "no line"}]})


def test_status_reports_changes(repo):
    work, _, _ = repo
    (work / "app.py").write_text("print('changed')\n")
    (work / "new.txt").write_text("hi")
    st = github.status(work)
    assert st["repo"] == "o/r" and st["branch"] == "main" and st["connected"]
    assert {c["path"] for c in st["changes"]} == {"app.py", "new.txt"}
    assert "+print('changed')" in st["diff"]


def test_not_connected_message(repo, monkeypatch):
    work, _, _ = repo
    monkeypatch.delenv("GITHUB_TOKEN")
    monkeypatch.setattr(github.shutil, "which", lambda _: None)
    with pytest.raises(ToolError, match="not connected"):
        run_tool(work, "github_issue", {"number": 7})
