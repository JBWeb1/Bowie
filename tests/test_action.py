import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace as NS

import pytest

from docks import action, github
from tests.test_docks import FakeClient, msg, tool_use


class FakeGitHub:
    def __init__(self):
        self.calls, self.open_prs = [], []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, obj, status=200):
                data = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _handle(self):
                length = int(self.headers.get("content-length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                outer.calls.append((self.command, self.path, body))
                p = self.path
                if p == "/repos/o/r":
                    return self._reply({"default_branch": "main"})
                if p == "/repos/o/r/issues/7":
                    return self._reply({"title": "Greeting is wrong"})
                if p.endswith("/comments") and self.command == "POST":
                    return self._reply({"id": 555, "html_url": "c"}, 201)
                if p.startswith("/repos/o/r/issues/comments/"):
                    return self._reply({})
                if p.startswith("/repos/o/r/pulls?"):
                    return self._reply(outer.open_prs)
                if p == "/repos/o/r/pulls" and self.command == "POST":
                    return self._reply({"html_url": "https://github.com/o/r/pull/8"}, 201)
                if p == "/repos/o/r/pulls/9":
                    return self._reply({"head": {"ref": "feat", "repo": {"full_name": "o/r"}}})
                self._reply({"message": "not found"}, 404)

            do_GET = do_POST = do_PATCH = _handle

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def last_reply(self):
        return [b for m, p, b in self.calls if m == "PATCH"][-1]["body"]


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd,
                          check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def env(tmp_path, monkeypatch):
    fake = FakeGitHub()
    monkeypatch.setattr(github, "API", fake.url)
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_test")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    bare, seed = tmp_path / "remote.git", tmp_path / "seed"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    git(tmp_path, "clone", "-q", str(bare), str(seed))
    (seed / "hello.py").write_text("print('helo')\n")
    git(seed, "add", "-A")
    git(seed, "commit", "-qm", "init")
    git(seed, "push", "-q", "origin", "main")
    git(seed, "checkout", "-qb", "feat")
    git(seed, "push", "-q", "origin", "feat")
    work = tmp_path / "work"
    git(tmp_path, "clone", "-q", str(bare), str(work))
    git(work, "remote", "set-url", "origin", "https://github.com/o/r.git")
    git(work, "config", f"url.{bare}.insteadOf", "https://github.com/o/r.git")
    return NS(fake=fake, bare=bare, work=work)


def comment_event(body, association="COLLABORATOR", pr=False, number=7):
    issue = {"number": number, "title": "t", "user": {"login": "ann"}}
    if pr:
        issue["pull_request"] = {}
    return {"comment": {"body": body, "user": {"login": "ann"}, "author_association": association}, "issue": issue}


def fixing_agent():
    return FakeClient([
        msg("tool_use", tool_use("t1", "edit_file", path="hello.py", old_string="helo", new_string="hello")),
        msg("end_turn", NS(type="text", text="Fixed the typo in the greeting.")),
    ])


def run(env, event, name="issue_comment", client=None):
    return action.run(env.work, name, event, "o/r", "https://run", model="m", client=client or fixing_agent())


def test_issue_comment_opens_pull_request(env):
    assert run(env, comment_event("@docks please fix this")) == "done"
    assert git(env.bare, "show", "docks/issue-7:hello.py") == "print('hello')"
    pr = next(b for m, p, b in env.fake.calls if m == "POST" and p == "/repos/o/r/pulls")
    assert pr["head"] == "docks/issue-7" and pr["base"] == "main" and "Fixes #7" in pr["body"]
    assert "Fixed the typo" in pr["body"]
    reply = env.fake.last_reply()
    assert "Opened https://github.com/o/r/pull/8" in reply and "View run" in reply


def test_second_request_updates_existing_pr(env):
    run(env, comment_event("@docks fix it"))
    env.fake.open_prs = [{"html_url": "https://github.com/o/r/pull/8"}]
    again = FakeClient([
        msg("tool_use", tool_use("t1", "write_file", path="NOTES.md", content="more\n")),
        msg("end_turn", NS(type="text", text="Added notes.")),
    ])
    run(env, comment_event("@docks also add notes"), client=again)
    log = git(env.bare, "log", "--format=%s", "docks/issue-7")
    assert len(log.splitlines()) == 3  # init + two Docks commits: the branch was continued, not reset
    assert "Updated https://github.com/o/r/pull/8" in env.fake.last_reply()


def test_pr_comment_pushes_to_pr_branch(env):
    assert run(env, comment_event("@docks fix the typo", pr=True, number=9)) == "done"
    assert git(env.bare, "show", "feat:hello.py") == "print('hello')"
    assert git(env.bare, "log", "-1", "--format=%s", "feat") == "Docks: fix the typo"
    assert "Pushed" in env.fake.last_reply()


def test_question_without_changes_just_replies(env):
    client = FakeClient([msg("end_turn", NS(type="text", text="It prints a greeting."))])
    run(env, comment_event("@docks what does hello.py do?"), client=client)
    assert env.fake.last_reply().startswith("It prints a greeting.")
    assert not any(p == "/repos/o/r/pulls" for m, p, b in env.fake.calls)


def test_ignores_outsiders_and_unrelated_comments(env):
    assert run(env, comment_event("@docks delete everything", association="NONE")).startswith("ignored")
    assert run(env, comment_event("looks good to me")).startswith("ignored")
    assert env.fake.calls == []


def test_label_triggers_issue_fix(env):
    event = {"action": "labeled", "label": {"name": "docks"}, "sender": {"login": "maintainer"},
             "issue": {"number": 7, "title": "Greeting is wrong", "body": "typo", "user": {"login": "rando"},
                       "author_association": "NONE"}}
    assert run(env, event, name="issues") == "done"
    assert git(env.bare, "show", "docks/issue-7:hello.py") == "print('hello')"


def test_install_writes_workflow(tmp_path):
    path = action.install(tmp_path, "docks==0.1.0")
    text = path.read_text()
    assert path == tmp_path / ".github/workflows/docks.yml"
    assert 'pip install "docks==0.1.0"' in text and "run: docks action" in text
    assert "secrets.ANTHROPIC_API_KEY" in text
