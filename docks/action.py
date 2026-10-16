"""`docks action`: the @docks bot, run inside GitHub Actions.

Mention @docks in an issue or pull request (or label an issue `docks`) and this:
  - on an issue: makes the change on a new branch, commits, pushes and opens a pull request;
  - on a pull request: makes the requested change and pushes it to the PR branch,
    or answers / reviews when no code change is needed;
  - with auto-review on: reviews every new pull request.

Only people with write access (owners, members, collaborators) can trigger it, because each
run spends the repository's API credits and can push code.
"""

import json
import os
from pathlib import Path

from . import github
from .agent import Agent, DEFAULT_MODEL

ALLOWED = {"OWNER", "MEMBER", "COLLABORATOR"}
BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"

WORKFLOW = """\
name: Docks

# Mention @docks in an issue or pull request, or label an issue "docks".
on:
  issue_comment:
    types: [created]
  pull_request_review_comment:
    types: [created]
  issues:
    types: [opened, labeled]
  pull_request:
    types: [opened, ready_for_review]

permissions:
  contents: write
  pull-requests: write
  issues: write

jobs:
  docks:
    if: >-
      (github.event_name == 'issue_comment' && contains(github.event.comment.body, '@docks')) ||
      (github.event_name == 'pull_request_review_comment' && contains(github.event.comment.body, '@docks')) ||
      (github.event_name == 'issues' && (contains(github.event.issue.body, '@docks') || github.event.label.name == 'docks')) ||
      (github.event_name == 'pull_request' && vars.DOCKS_AUTO_REVIEW == 'true')
    runs-on: ubuntu-latest
    timeout-minutes: 60
    concurrency:
      group: docks-${{ github.event.issue.number || github.event.pull_request.number }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install "__SOURCE__"
      - run: docks action
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          DOCKS_MODEL: ${{ vars.DOCKS_MODEL }}
"""

DEFAULT_SOURCE = "git+https://github.com/JBWeb1/Docks"


def install(root: Path, source: str = DEFAULT_SOURCE) -> Path:
    path = root / ".github" / "workflows" / "docks.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(WORKFLOW.replace("__SOURCE__", source))
    return path


def _git(root, *args, **kw):
    return github.git(root, "-c", f"user.name={BOT_NAME}", "-c", f"user.email={BOT_EMAIL}", *args, **kw)


def _push_env() -> dict:
    # In Actions, actions/checkout already gave git the token; a second auth header would break pushes.
    return {} if os.environ.get("GITHUB_ACTIONS") == "true" else github._auth_env()


def _short(text: str, trigger: str) -> str:
    lines = text.replace(trigger, "").strip().splitlines()
    return (lines[0][:60] if lines else "") or "requested changes"


def _commit_all(root: Path, message: str) -> bool:
    if not github.git(root, "status", "--porcelain"):
        return False
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)
    return True


def parse_event(name: str, event: dict, trigger: str) -> dict | None:
    """Work out what was asked, by whom, on which issue or PR. None means: not for us."""
    if name in ("issue_comment", "pull_request_review_comment"):
        comment = event["comment"]
        if trigger not in comment.get("body", ""):
            return None
        if name == "issue_comment":
            item, is_pr = event["issue"], "pull_request" in event["issue"]
        else:
            item, is_pr = event["pull_request"], True
        text = comment["body"]
        if name == "pull_request_review_comment":
            text = f"(On {comment.get('path')} line {comment.get('line')}.)\n{text}"
        return {"number": item["number"], "is_pr": is_pr, "text": text, "user": comment["user"]["login"],
                "association": comment.get("author_association", ""), "mode": "request"}
    if name == "issues":
        issue = event["issue"]
        labeled = event.get("action") == "labeled" and (event.get("label") or {}).get("name") == "docks"
        if not labeled and trigger not in (issue.get("body") or ""):
            return None
        # For a label, the person who added it is the one asking.
        user = event["sender"]["login"] if labeled else issue["user"]["login"]
        association = "COLLABORATOR" if labeled else issue.get("author_association", "")
        return {"number": issue["number"], "is_pr": False, "user": user, "association": association,
                "text": f"{issue['title']}\n\n{issue.get('body') or ''}", "mode": "request"}
    if name == "pull_request":
        pr = event["pull_request"]
        if pr.get("draft"):
            return None
        return {"number": pr["number"], "is_pr": True, "user": pr["user"]["login"], "text": "",
                "association": pr.get("author_association", ""), "mode": "review"}
    return None


def run(root: Path, event_name: str, event: dict, repo: str, run_url: str, model: str,
        trigger: str = "@docks", client=None) -> str:
    """Handle one event. Returns a short status string (also what tests check)."""
    task = parse_event(event_name, event, trigger)
    if not task:
        return "ignored: not for docks"
    task["trigger"] = trigger
    if task["association"] not in ALLOWED:
        return f"ignored: @{task['user']} doesn't have write access"
    n = task["number"]
    agent_kw = {"root": root, "model": model, "auto_approve": True, "exclude_tools": ("create_pull_request",)}
    if client is not None:
        agent_kw["client"] = client

    if task["mode"] == "review":
        agent = Agent(**agent_kw)
        agent.run(github.review_pr_prompt(n))
        return "reviewed"

    footer = f"\n\n<sub>[View run]({run_url})</sub>"
    progress = github.request("POST", f"/repos/{repo}/issues/{n}/comments",
                              {"body": f"Docks is working on this… {footer}"})

    def reply(body: str) -> None:
        github.update_comment(repo, progress["id"], body + footer)

    try:
        if task["is_pr"]:
            result = _handle_pr(root, repo, n, task, agent_kw)
        else:
            result = _handle_issue(root, repo, n, task, agent_kw)
        reply(result)
        return "done"
    except Exception as e:
        reply(f"Docks ran into a problem: `{e}`")
        raise


def _request_block(task: dict) -> str:
    return f"Request from @{task['user']}:\n\n{task['text']}"


def _handle_issue(root: Path, repo: str, n: int, task: dict, agent_kw: dict) -> str:
    branch = f"docks/issue-{n}"
    default = github.request("GET", f"/repos/{repo}")["default_branch"]
    # Asked again on the same issue: continue the existing branch instead of starting over.
    exists = github.git(root, "ls-remote", "--heads", "origin", branch, env=_push_env())
    start = f"origin/{default}"
    if exists:
        github.git(root, "fetch", "-q", "origin", branch, env=_push_env())
        start = f"origin/{branch}"
    _git(root, "checkout", "-q", "-B", branch, start)
    agent = Agent(**agent_kw)
    agent.run(
        f"You're working on GitHub issue #{n} in {repo}, on branch {branch}. Read it with github_issue.\n\n"
        f"{_request_block(task)}\n\n"
        "If this needs code changes, make them, add or update tests, and run the tests until they pass. "
        "Don't commit, push or open a pull request; Docks does that after you finish. If it's a question, "
        "just answer it. End with a short summary for the issue thread: what you changed and why.")
    summary = agent.last_text() or "Done."
    title = github.request("GET", f"/repos/{repo}/issues/{n}")["title"]
    if not _commit_all(root, f"Fix #{n}: {title}"):
        return summary
    github.git(root, "push", "-q", "origin", branch, env=_push_env())
    owner = repo.split("/")[0]
    open_prs = github.request("GET", f"/repos/{repo}/pulls?state=open&head={owner}:{branch}")
    if open_prs:
        return f"{summary}\n\nUpdated {open_prs[0]['html_url']}"
    pr = github.request("POST", f"/repos/{repo}/pulls", {
        "title": f"Fix #{n}: {title}", "head": branch, "base": default,
        "body": f"{summary}\n\nFixes #{n}\n\n_Opened by Docks at @{task['user']}'s request._"})
    return f"{summary}\n\nOpened {pr['html_url']}"


def _handle_pr(root: Path, repo: str, n: int, task: dict, agent_kw: dict) -> str:
    pr = github.request("GET", f"/repos/{repo}/pulls/{n}")
    same_repo = (pr["head"].get("repo") or {}).get("full_name") == repo
    branch = pr["head"]["ref"]
    if same_repo:
        github.git(root, "fetch", "-q", "origin", branch, env=_push_env())
        _git(root, "checkout", "-q", "-B", branch, f"origin/{branch}")
    else:
        github.git(root, "fetch", "-q", "origin", f"pull/{n}/head", env=_push_env())
        _git(root, "checkout", "-q", "FETCH_HEAD")
    can_push = "Make the requested changes and run the tests; don't commit or push, Docks pushes them to this " \
               "branch after you finish." if same_repo else \
               "This pull request comes from a fork, so changes can't be pushed: answer or review only."
    agent = Agent(**agent_kw)
    agent.run(
        f"You're working on pull request #{n} in {repo} (branch {branch}). Read it with github_pr for context.\n\n"
        f"{_request_block(task)}\n\n"
        f"If the request needs code changes: {can_push} If it's a question, answer it. If it asks for a review, "
        "post one with review_pull_request. End with a short summary for the PR thread.")
    summary = agent.last_text() or "Done."
    if same_repo and _commit_all(root, f"Docks: {_short(task['text'], task['trigger'])}"):
        github.git(root, "push", "-q", "origin", f"HEAD:{branch}", env=_push_env())
        sha = github.git(root, "rev-parse", "--short", "HEAD")
        return f"{summary}\n\nPushed {sha} to `{branch}`."
    return summary


def github_trigger() -> str:
    return os.environ.get("DOCKS_TRIGGER", "@docks")


def main(argv=None) -> int:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        print("docks action runs inside GitHub Actions. To set it up in a repo, run: docks install-github")
        return 1
    root = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
    repo = os.environ["GITHUB_REPOSITORY"]
    run_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repo}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"
    result = run(root, os.environ["GITHUB_EVENT_NAME"], json.loads(Path(event_path).read_text()), repo, run_url,
                 model=os.environ.get("DOCKS_MODEL") or DEFAULT_MODEL, trigger=github_trigger())
    print(f"docks: {result}")
    return 0
