---
description: Build a feature step by step - explore, ask, design, build, review
argument-hint: "<what to build>"
---
Build this feature carefully, in phases: $ARGUMENTS

1. Understand. Restate the goal in one or two sentences. Keep an update_plan checklist of the phases
   below and keep it current.
2. Explore. Call delegate two or three times in one response so helpers explore in parallel: one maps
   the code closest to this feature (entry points, data flow, similar existing features), one finds
   the conventions to follow (patterns, tests, styling). Read the key files they point to yourself.
3. Clarify. If anything important is ambiguous (scope, edge cases, behavior, look), use ask_user with
   clear options and a recommended choice. Skip this if nothing is genuinely unclear.
4. Design. Lay out the approach: files to add or change, how it fits the existing architecture, and
   trade-offs. For a large change, present it with exit_plan_mode if plan mode is on, or briefly ask
   the user to confirm before building.
5. Build. Implement it completely, following the conventions you found. Add or update tests.
6. Verify. Run the tests, the build and the app. Fix what fails.
7. Review. Delegate one helper to review the finished diff for bugs and missed edge cases; fix real
   problems it finds.
8. Summarize what was built, the files changed, and how to try it.
