"""Auto mode: approve safe actions on their own and ask only about risky ones.

Clear cases are decided by rules (edits inside the project are fine because every task can be undone;
`rm -rf /` or `git push --force` always ask). Everything in between goes to a small, fast model.
Anything it can't decide, or any error, means asking the user.
"""

import re
from pathlib import Path

CLASSIFIER_MODEL = "claude-haiku-5-5"

SAFE_COMMANDS = re.compile(r"""^\s*(
    ls|pwd|cat|head|tail|wc|echo|printf|which|type|file|stat|tree|du|df|date|env|uname|whoami|
    grep|rg|find|fd|sort|uniq|diff|cut|tr|jq|sed\s+-n|awk|
    git\s+(status|diff|log|show|branch|rev-parse|ls-files|blame|stash\s+list|remote\s+-v|add|commit|checkout\s+-b|switch\s+-c|fetch)|
    (npm|pnpm|yarn|bun)\s+(test|run\s+(test|build|lint|dev|start|typecheck|format)|install|ci|ls|outdated)|
    npx\s+(tsc|eslint|prettier|vitest|jest|playwright\s+test)|
    (python3?|py)\s+(-m\s+(pytest|unittest|http\.server|pip\s+(install|list|show)|venv|compileall|json\.tool)|[\w./-]+\.py)|
    pytest|tsc|eslint|prettier|ruff|black|mypy|flake8|
    pip3?\s+(install|list|show|freeze)|uv\s+(pip|run|sync)|poetry\s+(install|run)|
    cargo\s+(build|test|check|run|fmt|clippy)|go\s+(build|test|run|vet|fmt|mod)|make(\s|$)|
    node\s+[\w./-]+|deno\s+(run|test)|mkdir|touch|cp|mv
)(\s|$)""", re.X)

DANGEROUS = re.compile(r"""(
    \bsudo\b|\bsu\s|\brm\s+-[a-z]*r[a-z]*f?\s+(/|~|\$HOME|\*|\.\.)|\bmkfs|\bdd\s+if=|:\(\)\s*\{|
    \bchmod\s+-R\s+777|\bchown\s+-R|>\s*/dev/sd|\bshutdown\b|\breboot\b|
    (curl|wget)[^|]*\|\s*(sh|bash|python)|
    \bgit\s+push\b.*(--force|-f\b)|\bgit\s+reset\s+--hard|\bgit\s+clean\s+-[a-z]*f|
    \bdrop\s+(table|database)\b|\btruncate\s+table\b|
    \bnpm\s+publish\b|\bpip\s+uninstall\b|\bkill\s+-9\s+-1|\bcrontab\b|~/\.ssh|/etc/
)""", re.X | re.I)

ALWAYS_ASK = {"create_pull_request", "github_comment", "review_pull_request"}

CLASSIFIER_PROMPT = """You review actions an AI coding agent wants to take in a user's project at {root}.
Decide if the action is safe to run without asking the user.

Safe: reading, building, testing, formatting, installing project dependencies, editing or creating files
inside the project, running local dev servers, ordinary git commits.
Ask: anything that deletes or overwrites data outside the project, touches system files or credentials,
sends data to external services, publishes, deploys, pushes, spends money, or that you can't judge.

Reply with exactly one line: ALLOW: <short reason>  or  ASK: <short reason>"""


def _inside(root: Path, path: str) -> bool:
    try:
        return (root / path).resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        return False


def rule_verdict(tool: str, args: dict, root: Path) -> tuple[str, str] | None:
    """("allow"|"ask", reason) when a rule decides, else None (ask the classifier)."""
    if tool in ALWAYS_ASK:
        return "ask", "it acts on GitHub"
    if tool in ("write_file", "edit_file"):
        if _inside(root, str(args.get("path", ""))):
            return "allow", "an edit inside the project (can be undone)"
        return "ask", "it writes outside the project"
    if tool in ("bash", "start_process"):
        command = str(args.get("command", ""))
        if DANGEROUS.search(command):
            return "ask", "the command looks destructive"
        parts = [p for p in re.split(r"&&|\|\||;|\|", command) if p.strip()]
        if parts and all(SAFE_COMMANDS.match(p) for p in parts):
            return "allow", "a routine development command"
        return None
    return None


def classify(client, tool: str, args: dict, root: Path) -> tuple[str, str]:
    """Decide whether to run an action without asking. Never raises: on doubt it says ask."""
    verdict = rule_verdict(tool, args, root)
    if verdict:
        return verdict
    if client is None:
        return "ask", "no model available to judge it"
    detail = args.get("command") if tool in ("bash", "start_process") else str(args)[:2000]
    try:
        response = client.messages.create(
            model=CLASSIFIER_MODEL, max_tokens=600,
            system=CLASSIFIER_PROMPT.format(root=root),
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": f"Tool: {tool}\nAction: {detail}"}])
        text = "".join(getattr(b, "text", "") for b in response.content).strip()
    except Exception as e:  # network, auth, refusal… asking is always safe
        return "ask", f"couldn't check automatically ({type(e).__name__})"
    m = re.search(r"\b(ALLOW|ASK)\s*:\s*(.*)", text)
    if not m:
        return "ask", "the automatic check was unclear"
    return ("allow" if m.group(1) == "ALLOW" else "ask"), m.group(2).strip()[:200]
