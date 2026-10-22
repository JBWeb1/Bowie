---
description: Review changes with several reviewers in parallel and report only well-supported problems
argument-hint: "[PR number | branch | nothing for uncommitted changes]"
---
Review code changes thoroughly, using several helper agents in parallel.

What to review: $ARGUMENTS
- If that's a pull request number, read it with github_pr.
- If it's a branch name, review `git diff <default branch>...<that branch>`.
- If it's empty, review the uncommitted changes (`git diff HEAD` plus new files from `git status`).

Steps:
1. Get the diff and the list of changed files. If there's nothing to review, say so and stop.
2. In ONE response, call delegate four times so the reviewers run in parallel. Give each the full diff
   (or tell it exactly which command produces it) and ask for a list of findings, each with file, line,
   what's wrong, a concrete scenario that triggers it, and a confidence from 0 to 100:
   - "Bug hunt": logic errors, wrong conditions, off-by-one, null/undefined, races, broken error handling.
   - "Security": injection, secrets in code, unsafe input handling, auth gaps, path traversal.
   - "Tests and behavior": what the change breaks for callers, missing tests for new behavior.
   - "Project rules": violations of instructions in DOCKS.md, CLAUDE.md or AGENTS.md, and of the
     conventions in the surrounding code.
3. For every finding with confidence 60 or more, check it yourself against the actual code: read the
   lines and trace the scenario. Drop anything you can't confirm, style nitpicks, and things that were
   already wrong before this change.
4. Report the confirmed findings, most severe first, each with file:line, the problem, the scenario
   and a suggested fix. If this is a pull request and the user asked you to post it, use
   review_pull_request with inline comments. If nothing survived, say the change looks good and what
   you checked.
