"""The observer: a second pair of eyes on each task, inspired by Meta's Muse Code observers.

After a turn that changed something, a separate, read-only model call compares what Bowers said it did with what
actually happened (the tool calls and their results, and the git diff). It reports:

  unverified  a claim in the reply that nothing in the log backs up ("tests pass" with no test run)
  missed      part of the request that wasn't done
  broken      a failed step that was never fixed or mentioned
  remember    a preference or project fact worth saving to memory

It never changes anything. Findings appear after the reply; /fix (or Fix it in the browser) hands them back to
Bowers. Turn it off with {"observer": false} in settings.json, or pick its model with {"observerModel": "..."}.
"""

import json
import re
import subprocess
from pathlib import Path

KINDS = ("unverified", "missed", "broken", "remember")
MAX_LOG = 24_000
MAX_DIFF = 16_000

PROMPT = """You are the observer for a coding agent called Bowers. You check its work; you never do the work.

You get the person's request, Bowers' final reply, a log of every action it took this turn (with results), and the
resulting git diff. Compare the reply with the evidence. Report only real problems:

- "unverified": the reply claims something (tests pass, it builds, the bug is fixed, the page works) that no action
  in the log shows. Name the claim and the check that would verify it.
- "missed": part of the request that the diff and log show wasn't done.
- "broken": an action failed and was never fixed or mentioned in the reply.
- "remember": the person stated a lasting preference or project fact worth saving as a note (only if clearly stated).

Be strict about evidence, and brief. No style opinions, no praise. If everything is backed up, return no findings.
Answer with JSON only:
{"summary": "<one short sentence>", "findings": [{"kind": "unverified|missed|broken|remember", "text": "<what>", "action": "<the concrete next step, or the note to save>"}]}"""


def worth_checking(events: list[dict]) -> bool:
    """Only turns that changed something: a successful action that edits files, runs commands, or similar."""
    changing = {e.get("id") for e in events if e.get("kind") == "tool_call" and e.get("mutating")}
    return any(e.get("kind") == "tool_result" and e.get("id") in changing and e.get("ok") for e in events)


def diff(root: Path) -> str:
    def git(*args):
        try:
            return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            return ""
    if not git("rev-parse", "--git-dir"):
        return "(not a git repository; no diff available)"
    out = git("diff", "HEAD", "--stat") + "\n" + git("diff", "HEAD")
    new = git("ls-files", "--others", "--exclude-standard")
    if new.strip():
        out += "\nNew files:\n" + new
    return out[:MAX_DIFF] + ("\n… (diff cut off)" if len(out) > MAX_DIFF else "")


def action_log(events: list[dict]) -> str:
    lines = []
    for e in events:
        who = f"[helper: {e['by']}] " if e.get("by") else ""
        if e.get("kind") == "tool_call":
            lines.append(f"{who}CALL {e.get('name')} {json.dumps(e.get('args'), default=str)[:600]}")
        elif e.get("kind") == "tool_result":
            lines.append(f"{who}{'OK' if e.get('ok') else 'FAILED'} {e.get('name')}: {str(e.get('output', ''))[:800]}")
    text = "\n".join(lines)
    return text if len(text) <= MAX_LOG else "… (earlier actions cut)\n" + text[-MAX_LOG:]


def parse(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    findings = [{"kind": f.get("kind") if f.get("kind") in KINDS else "unverified",
                 "text": str(f.get("text", "")).strip()[:500], "action": str(f.get("action", "")).strip()[:500]}
                for f in data.get("findings", []) if isinstance(f, dict) and str(f.get("text", "")).strip()]
    summary = str(data.get("summary", "")).strip()[:200] or ("Found things to check." if findings else "The work matches the reply.")
    return {"summary": summary, "findings": findings[:8]}


def check(client, model: str, request: str, reply: str, events: list[dict], changes: str) -> dict | None:
    """Ask the observer about one turn. Never raises: on any trouble it returns None and stays quiet."""
    try:
        response = client.messages.create(
            model=model, max_tokens=2000, system=PROMPT, output_config={"effort": "low"},
            messages=[{"role": "user", "content":
                       f"<request>\n{request[:6000]}\n</request>\n<reply>\n{reply[:6000]}\n</reply>\n"
                       f"<actions>\n{action_log(events)}\n</actions>\n<diff>\n{changes}\n</diff>"}])
        text = "".join(getattr(b, "text", "") or "" for b in response.content)
    except Exception:
        return None
    return parse(text)


def followup(findings: list[dict]) -> str:
    """The message /fix sends: the observer's concerns, for Bowers to verify or fix."""
    work = [f for f in findings if f["kind"] != "remember"]
    if not work:
        return ""
    lines = "\n".join(f"- ({f['kind']}) {f['text']}" + (f" Suggested: {f['action']}" if f["action"] else "") for f in work)
    return ("An observer reviewed your last turn against the action log and the diff and raised these points:\n"
            f"{lines}\n\nFor each one: actually verify it (run the check) or fix it. If a point is wrong, say why "
            "with evidence. Then report briefly what you confirmed and what you changed.")


def format_text(result: dict) -> str:
    if not result["findings"]:
        return f"Observer: {result['summary']}"
    marks = {"unverified": "?", "missed": "○", "broken": "✗", "remember": "★"}
    lines = [f"Observer: {result['summary']}"]
    for f in result["findings"]:
        lines.append(f"  {marks[f['kind']]} {f['text']}" + (f"  → {f['action']}" if f["action"] else ""))
    tips = []
    if followup(result["findings"]):
        tips.append("/fix to have Bowers address these")
    if any(f["kind"] == "remember" for f in result["findings"]):
        tips.append("# <note> to save a note")
    if tips:
        lines.append("  (" + "; ".join(tips) + ")")
    return "\n".join(lines)
