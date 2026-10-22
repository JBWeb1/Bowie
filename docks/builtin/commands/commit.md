---
description: Commit the current changes with a good message
argument-hint: "[optional message hint]"
---
Commit the current changes.

Current status:
!`git status --short`

Diff summary:
!`git diff HEAD --stat`

Recent commit messages (match their style):
!`git log --oneline -8`

Look at the full diff (`git diff HEAD`) to understand the change. Don't commit files that look like
secrets (.env, keys, credentials) or build output; mention them if present. Stage the relevant files
and commit with a concise message that says what changed and why. Hint from the user: $ARGUMENTS
If there's nothing to commit, say so.
