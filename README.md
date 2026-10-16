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

## Docks Router: one endpoint for every coding tool

`docks router` is a self-hosted gateway, similar to OmniRoute but focused on coding. Point Claude Code, Cline, Aider, Continue, OpenCode, Cursor or Docks at it, and it sends each request to whichever AI provider is available right now.

```bash
docks router init             # writes ~/.docks/router.json (edit routes and models here)
export ANTHROPIC_API_KEY=...  # set keys for any providers you use
export DEEPSEEK_API_KEY=...
ollama pull qwen2.5-coder     # optional: free local model with no usage limits
docks router serve            # http://127.0.0.1:8787, dashboard at /
docks router setup claude-code   # prints setup for your tool (also: cline, aider, continue, opencode, cursor, docks)
docks router routes           # shows which providers each route will use right now
```

How it keeps you working when a provider limits you:

- **Failover.** Each route is a chain of `provider/model` targets. A 429 rate limit, an outage, an out-of-credits error or a bad key makes the router try the next target immediately.
- **Cooldowns.** A provider that failed is skipped until it recovers. The router honors `retry-after` and backs off exponentially.
- **Wait instead of fail.** If every target is rate-limited, it waits for the first to recover (up to `max_wait_seconds`) instead of returning an error. It doesn't wait on errors that won't clear by themselves, such as a bad key, no credits, or a local server that isn't running.
- **No caps of its own.** The router adds no request limits, token caps or throttling. Local models (Ollama, LM Studio) have no usage limits at all, so put one at the end of a route.
- **Format translation.** Clients that speak Anthropic Messages can use OpenAI-compatible providers and the reverse, with streaming and tool calls. Supported: Anthropic, OpenAI, DeepSeek, Gemini, Mistral/Codestral, Groq, OpenRouter, xAI, Together, Fireworks, Cerebras, Ollama, LM Studio, plus any OpenAI-compatible URL.

Routes support `fallback` (in order), `round-robin`, and `latency` (fastest first) strategies. Model names resolve through `aliases`, then `routes`, then `provider/model`, then by prefix (`claude-` goes to Anthropic, `gpt-` to OpenAI, and so on). With `fallback_to_default`, every request can fall back to the default route.

Set `DOCKS_ROUTER_KEY` to require a key from clients. It's required if you listen on anything other than localhost. Provider keys come from environment variables and never leave your machine except to their own provider. The router logs request metadata only, never prompts.

Not supported yet: the OpenAI Responses API, which current Codex CLI requires.

## Project instructions

Put a `DOCKS.md` (or `AGENTS.md` / `CLAUDE.md`) in your project root with conventions, commands, and context. Docks reads it into its system prompt.

## How it works

```
docks/
  cli.py     argument parsing, REPL, slash commands
  agent.py   the agent loop: stream a turn, run tools, feed results back, repeat
  tools.py   bash, read_file, write_file, edit_file, glob, grep (+ input validation)
  ui.py      terminal rendering and approval prompts
  memory.py  lessons saved by the remember tool
  router/    the gateway: config, engine (failover), translate (formats), server, cli
```

Each turn streams from the Claude Messages API with adaptive thinking, progress notes between tool calls, prompt caching and server-side refusal fallback. When Claude calls tools, Docks runs them locally, sends the results back, and loops until Claude finishes.

Add a tool by adding an entry to `TOOLS` in `docks/tools.py`.

## Develop

```bash
pip install -e . pytest
pytest
```
