# Docks

Docks is a coding agent for your terminal, powered by Claude. Tell it what to build, such as an app, a website, a script, an API or a game. It looks around your project, writes and edits files, runs commands and tests, and fixes what breaks until the job is done.

## Install

```bash
pip install -e .
export ANTHROPIC_API_KEY=sk-ant-...   # get one at https://console.anthropic.com
```

## Use

```bash
cd my-project
docks                                   # interactive session
docks "build a snake game in the browser"   # one-shot task
docks -y "add tests for utils.py and make them pass"   # no approval prompts
```

| Flag | Meaning |
|---|---|
| `-C DIR` | project directory (default: current) |
| `-m MODEL` | Claude model (default `claude-opus-5-5`, or `$DOCKS_MODEL`) |
| `-e LEVEL` | effort: `low` `medium` `high` `xhigh` `max` (default `high`) |
| `-y` | auto-approve file writes and shell commands |

In interactive mode: `/clear` starts over, `/usage` shows tokens, `/yolo` toggles auto-approve, `/exit` quits. Ctrl-C cancels the current turn.

By default Docks asks before it writes a file or runs a shell command. Answer `a` to allow that tool for the rest of the session. Reading and searching never ask.

## Project instructions

Put a `DOCKS.md` (or `AGENTS.md` / `CLAUDE.md`) in your project root with conventions, commands, and context. Docks reads it into its system prompt.

## How it works

```
docks/
  cli.py     argument parsing, REPL, slash commands
  agent.py   the agent loop: stream a turn, run tools, feed results back, repeat
  tools.py   bash, read_file, write_file, edit_file, glob, grep (+ input validation)
  ui.py      terminal rendering and approval prompts
```

Each turn streams from the Claude Messages API with adaptive thinking, progress notes between tool calls, prompt caching and server-side refusal fallback. When Claude calls tools, Docks runs them locally, sends the results back, and loops until Claude finishes.

Add a tool by adding an entry to `TOOLS` in `docks/tools.py`.

## Develop

```bash
pip install -e . pytest
pytest
```
