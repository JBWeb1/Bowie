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

### In the browser

```bash
docks web                 # opens http://127.0.0.1:8788 with a one-time link
docks web -C ~/my-site    # work on a specific project
```

You get a chat where Docks' work streams in as plain-language steps ("Wrote index.html", "Ran a command"). Each change it wants to make shows an approval card, with a colored diff for edits. Beside the chat are three tabs:

- **Preview** shows the site Docks is building, refreshing after every change, in desktop or phone width.
- **Code** is a file tree and viewer.
- **GitHub** has the repo, your changes and one-click GitHub tasks.

It has light and dark themes and works on phones. Settings (model, effort, auto-approve, theme) are under the gear menu. Reloading the page restores the conversation.

The browser link contains a one-time token. The API only accepts requests that carry it, so other websites can't reach Docks. The preview is served from a separate port under a secret path, and it never serves dotfiles like `.env` or `.git`. Docks listens only on this machine unless you pass `--host`. Anyone with the link can run commands on your machine, so don't share it.

| Flag | Meaning |
|---|---|
| `-C DIR` | project directory (default: current) |
| `-m MODEL` | Claude model (default `claude-opus-5-5`, or `$DOCKS_MODEL`) |
| `-e LEVEL` | effort: `low` `medium` `high` `xhigh` `max` (default `high`) |
| `-y` | auto-approve file writes and shell commands |

In interactive mode: `/clear` starts over, `/usage` shows tokens, `/yolo` toggles auto-approve, `/exit` quits. Ctrl-C cancels the current turn.

By default Docks asks before it writes a file or runs a shell command. Answer `a` to allow that tool for the rest of the session. Reading and searching never ask.

## GitHub

Docks works with GitHub the way Claude Code and Codex do. Connect by setting `GITHUB_TOKEN` (or logging in with `gh auth login`), then:

```bash
docks clone owner/repo        # clone and start working (add --web for the browser)
docks fix 42                  # read issue #42, fix it on a branch, run tests, open a PR
docks review 17               # review PR #17 and post comments on the exact lines
docks pr                      # commit current changes on a branch and open a PR
```

The agent has GitHub tools too, so you can just say "fix issue 42" or "review PR 17" in a chat. It can read issues and PRs (including diffs), open pull requests, comment, and post reviews with inline comments. Pushing, opening PRs and posting comments always ask first unless auto-approve is on. Docks never commits to the default branch or force-pushes. Your token is sent only to GitHub. It goes to git as an environment setting, never on the command line or into `.git/config`.

In the browser, the **GitHub** tab shows the repo, branch and uncommitted changes (with a diff), and has one-click Fix an issue, Review a pull request and Open a pull request. In an empty folder it can clone a repo for you.

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
  github.py  GitHub API + git: issues, PRs, reviews, push, clone
  router/    the gateway: config, engine (failover), translate (formats), server, cli
  web/       browser UI: server.py (API, live events, preview) and app.html
```

Each turn streams from the Claude Messages API with adaptive thinking, progress notes between tool calls, prompt caching and server-side refusal fallback. When Claude calls tools, Docks runs them locally, sends the results back, and loops until Claude finishes.

Add a tool by adding an entry to `TOOLS` in `docks/tools.py`.

## Develop

```bash
pip install -e . pytest
pytest
```
