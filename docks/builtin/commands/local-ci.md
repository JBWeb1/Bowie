---
description: Run this repo's GitHub Actions locally with act and fix failures
argument-hint: "[workflow or job]"
---
Run this repository's GitHub Actions workflows locally with nektos/act before pushing. Target: $ARGUMENTS (all push workflows if empty).
Check that act and Docker are installed; if not, explain how to install them on this OS (winget/choco on Windows, brew on macOS, the install script on Linux) and stop. List jobs with `act -l`, run the selected ones, read the logs, fix failures in the code, and re-run until green. Never put real secrets on the command line; use `act --secret-file` with a git-ignored file if secrets are needed.
