"""GitHub integration: read issues and pull requests, push branches, open PRs, post reviews.

Auth comes from GITHUB_TOKEN / GH_TOKEN, then the account you connected with `docks github login` (saved in
~/.docks/github.json, readable only by you), then the GitHub CLI (`gh auth token`) if it's logged in.
The token is only ever sent to the GitHub API and to git over HTTPS; it's never put on a command line.
"""

import base64
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

API = os.environ.get("GITHUB_API_URL", "https://api.github.com")
MAX_DIFF = 60_000


class GitHubError(Exception):
    pass


def account_path() -> Path:
    return Path(os.environ.get("DOCKS_HOME", Path.home() / ".docks")) / "github.json"


def _saved_account() -> dict:
    try:
        return json.loads(account_path().read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def token_source() -> str | None:
    if os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"):
        return "environment"
    if _saved_account().get("token"):
        return "docks"
    if shutil.which("gh") and _gh_token():
        return "gh"
    return None


def _gh_token() -> str | None:
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def token() -> str | None:
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or _saved_account().get("token")
    if tok:
        return tok
    if shutil.which("gh"):
        try:
            out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
            return out.stdout.strip() or None
        except (OSError, subprocess.TimeoutExpired):
            return None
    return None


def git(root: Path, *args: str, check: bool = True, env: dict | None = None, strip: bool = True) -> str:
    proc = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=300,
                          env={**os.environ, **(env or {})})
    if check and proc.returncode != 0:
        raise GitHubError(f"git {' '.join(args)} failed: {(proc.stderr or proc.stdout).strip()}")
    return proc.stdout.strip() if strip else proc.stdout


def _auth_env() -> dict:
    """Pass the token to git as an HTTP header via env config, so it never appears in argv or .git/config."""
    tok = token()
    if not tok:
        return {}
    basic = base64.b64encode(f"x-access-token:{tok}".encode()).decode()
    host = re.sub(r"^https?://(api\.)?", "", API).split("/")[0]
    host = "github.com" if host in ("github.com", "api.github.com") else host
    return {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": f"http.https://{host}/.extraheader",
            "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}"}


def parse_repo(url: str) -> str | None:
    """owner/repo from an https or ssh remote URL, or from 'owner/repo' itself."""
    m = re.search(r"(?:github\.com[:/]|^)([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", url.strip())
    return f"{m.group(1)}/{m.group(2)}" if m else None


def repo_of(root: Path) -> str:
    try:
        url = git(root, "config", "--get", "remote.origin.url")  # raw URL, before any insteadOf rewrite
    except GitHubError:
        raise GitHubError("this project has no 'origin' remote on GitHub")
    repo = parse_repo(url)
    if not repo:
        raise GitHubError(f"origin is not a GitHub repository: {url}")
    return repo


def request(method: str, path: str, body: dict | None = None, accept: str = "application/vnd.github+json"):
    tok = token()
    if not tok:
        raise GitHubError("not connected to GitHub: run `docks github login` (or set GITHUB_TOKEN)")
    req = urllib.request.Request(f"{API}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"authorization": f"Bearer {tok}", "accept": accept,
                                          "x-github-api-version": "2022-11-28",
                                          "user-agent": "docks", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        raise GitHubError(f"GitHub API {method} {path} returned {e.code}: {detail}")
    except urllib.error.URLError as e:
        raise GitHubError(f"could not reach GitHub: {e.reason}")
    if accept.endswith("diff"):
        return raw.decode(errors="replace")
    return json.loads(raw) if raw else {}


# ------------------------------------------------------------ agent tools


def _comments(repo: str, number: int) -> str:
    comments = request("GET", f"/repos/{repo}/issues/{number}/comments?per_page=50")
    return "\n\n".join(f"@{c['user']['login']}:\n{c['body']}" for c in comments) or "(no comments)"


def github_issue(root: Path, number: int) -> str:
    repo = repo_of(root)
    issue = request("GET", f"/repos/{repo}/issues/{number}")
    labels = ", ".join(l["name"] for l in issue.get("labels", [])) or "none"
    return (f"{repo}#{number}: {issue['title']}\nstate: {issue['state']}  labels: {labels}  "
            f"author: @{issue['user']['login']}\n\n{issue.get('body') or '(no description)'}\n\n"
            f"--- comments ---\n{_comments(repo, number)}")


def github_pr(root: Path, number: int) -> str:
    repo = repo_of(root)
    pr = request("GET", f"/repos/{repo}/pulls/{number}")
    diff = request("GET", f"/repos/{repo}/pulls/{number}", accept="application/vnd.github.diff")
    if len(diff) > MAX_DIFF:
        diff = diff[:MAX_DIFF] + f"\n… diff truncated ({len(diff)} chars); fetch the branch to see the rest"
    return (f"{repo}#{number}: {pr['title']}\nstate: {pr['state']}  {pr['head']['ref']} -> {pr['base']['ref']}  "
            f"author: @{pr['user']['login']}  +{pr['additions']} -{pr['deletions']} in {pr['changed_files']} files\n\n"
            f"{pr.get('body') or '(no description)'}\n\n--- comments ---\n{_comments(repo, number)}\n\n--- diff ---\n{diff}")


def create_pull_request(root: Path, title: str, body: str = "", base: str = "", draft: bool = False) -> str:
    repo = repo_of(root)
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    info = request("GET", f"/repos/{repo}")
    base = base or info["default_branch"]
    if branch == base:
        raise GitHubError(f"you're on {base}; create a feature branch and commit to it first")
    if git(root, "status", "--porcelain"):
        raise GitHubError("there are uncommitted changes; commit them before opening a pull request")
    git(root, "push", "-u", "origin", branch, env=_auth_env())
    pr = request("POST", f"/repos/{repo}/pulls",
                 {"title": title, "body": body, "head": branch, "base": base, "draft": draft})
    return f"opened {pr['html_url']}"


def github_comment(root: Path, number: int, body: str) -> str:
    repo = repo_of(root)
    c = request("POST", f"/repos/{repo}/issues/{number}/comments", {"body": body})
    return f"commented: {c['html_url']}"


def update_comment(repo: str, comment_id: int, body: str) -> None:
    request("PATCH", f"/repos/{repo}/issues/comments/{comment_id}", {"body": body})


def review_pull_request(root: Path, number: int, body: str, comments: list | None = None,
                        verdict: str = "COMMENT") -> str:
    repo = repo_of(root)
    payload = {"body": body, "event": verdict}
    if comments:
        payload["comments"] = [{"path": c["path"], "line": int(c["line"]), "side": "RIGHT", "body": c["body"]}
                               for c in comments]
    r = request("POST", f"/repos/{repo}/pulls/{number}/reviews", payload)
    return f"review posted: {r.get('html_url', 'ok')}"


# ------------------------------------------------------- status and clone


def status(root: Path) -> dict:
    """Everything the UI needs to show: repo, branch, changed files and the diff."""
    out = {"is_repo": False, "connected": bool(token()), "repo": None, "branch": None, "changes": [], "diff": ""}
    if git(root, "rev-parse", "--is-inside-work-tree", check=False) != "true":
        return out
    out["is_repo"] = True
    out["branch"] = git(root, "rev-parse", "--abbrev-ref", "HEAD", check=False) or None
    try:
        out["repo"] = repo_of(root)
    except GitHubError:
        pass
    for line in git(root, "status", "--porcelain", check=False, strip=False).splitlines():
        out["changes"].append({"status": line[:2].strip() or "?", "path": line[3:]})
    diff = git(root, "diff", "HEAD", check=False) if out["changes"] else ""
    out["diff"] = diff[:MAX_DIFF] + ("\n… (diff truncated)" if len(diff) > MAX_DIFF else "")
    return out


def clone(spec: str, dest: Path) -> Path:
    repo = parse_repo(spec)
    if not repo:
        raise GitHubError(f"not a GitHub repository: {spec}")
    host = "github.com" if "github.com" in API else re.sub(r"^https?://(api\.)?", "", API).split("/")[0]
    proc = subprocess.run(["git", "clone", f"https://{host}/{repo}.git", str(dest)], capture_output=True,
                          text=True, timeout=900, env={**os.environ, **_auth_env()})
    if proc.returncode != 0:
        raise GitHubError(f"clone failed: {proc.stderr.strip()}")
    return dest


# Canned tasks: the same workflows Claude Code and Codex offer for GitHub.
def fix_issue_prompt(number: int) -> str:
    return (f"Fix GitHub issue #{number}. Read it with github_issue. Create a branch named docks/issue-{number} "
            "from the default branch, find the cause, make the fix, add or update tests, and run them until they "
            f"pass. Commit with a clear message, then open a pull request with create_pull_request whose body "
            f"explains the change and ends with 'Fixes #{number}'.")


def review_pr_prompt(number: int) -> str:
    return (f"Review GitHub pull request #{number}. Read it with github_pr and look at the surrounding code where "
            "needed. Look for real bugs, security problems, missing tests and unclear code; skip style nitpicks. "
            "Post one review with review_pull_request: a short summary, plus inline comments (path, line in the "
            "new file, body) for each concrete problem. Use verdict REQUEST_CHANGES only for real bugs.")


def open_pr_prompt() -> str:
    return ("Open a pull request for the current changes. Look at git status and the diff. If we're on the "
            "default branch, create a descriptively named branch first. Commit the changes with a clear message, "
            "then open the pull request with create_pull_request, with a title and a body that explains what "
            "changed and why.")


def deploy_prompt() -> str:
    return ("Deploy this project so it has a public URL. Work out what kind of project it is and pick the simplest "
            "fitting option that's available here: if VERCEL_TOKEN is set, use `npx vercel deploy --prod --yes "
            "--token $VERCEL_TOKEN`; if NETLIFY_AUTH_TOKEN is set, use `npx netlify-cli deploy --prod`; otherwise, if "
            "this is a GitHub repository and the site is static (or builds to static files), add a GitHub Pages "
            "workflow under .github/workflows that builds and publishes it, commit it on a branch and open a pull "
            "request. Build first and fix build errors. Finish with the live URL, or exactly what the user must do "
            "to finish (for example, which setting to turn on).")


# ------------------------------------------------------------ your account


WEB = "https://github.com" if API == "https://api.github.com" else re.sub(r"/api/v3/?$", "", API)
SCOPES = "repo read:org workflow"


def _check_token(tok: str) -> dict:
    req = urllib.request.Request(f"{API}/user", headers={"authorization": f"Bearer {tok}", "user-agent": "docks",
                                                         "accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            user = json.loads(resp.read())
            scopes = resp.headers.get("x-oauth-scopes") or ""
    except urllib.error.HTTPError as e:
        raise GitHubError("GitHub didn't accept that token" if e.code == 401 else f"GitHub returned {e.code}")
    except urllib.error.URLError as e:
        raise GitHubError(f"could not reach GitHub: {e.reason}")
    return {"login": user.get("login"), "name": user.get("name") or "", "avatar": user.get("avatar_url", ""),
            "scopes": scopes}


def save_token(tok: str, source: str = "token") -> dict:
    """Check a token with GitHub, then keep it in ~/.docks/github.json (only you can read it)."""
    tok = tok.strip()
    if not tok:
        raise GitHubError("no token given")
    info = _check_token(tok)
    path = account_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"token": tok, "source": source, **info}, f)
    os.chmod(path, 0o600)
    return info


def logout() -> bool:
    try:
        account_path().unlink()
        return True
    except FileNotFoundError:
        return False


def whoami() -> dict | None:
    """The connected account, or None."""
    tok = token()
    if not tok:
        return None
    saved = _saved_account()
    if saved.get("token") == tok and saved.get("login"):
        return {k: saved.get(k, "") for k in ("login", "name", "avatar", "scopes")} | {"source": token_source()}
    try:
        return _check_token(tok) | {"source": token_source()}
    except GitHubError:
        return None


def device_client_id() -> str | None:
    return os.environ.get("DOCKS_GITHUB_CLIENT_ID") or _saved_account().get("client_id")


def _form_post(url: str, fields: dict) -> dict:
    from urllib.parse import urlencode
    req = urllib.request.Request(url, data=urlencode(fields).encode(), method="POST",
                                 headers={"accept": "application/json", "user-agent": "docks"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise GitHubError(f"GitHub sign-in failed ({e.code}): {e.read().decode(errors='replace')[:200]}")
    except urllib.error.URLError as e:
        raise GitHubError(f"could not reach GitHub: {e.reason}")


def start_device_login(client_id: str | None = None) -> dict:
    """Step 1 of signing in with GitHub: a code to enter at github.com/login/device."""
    client_id = client_id or device_client_id()
    if not client_id:
        raise GitHubError("signing in through GitHub needs an OAuth app's client ID in DOCKS_GITHUB_CLIENT_ID "
                          "(see the README), or connect with a token instead")
    data = _form_post(f"{WEB}/login/device/code", {"client_id": client_id, "scope": SCOPES})
    if "device_code" not in data:
        raise GitHubError(data.get("error_description") or data.get("error") or "GitHub didn't start the sign-in")
    return {"client_id": client_id, "device_code": data["device_code"], "user_code": data["user_code"],
            "verification_uri": data.get("verification_uri", f"{WEB}/login/device"),
            "interval": int(data.get("interval", 5)), "expires_in": int(data.get("expires_in", 900))}


def poll_device_login(login: dict) -> dict | None:
    """Step 2: None while waiting for the person to approve; their account once they have."""
    data = _form_post(f"{WEB}/login/oauth/access_token", {
        "client_id": login["client_id"], "device_code": login["device_code"],
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code"})
    if data.get("access_token"):
        return save_token(data["access_token"], source="device")
    error = data.get("error")
    if error == "slow_down":
        login["interval"] = int(data.get("interval", login["interval"] + 5))
        return None
    if error == "authorization_pending":
        return None
    raise GitHubError({"expired_token": "the sign-in code expired; start again",
                       "access_denied": "sign-in was cancelled on GitHub"}.get(error, data.get("error_description") or str(error)))


# ------------------------------------------------------------ repositories, branches, pull requests


def my_repos(query: str = "", limit: int = 60) -> list[dict]:
    if query:
        login = (whoami() or {}).get("login", "")
        found = request("GET", "/search/repositories?per_page=50&q=" + urllib.request.quote(
            f"{query} in:name fork:true" + (f" user:{login}" if "/" not in query and login else "")))
        items = found.get("items", [])
        if not items and login:  # also look beyond your own account (orgs, public repos)
            items = request("GET", "/search/repositories?per_page=30&q=" + urllib.request.quote(f"{query} in:name")).get("items", [])
    else:
        items = request("GET", "/user/repos?sort=pushed&per_page=100&affiliation=owner,collaborator,organization_member")
    return [{"repo": r["full_name"], "private": r.get("private", False), "description": r.get("description") or "",
             "default_branch": r.get("default_branch", "main"), "pushed": r.get("pushed_at", ""),
             "language": r.get("language") or "", "url": r.get("html_url", "")} for r in items[:limit]]


def branches(repo: str) -> dict:
    info = request("GET", f"/repos/{repo}")
    found = request("GET", f"/repos/{repo}/branches?per_page=100")
    return {"default": info.get("default_branch", "main"),
            "branches": [{"name": b["name"], "protected": b.get("protected", False)} for b in found]}


def _checks(repo: str, sha: str) -> str:
    """success | failure | pending | none, for a commit's check runs and statuses."""
    try:
        runs = request("GET", f"/repos/{repo}/commits/{sha}/check-runs?per_page=100").get("check_runs", [])
        combined = request("GET", f"/repos/{repo}/commits/{sha}/status")
    except GitHubError:
        return "none"
    states = [r.get("conclusion") or "pending" for r in runs if r.get("status") == "completed"] + \
             ["pending" for r in runs if r.get("status") != "completed"] + \
             [st.get("state") for st in combined.get("statuses", [])]
    if not states:
        return "none"
    if any(x in ("failure", "error", "timed_out", "cancelled", "action_required") for x in states):
        return "failure"
    if any(x == "pending" for x in states):
        return "pending"
    return "success"


def _review_state(repo: str, number: int) -> str:
    try:
        reviews = request("GET", f"/repos/{repo}/pulls/{number}/reviews?per_page=100")
    except GitHubError:
        return ""
    latest = {}
    for r in reviews:
        if r.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            latest[(r.get("user") or {}).get("login")] = r["state"]
    if "CHANGES_REQUESTED" in latest.values():
        return "changes requested"
    return "approved" if "APPROVED" in latest.values() else ("commented" if reviews else "")


def pull_request_state(repo: str, number: int) -> dict:
    pr = request("GET", f"/repos/{repo}/pulls/{number}")
    state = "merged" if pr.get("merged") else pr.get("state", "open")
    return {"repo": repo, "number": number, "title": pr.get("title", ""), "author": (pr.get("user") or {}).get("login", ""),
            "state": state, "draft": pr.get("draft", False), "head": (pr.get("head") or {}).get("ref", ""),
            "base": (pr.get("base") or {}).get("ref", ""), "url": pr.get("html_url", ""),
            "updated": pr.get("updated_at", ""), "checks": _checks(repo, pr["head"]["sha"]) if state == "open" else "none",
            "review": _review_state(repo, number), "comments": pr.get("comments", 0) + pr.get("review_comments", 0)}


def pull_requests(repo: str, limit: int = 15) -> list[dict]:
    found = request("GET", f"/repos/{repo}/pulls?state=open&sort=updated&direction=desc&per_page={limit}")
    return [{"repo": repo, "number": p["number"], "title": p["title"], "author": (p.get("user") or {}).get("login", ""),
             "draft": p.get("draft", False), "head": p["head"]["ref"], "base": p["base"]["ref"], "url": p["html_url"],
             "updated": p.get("updated_at", ""), "checks": _checks(repo, p["head"]["sha"]), "state": "open"}
            for p in found]


def my_pull_requests() -> dict:
    """Open pull requests you wrote, and ones waiting for your review, across all repositories."""
    def search(q):
        items = request("GET", "/search/issues?per_page=30&sort=updated&q=" + urllib.request.quote(q)).get("items", [])
        return [{"repo": i["repository_url"].split("/repos/")[-1], "number": i["number"], "title": i["title"],
                 "url": i["html_url"], "updated": i.get("updated_at", ""), "draft": i.get("draft", False)} for i in items]
    return {"authored": search("is:pr is:open author:@me archived:false"),
            "review_requested": search("is:pr is:open review-requested:@me archived:false")}


def switch_branch(root: Path, name: str) -> str:
    if git(root, "status", "--porcelain", check=False):
        raise GitHubError("you have uncommitted changes; commit or stash them before switching branches")
    git(root, "fetch", "origin", name, check=False, env=_auth_env())
    if git(root, "rev-parse", "--verify", "-q", f"refs/heads/{name}", check=False):
        git(root, "switch", name)
    else:
        git(root, "switch", "-c", name, "--track", f"origin/{name}")
    return name
