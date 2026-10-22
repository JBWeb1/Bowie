# Docks

Docks is a coding agent for your terminal, powered by Claude. Tell it what to build, such as an app, a website, a script, an API or a game. It looks around your project, writes and edits files, runs commands and tests, and fixes what breaks until the job is done.

## Install

```bash
pip install -e .
export ANTHROPIC_API_KEY=sk-ant-...   # get one at https://console.anthropic.com
docks doctor                          # check that everything works
```

Optional, and worth it:

```bash
pip install -e ".[browser]" && playwright install chromium   # Claude can open and test the apps it builds
npm i -g pyright typescript-language-server typescript        # code intelligence for Python and JS/TS
sudo apt install bubblewrap                                   # sandboxing on Linux (macOS has it built in)
```

## Use

```bash
cd my-project
docks                                   # interactive session
docks "build a snake game in the browser"   # one-shot task
docks -y "add tests for utils.py and make them pass"   # no approval prompts
docks --plan "add user accounts"        # research and propose a plan first
docks --continue                        # pick up your last conversation here
docks --resume "todo app"               # or any saved one, by name or id
docks sessions                          # list saved conversations
docks -w login "add a login page"       # work in a separate git worktree (see below)
docks -p "why does the build fail?"     # script mode: answer only, no questions (see below)
docks --sandbox                         # commands can only write inside the project
```

Inside a session, `/help` lists everything. Highlights:

| Command | What it does |
| --- | --- |
| `/mode ask\|auto\|plan\|yolo` | How Docks asks before changes (see below) |
| `/plan` | Switch to plan mode |
| `/sessions`, `/resume NAME`, `/rename NAME` | Saved conversations |
| `/bookmark`, `/bookmarks` | Keep a reply to find later |
| `/copy` | Copy Claude's last reply to the clipboard |
| `/undo` | Put files back to before the last task |
| `/review`, `/feature`, `/commit`, `/commit-push-pr`, `/init` | Built-in workflows (below) |
| `/commands`, `/agents`, `/skills`, `/hooks` | What's installed |
| `/permissions`, `/allow RULE`, `/ask RULE`, `/deny RULE` | Permission rules (below) |
| `/sandbox [on\|off]` | Run commands in a sandbox |
| `/compact [focus]` | Summarize the conversation to free up room |
| `/context` | What's filling the context window, and how full it is |
| `/memory`, `/memory edit` | Instruction files in use |
| `# note` | Remember something: adds a line to an instruction file |
| `/output-style NAME` | `explanatory`, `learning`, `concise`, or your own |
| `/security-review` | Check changes for security holes |
| `/doctor` | Check your setup |
| `/vim`, `/statusline` | Vim keys; the status line |

Type `@path/to/file` (or a folder) in a message to attach it. In the browser, `/` and `@` open an autocomplete menu, ↑ in an empty box recalls your last message, an unsent draft survives a reload, and math like `$$E = mc^2$$` is typeset.

### Modes

- **Ask first** (default): every change or command waits for your OK.
- **Auto**: safe actions run on their own: reading, edits inside the project (they can be undone), tests and builds. Risky ones ask: deletes outside the project, force pushes, `sudo`, publishing, GitHub writes. Clear cases are decided by rules; anything in between goes to a small, fast model, and if it can't decide, Docks asks.
- **Plan first**: Docks researches without changing anything, may ask you multiple-choice questions, then shows a plan. Approve it, or send feedback and it revises.
- **Full auto** (`-y`): never asks. Use it when you trust the task.

If the API is overloaded or rate-limited, Docks waits and retries on its own (up to 6 times), and tells you it's doing so.

Shift+Tab cycles through the modes, in the terminal and in the browser. A settings file can pick the starting mode with `"permissions": {"defaultMode": "auto"}` (`acceptEdits`, `plan` and `bypassPermissions` work too).

### Permission rules

Rules in `settings.json` (yours in `~/.docks/` or `~/.claude/`, a project's in `.claude/`) decide what runs without asking, what always asks, and what never runs. They use Claude Code's format:

```json
{"permissions": {
  "allow": ["Bash(npm test:*)", "Bash(git status)", "Edit(src/**)", "WebFetch(domain:docs.python.org)"],
  "ask":   ["Bash(git push:*)"],
  "deny":  ["Read(./.env)", "Read(**/*.pem)", "Bash(curl:*)"]}}
```

- `Bash(npm test:*)` matches commands starting with `npm test`; `Bash(git status)` matches exactly. For `cmd1 && cmd2`, every part must be allowed, and one denied part blocks the whole command.
- `Read(...)` and `Edit(...)` take gitignore-style paths. `Edit` covers every tool that changes files; `Read` covers reading and searching.
- `mcp__server` covers all of an MCP server's tools.
- deny beats ask beats allow. Ask rules ask even in Full auto.

Answering "always" to a command remembers a narrow rule like `Bash(npm test:*)` for the session. `/allow RULE` saves one in `.claude/settings.local.json`, which is kept out of git. `-p` runs take `--allow` and `--deny` too (`--allowedTools` / `--disallowedTools` work).

A cloned project's own allow rules, start mode, status-line command and language servers could make Docks act or run programs without asking. So, like its hooks and MCP servers, they wait until you approve them once.

### Sandbox

With `docks --sandbox`, `/sandbox`, or `"sandbox": {"enabled": true}` in settings, shell commands run in a sandbox. Everything can be read, but only the project folder (and a private `/tmp`) can be written. Folders with credentials (`~/.ssh`, `~/.aws`, `~/.config/gh` and others) are hidden. It uses bubblewrap on Linux and `sandbox-exec` on macOS. Options:

```json
{"sandbox": {"enabled": true, "network": false, "allowWrite": ["~/.npm", "~/.cache/pip"],
             "excludedCommands": ["docker"], "autoAllowBashIfSandboxed": true}}
```

`network: false` cuts commands off from the internet. Dev servers started in the background keep the network so you can still preview them. In Auto mode, sandboxed commands run without asking unless they look destructive. If settings turn the sandbox on and it can't run, Docks refuses to work rather than run unprotected.

### Testing what it builds, in a real browser

With Playwright installed, Claude gets a browser tool. It opens the dev server (or an HTML file), clicks, types and presses keys, switches to a phone-size screen, and sees a screenshot after each step. Every step also reports new console errors and failed requests, so Claude finds and fixes them before telling you a page works. Screenshots show up in the browser UI's steps. On your own machine (localhost) it doesn't ask; clicking or typing on other websites asks first.

### Code intelligence

When a language server is installed (pyright, basedpyright or pylsp for Python, typescript-language-server, gopls, rust-analyzer, clangd), Claude can look up definitions, find every reference before changing something, see types, outline a file and search symbols across the project. After every edit, the server checks the file, and errors it reports go straight back to Claude. Add other servers in settings (or a plugin's `.lsp.json`):

```json
{"lspServers": {"elixir": {"command": "elixir-ls", "args": [], "extensionToLanguage": {".ex": "elixir"}}}}
```

Turn it off with `"codeIntelligence": false`.

### Parallel work in worktrees

`docks -w NAME` (also `docks web -w NAME`) works in a git worktree of its own: a separate copy of the repo in `.docks/worktrees/NAME` on branch `docks/NAME`. Run several at once for different tasks, then keep the ones you like:

```bash
docks worktree list               # each one, with its commits and uncommitted files
docks worktree merge NAME         # commits leftover changes, merges into your current branch
docks worktree remove NAME        # --force also throws away unmerged work
```

### Script mode

`docks -p "task"` runs with nobody to ask, for CI, git hooks or other programs. Anything that would need approval is refused and reported, so allow what the task needs:

```bash
docks -p "fix the lint errors" --allow Edit --allow "Bash(npm run lint:*)"
cat error.log | docks -p "why does this fail?"
docks -p "list the TODOs" --output-format json | jq -r .result
docks -p "add tests" -y --output-format stream-json     # one JSON event per line as it works
```

`text` prints only the answer. `json` prints one result object: `result`, `is_error`, `session_id`, `num_turns`, `duration_ms`, `usage`, `denied`. `stream-json` prints `init`, `text`, `tool_use`, `tool_result`, `permission_denied` and other events, then the result. The exit code is 1 if the task failed.

### Memory and instructions

- `DOCKS.md` (or `AGENTS.md` / `CLAUDE.md`) in the project root is shared with your team.
- `DOCKS.local.md` (or `CLAUDE.local.md`) is just for you, and kept out of git.
- `~/.docks/DOCKS.md` and `~/.claude/CLAUDE.md` apply to every project.
- A `DOCKS.md` in a subfolder is read the first time Docks works in that folder.
- Inside any of them, `@docs/style.md` pulls in another file.

Start a message with `#` to add a line. The terminal asks which file. In the browser, `#` goes to the project file and `##` to your local one. `/memory` lists them and `/memory edit` opens one in your editor.

`/compact` replaces the conversation with Claude's summary of it (`/compact keep the API decisions` says what to focus on). `/context` shows how full the context window is and what's using it. Very long sessions are also summarized automatically.

### Output styles

`/output-style` (or Output style in the browser's settings) changes how Docks talks to you:
- `explanatory` adds short notes on why it made its choices.
- `learning` explains as it goes and leaves small pieces for you to write, marked `TODO(human)`.
- `concise` keeps answers to a sentence or two.

Write your own in `output-styles/NAME.md` (Claude Code's format), or set a default with `"outputStyle": "explanatory"`.

### Terminal extras

- **Status line.** Above the prompt: the model, branch, mode and how full the context is. To use your own, add `{"statusLine": {"type": "command", "command": "~/status.sh"}}`; the script gets the session as JSON on stdin. `"type": "none"` hides it.
- **Notifications.** When Docks needs you, or finishes a task that took over 30 seconds, the terminal rings and shows a desktop notification (iTerm2, kitty, WezTerm, Ghostty, Windows Terminal and more). In the browser, turn on "Notify me" in settings. `"notifications": false` turns them off.
- **Keys.** `/vim` switches to vi keys. Shortcuts go in `~/.docks/keybindings.json`: `{"ctrl+g": "/commit", "alt+r": "/review"}`. Shift+Tab cycles modes.
- **`docks doctor`** checks Python, the SDK, your API key, git, the browser tool, language servers, the sandbox, settings files and MCP servers, and says how to fix what's wrong.

### In the browser

```bash
docks web                 # opens http://127.0.0.1:8788 with a one-time link
docks web -C ~/my-site    # work on a specific project
```

You get a chat where Docks' work streams in as plain-language steps ("Wrote index.html", "Ran a command"). Each change it wants to make shows an approval card, with a colored diff for edits. Beside the chat are three tabs:

- **Preview** shows the site Docks is building, refreshing after every change, in desktop or phone width.
- **Code** is a file tree and viewer.
- **GitHub** has the repo, your changes and one-click GitHub tasks.

It has an animated code background (turn it off under the gear menu; it stays still if your system asks for reduced motion), light and dark themes, and works on phones. Settings (model, effort, auto-approve, theme, MCP servers) are under the gear menu. Reloading the page restores the conversation.

The browser link contains a one-time token. The API only accepts requests that carry it, so other websites can't reach Docks. The preview is served from a separate port under a secret path, and it never serves dotfiles like `.env` or `.git`. Docks listens only on this machine unless you pass `--host`. Anyone with the link can run commands on your machine, so don't share it.

| Flag | Meaning |
|---|---|
| `-C DIR` | project directory (default: current) |
| `-m MODEL` | Claude model (default `claude-opus-5-5`, or `$DOCKS_MODEL`) |
| `-e LEVEL` | effort: `low` `medium` `high` `xhigh` `max` (default `high`) |
| `-y` | auto-approve file writes and shell commands |

In interactive mode: `/clear` starts over, `/usage` shows tokens, `/yolo` toggles auto-approve, `/exit` quits. Ctrl-C cancels the current turn.

By default Docks asks before it writes a file or runs a shell command. Answer `a` to stop asking: for a command, about that kind of command (like `npm test`); for a file tool, for the rest of the session. Reading and searching never ask.

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

### @docks in issues and pull requests

Like `@claude` and `@codex`, you can mention **@docks** right on GitHub and it does the work there:

```bash
docks install-github     # writes .github/workflows/docks.yml (or use the button in the browser's GitHub tab)
gh secret set ANTHROPIC_API_KEY
```

Then, in Settings → Actions → General, allow GitHub Actions to create pull requests, and push the workflow. After that:

- **On an issue**, comment `@docks fix this` (or label it `docks`). Docks makes the change on `docks/issue-N`, runs the tests, and opens a pull request that says `Fixes #N`. Asking again continues the same branch and updates the same PR.
- **On a pull request**, comment `@docks rename this function` or `@docks why does this fail?`. Docks pushes the changes to the PR branch, or answers or reviews if no code change is needed. On a pull request from a fork it can only answer and review.
- **Auto review:** set the repo variable `DOCKS_AUTO_REVIEW=true` to have Docks review every new pull request.

Docks replies in the thread with a summary and a link to the run. Only owners, members and collaborators can trigger it, because each run spends your API credits and can push code. One limitation comes from GitHub: pull requests opened with the built-in Actions token don't trigger other workflows (like CI) until someone pushes to them.

## Building websites and apps

Docks covers the core features of prompt-to-app builders like Lovable, Bolt and v0:

- **Templates:** in the browser, start from a landing page, React app, full-stack app (FastAPI + React), dashboard, browser game, mobile app (Expo), Chrome extension, REST API or portfolio.
- **Live running apps:** Docks starts dev servers (Vite, Next.js, Flask, FastAPI…) in the background. The Preview shows the running app as soon as it prints its URL, and you can switch between or stop running apps from the pills above it.
- **Build from an image:** attach, paste or drop a screenshot, mockup or design, and Docks builds the UI to match. In the terminal, use `docks -i design.png "build this"`.
- **Deploy:** the Deploy button publishes the project. It uses Vercel if `VERCEL_TOKEN` is set, Netlify if `NETLIFY_AUTH_TOKEN` is set, and otherwise sets up GitHub Pages.

## MCP servers

Docks connects to [MCP](https://modelcontextprotocol.io) servers, the same plug-ins Claude Code, Claude Desktop and Cursor use, and gives their tools to the agent.

```bash
docks mcp add files -- npx -y @modelcontextprotocol/server-filesystem .   # a local server
docks mcp add docs --url https://example.com/mcp --header "Authorization: Bearer \${DOCS_TOKEN}"   # a remote one
docks mcp list                                                              # status and tools
docks mcp remove files
```

Your servers live in `~/.docks/mcp.json`. A project can also ship a `.mcp.json` (the same format Claude Code uses). Because a project's servers run commands on your machine, Docks asks before starting each one, and asks again if its command changes. In the browser, approve them under the gear menu. Read-only tools run freely. Others ask for approval like any change. `${VAR}` in a config is filled in from your environment, so secrets stay out of the file.

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

## Big and long tasks

- **Long sessions keep going.** When a conversation gets long, Claude's API summarizes the earlier part on its own (server-side compaction), and Docks carries on instead of stopping at the context limit.
- **Undo anything.** Before every task, Docks snapshots the project's files. In the terminal, `/undo` puts the files back and forgets the last task (repeat to go further back). In the browser, hover any of your messages and click **Undo from here**: files go back to how they were before that message, and the message reappears in the box so you can edit and resend it. Snapshots are kept in `~/.docks/checkpoints`, never in your repo's own git, and skip ignored files and heavy folders like `node_modules`. Changes outside the project, like installed packages, databases or pushes, can't be undone.
- **Helpers in parallel.** For big jobs, Claude can hand self-contained pieces to helper agents that run at the same time, each with a fresh context and the same tools. In the browser, each helper's steps appear inside its own card, and its final report goes back to the main agent.
- **A live plan.** On multi-step tasks, Claude keeps a checklist that's pinned above the message box in the browser (and printed in the terminal), with a progress bar.

## Plugins, commands, agents, skills and hooks

Docks reads the same file layout as Claude Code, so existing plugins and `.claude/` folders work as they are. That includes commands, agents, skills, hooks, output styles, `.mcp.json` and `.lsp.json`.

```bash
docks plugin install anthropics/claude-code --plugin commit-commands   # from a git repo or marketplace
docks plugin install ./my-plugin                                       # or a local folder
docks plugin list | enable NAME | disable NAME | remove NAME
```

- **Commands**: `commands/NAME.md` becomes `/NAME`. Supports frontmatter, `$ARGUMENTS`, `$1`…`$9`, and `` !`git status` `` to inline command output (only for commands from your home folder or plugins, never from a project you just cloned). Plugin commands are `/plugin:NAME`, or just `/NAME` when no other command shares it.
- **Agents**: `agents/NAME.md` (with `name`, `description`, `tools`, `model`) defines a specialist helper Claude can delegate to. Helpers can also run **in the background** while you keep working; their report arrives when they finish.
- **Skills**: `skills/NAME/SKILL.md` is loaded only when a task needs it.
- **Hooks**: `hooks/hooks.json`, or `"hooks"` in `.claude/settings.json`, run your scripts on `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `SessionStart`, `Stop`, `SubagentStop` (a helper finished; block to send it back), `Notification` (Docks is waiting for you), `PreCompact` and `SessionEnd`. Exit code 2 (or `{"decision": "block"}`) blocks the action and tells Claude why. A project's own hooks run only after you approve them once.

Docks looks in `~/.claude`, `~/.docks`, enabled plugins, and the project's `.claude/` and `.docks/` folders.

Built-in workflows:
- `/review`: several reviewers check the changes in parallel; only findings that survive a second check are reported.
- `/feature IDEA`: explore the code, ask questions, design, build, then review.
- `/commit`, `/commit-push-pr`: a good commit message (and a PR) in one go.
- `/init`: write a `DOCKS.md` that teaches Docks your project.
- `/security-review`: trace real attack paths through your changes and report only the ones that hold up.

## Project instructions

Put a `DOCKS.md` (or `AGENTS.md` / `CLAUDE.md`) in your project root with conventions, commands, and context. Docks reads it into its system prompt. See "Memory and instructions" above for personal, local and folder files.

## How it works

```
docks/
  cli.py     argument parsing, REPL, slash commands
  agent.py   the agent loop: stream a turn, run tools, feed results back, repeat
  tools.py   bash, read_file, write_file, edit_file, glob, grep (+ input validation)
  ui.py      terminal rendering and approval prompts
  memory.py  lessons saved by the remember tool
  github.py  GitHub API + git: issues, PRs, reviews, push, clone
  action.py  the @docks bot that runs in GitHub Actions
  mcp.py     MCP client (local and remote servers)
  procs.py   background processes such as dev servers
  checkpoints.py  file snapshots for undo
  plugins.py      plugins, commands, agents, skills, hooks, output styles, settings
  permissions.py  allow / ask / deny rules
  automode.py     what Auto mode may run on its own
  sandbox.py      bubblewrap / sandbox-exec wrapping for commands
  browser.py      the Playwright browser tool
  lsp.py          language server client (code intelligence)
  worktrees.py    parallel work in git worktrees
  instructions.py DOCKS.md files, imports and # notes
  script.py       docks -p (text, json, stream-json)
  sessions.py     saved conversations
  terminal.py     status line, notifications, vim mode, keybindings
  doctor.py       docks doctor
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
