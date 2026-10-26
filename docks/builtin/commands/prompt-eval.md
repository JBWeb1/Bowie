---
description: Test a prompt against example inputs and compare models
argument-hint: "PROMPT_FILE_OR_TEXT"
---
Evaluate this prompt like promptfoo does: $ARGUMENTS
Write promptfooconfig.yaml with the prompt, 6 to 10 realistic test cases (including edge cases) and assertions (contains, regex, or llm-rubric). If Node is available run `npx promptfoo@latest eval` and summarize the results; otherwise run the cases yourself with the models available and grade them. Suggest concrete prompt improvements and show the before/after pass rate.
