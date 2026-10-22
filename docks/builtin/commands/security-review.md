---
description: Check changes for security holes and report only real, exploitable problems
argument-hint: "[PR number | branch | nothing for uncommitted changes]"
---
Do a security review of code changes.

What to review: $ARGUMENTS
- A pull request number: read it with github_pr.
- A branch name: review `git diff <default branch>...<that branch>`.
- Nothing: review the uncommitted changes (`git diff HEAD` plus new files from `git status`).

1. Get the diff. If there's nothing to review, say so and stop.
2. Understand the context before judging: read the changed files in full, see where inputs come from
   (requests, files, environment, other services), how data reaches databases, shells, file paths, HTML and
   redirects, and which checks (auth, validation, escaping) the project already has.
3. Look for problems the change introduces or makes reachable:
   - injection: SQL, shell commands, template, path traversal, unsafe deserialization, eval
   - authentication and authorization: missing checks, checks on the wrong user, guessable tokens
   - secrets: keys or passwords in code, logs or error messages
   - web: cross-site scripting, open redirects, CSRF on state-changing requests, unsafe CORS
   - data exposure: sensitive fields returned or logged, overly broad queries
   - crypto: home-made crypto, weak hashes for passwords, predictable randomness for secrets
   - dependencies added with known problems, and unsafe defaults in configuration
4. For each candidate, trace a concrete path from an attacker-controlled input to the harm. Drop anything you
   can't trace, anything already prevented elsewhere, and style or theoretical concerns. False alarms cost
   more than they help.
5. Report each remaining finding with: severity (high / medium / low), file and line, the attack in one or two
   sentences (input -> what happens), and the fix. If nothing survives, say the changes look safe and name
   the riskiest area you checked.

Don't change any files unless the user asks you to fix the findings.
