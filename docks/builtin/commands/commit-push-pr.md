---
description: Commit, push a branch and open a pull request in one go
argument-hint: "[optional notes for the PR]"
---
Commit the current changes, push them and open a pull request.

Current branch: !`git rev-parse --abbrev-ref HEAD`
Status:
!`git status --short`

1. If the current branch is the repository's default branch, create a descriptively named branch first.
2. Review the diff, stage the relevant files (no secrets or build output) and commit with a clear message.
3. Open the pull request with create_pull_request (it pushes the branch). The description should say
   what changed, why, and how it was tested. Notes from the user: $ARGUMENTS
4. Reply with the pull request link.
