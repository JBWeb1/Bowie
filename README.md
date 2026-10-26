<p align="center"><img src="docks/web/assets/bowie.webp" width="150" alt="Bowie, the Bowers mascot"></p>

# Bowers

**Think. Create. Build. Together.** Bowers is an AI agent for building things, in your terminal or your browser. Tell it what to make, such as an app, a website, a script, an API, a game, a design or a document. It looks around your project, writes and edits files, runs commands and tests, checks its work in a real browser, and fixes what breaks until the job is done. Bowie, the mascot, keeps you company while it works.

(Bowers was called Docks. The `docks` command, `DOCKS_*` settings and the `~/.docks` folder still work.)

## Bowers models

| Model | Best for | Runs on |
|---|---|---|
| **Bowers Syntra 1** (default) | Software, automation and complex workflows | Claude Opus, high effort |
| **Bowers Aether 1** | The flagship: hard reasoning, research and creative work | Claude Fable, extra-high effort |
| **Bowers Solace 1** | Calm, clear help that explains as it goes | Claude Sonnet, medium effort |

Each Bowers model is a tuned profile on top of the newest Claude model in its family: its own instructions, its own way of working, and how hard it thinks. As Anthropic releases newer models, `bowers models update` (and a daily check in the background) moves them up. Pick one with `bowers -m aether`, `/model solace`, or the model button in the browser. You can also choose an engine directly: `opus`, `fable`, `sonnet`, `haiku`, or OpenAI's `codex` and `chatgpt` (through Bowers Router, with `OPENAI_API_KEY`).

## Install

**Windows (one step):** open PowerShell and run

```powershell
irm https://raw.githubusercontent.com/JBWeb1/Bowie/main/install.ps1 | iex
```

This installs Python and Git if needed, then Bowers. It also adds **Bowers** to the Start menu and the desktop, and opens it in its own app window. The window can also be pinned with your browser's **Install app** button. **macOS / Linux:** `curl -fsSL https://raw.githubusercontent.com/JBWeb1/Bowie/main/install.sh | sh`. Already installed? `bowers app` opens the app window, and `bowers install-app` adds the shortcuts.

From source:

```bash
pip install -e .
export ANTHROPIC_API_KEY=sk-ant-...   # get one at https://console.anthropic.com
bowers doctor                          # check that everything works
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
bowers                                   # interactive session
bowers "build a snake game in the browser"   # one-shot task
bowers -y "add tests for utils.py and make them pass"   # no approval prompts
bowers --plan "add user accounts"        # research and propose a plan first
bowers --continue                        # pick up your last conversation here
bowers --resume "todo app"               # or any saved one, by name or id
bowers sessions                          # list saved conversations
bowers -w login "add a login page"       # work in a separate git worktree (see below)
bowers -p "why does the build fail?"     # script mode: answer only, no questions (see below)
bowers --sandbox                         # commands can only write inside the project
```

Inside a session, `/help` lists everything. Highlights:

| Command | What it does |
| --- | --- |
| `/mode ask\|auto\|plan\|yolo` | How Bowers asks before changes (see below) |
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
- **Auto**: safe actions run on their own: reading, edits inside the project (they can be undone), tests and builds. Risky ones ask: deletes outside the project, force pushes, `sudo`, publishing, GitHub writes. Clear cases are decided by rules; anything in between goes to a small, fast model, and if it can't decide, Bowers asks.
- **Plan first**: Bowers researches without changing anything, may ask you multiple-choice questions, then shows a plan. Approve it, or send feedback and it revises.
- **Full auto** (`-y`): never asks. Use it when you trust the task.

If the API is overloaded or rate-limited, Bowers waits and retries on its own (up to 6 times), and tells you it's doing so.

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

A cloned project's own allow rules, start mode, status-line command and language servers could make Bowers act or run programs without asking. So, like its hooks and MCP servers, they wait until you approve them once.

### Sandbox

With `bowers --sandbox`, `/sandbox`, or `"sandbox": {"enabled": true}` in settings, shell commands run in a sandbox. Everything can be read, but only the project folder (and a private `/tmp`) can be written. Folders with credentials (`~/.ssh`, `~/.aws`, `~/.config/gh` and others) are hidden. It uses bubblewrap on Linux and `sandbox-exec` on macOS. Options:

```json
{"sandbox": {"enabled": true, "network": false, "allowWrite": ["~/.npm", "~/.cache/pip"],
             "excludedCommands": ["docker"], "autoAllowBashIfSandboxed": true}}
```

`network: false` cuts commands off from the internet. Dev servers started in the background keep the network so you can still preview them. In Auto mode, sandboxed commands run without asking unless they look destructive. If settings turn the sandbox on and it can't run, Bowers refuses to work rather than run unprotected.

### Testing what it builds, in a real browser

With Playwright installed, Claude gets a browser tool. It opens the dev server (or an HTML file), clicks, types and presses keys, switches to a phone-size screen, and sees a screenshot after each step. Every step also reports new console errors and failed requests, so Claude finds and fixes them before telling you a page works. Screenshots show up in the browser UI's steps. On your own machine (localhost) it doesn't ask; clicking or typing on other websites asks first.

### Code intelligence

When a language server is installed (pyright, basedpyright or pylsp for Python, typescript-language-server, gopls, rust-analyzer, clangd), Claude can look up definitions, find every reference before changing something, see types, outline a file and search symbols across the project. After every edit, the server checks the file, and errors it reports go straight back to Claude. Add other servers in settings (or a plugin's `.lsp.json`):

```json
{"lspServers": {"elixir": {"command": "elixir-ls", "args": [], "extensionToLanguage": {".ex": "elixir"}}}}
```

Turn it off with `"codeIntelligence": false`.

### Parallel work in worktrees

`bowers -w NAME` (also `bowers web -w NAME`) works in a git worktree of its own: a separate copy of the repo in `.docks/worktrees/NAME` on branch `docks/NAME`. Run several at once for different tasks, then keep the ones you like:

```bash
bowers worktree list               # each one, with its commits and uncommitted files
bowers worktree merge NAME         # commits leftover changes, merges into your current branch
bowers worktree remove NAME        # --force also throws away unmerged work
```

### Script mode

`bowers -p "task"` runs with nobody to ask, for CI, git hooks or other programs. Anything that would need approval is refused and reported, so allow what the task needs:

```bash
bowers -p "fix the lint errors" --allow Edit --allow "Bash(npm run lint:*)"
cat error.log | bowers -p "why does this fail?"
bowers -p "list the TODOs" --output-format json | jq -r .result
bowers -p "add tests" -y --output-format stream-json     # one JSON event per line as it works
```

`text` prints only the answer. `json` prints one result object: `result`, `is_error`, `session_id`, `num_turns`, `duration_ms`, `usage`, `denied`. `stream-json` prints `init`, `text`, `tool_use`, `tool_result`, `permission_denied` and other events, then the result. The exit code is 1 if the task failed.

### Memory and instructions

- `DOCKS.md` (or `AGENTS.md` / `CLAUDE.md`) in the project root is shared with your team.
- `DOCKS.local.md` (or `CLAUDE.local.md`) is just for you, and kept out of git.
- `~/.docks/DOCKS.md` and `~/.claude/CLAUDE.md` apply to every project.
- A `DOCKS.md` in a subfolder is read the first time Bowers works in that folder.
- Inside any of them, `@docs/style.md` pulls in another file.

Start a message with `#` to add a line. The terminal asks which file. In the browser, `#` goes to the project file and `##` to your local one. `/memory` lists them and `/memory edit` opens one in your editor.

`/compact` replaces the conversation with Claude's summary of it (`/compact keep the API decisions` says what to focus on). `/context` shows how full the context window is and what's using it. Very long sessions are also summarized automatically.

### Output styles

`/output-style` (or Output style in the browser's settings) changes how Bowers talks to you:
- `explanatory` adds short notes on why it made its choices.
- `learning` explains as it goes and leaves small pieces for you to write, marked `TODO(human)`.
- `concise` keeps answers to a sentence or two.

Write your own in `output-styles/NAME.md` (Claude Code's format), or set a default with `"outputStyle": "explanatory"`.

### Terminal extras

- **Status line.** Above the prompt: the model, branch, mode and how full the context is. To use your own, add `{"statusLine": {"type": "command", "command": "~/status.sh"}}`; the script gets the session as JSON on stdin. `"type": "none"` hides it.
- **Notifications.** When Bowers needs you, or finishes a task that took over 30 seconds, the terminal rings and shows a desktop notification (iTerm2, kitty, WezTerm, Ghostty, Windows Terminal and more). In the browser, turn on "Notify me" in settings. `"notifications": false` turns them off.
- **Keys.** `/vim` switches to vi keys. Shortcuts go in `~/.docks/keybindings.json`: `{"ctrl+g": "/commit", "alt+r": "/review"}`. Shift+Tab cycles modes.
- **`bowers doctor`** checks Python, the SDK, your API key, git, the browser tool, language servers, the sandbox, settings files and MCP servers, and says how to fix what's wrong.

### In the browser

```bash
bowers web                 # opens http://127.0.0.1:8788 with a one-time link
bowers web -C ~/my-site    # work on a specific project
```

The first time, Bowie welcomes you: tell it your name, check your connections (Claude, OpenAI, GitHub) and choose a Bowers model. Then the sidebar has:

- **Home:** a greeting, the message box, quick starts (build a website, create an image, write code, analyze data, plan a project), and your recent chats. Bowers' work streams in as plain-language steps, each change it wants to make shows an approval card (with a colored diff for edits), and a card appears when your app is live. Beside the chat are **Preview** (your site, refreshed after every change, desktop or phone width), **Code** (files), **GitHub** and **Images**.
- **Projects:** every folder you've worked in. Open one (Bowers switches without restarting) or start a new one in `~/Bowers Projects`.
- **Tasks:** each conversation's plan with its progress, what's done, and anything waiting for your approval.
- **Library:** everything you've made in this project (designs, images, websites, documents, bookmarked code), with filters and search.
- **Creation Studio:** image generator, video creator, code editor, design studio, document writer, 3D creator, music studio and presentation builder. Images use OpenAI's image model. Bowers builds the rest with code: an animated HTML video, a three.js scene, a Tone.js song, a .pptx or Word file.
- **Explore:** the Bowers models, project templates, and your commands and skills.
- **Settings:** your name, model, effort and mode, output style, GitHub account and a setup check, sandbox and permission rules, MCP servers and plugins, theme and the animated background.

Bowie's face follows what Bowers is doing: thinking, focused while it works, curious when it needs you, and excited when it's done. There are light and dark themes. On phones the bottom bar has Home, Projects, Library, Studio and More. Reloading the page restores the conversation.

The browser link contains a one-time token. The API only accepts requests that carry it, so other websites can't reach Bowers. The preview is served from a separate port under a secret path, and it never serves dotfiles like `.env` or `.git`. Bowers listens only on this machine unless you pass `--host`. Anyone with the link can run commands on your machine, so don't share it.

| Flag | Meaning |
|---|---|
| `-C DIR` | project directory (default: current) |
| `-m MODEL` | `syntra` (default), `aether`, `solace`, or an engine (or `$DOCKS_MODEL`) |
| `-e LEVEL` | effort: `low` `medium` `high` `xhigh` `max` (default: the model's own) |
| `-y` | auto-approve file writes and shell commands |

In interactive mode: `/clear` starts over, `/usage` shows tokens, `/yolo` toggles auto-approve, `/exit` quits. Ctrl-C cancels the current turn.

By default Bowers asks before it writes a file or runs a shell command. Answer `a` to stop asking: for a command, about that kind of command (like `npm test`); for a file tool, for the rest of the session. Reading and searching never ask.

## GitHub

Bowers works with GitHub the way Claude Code and Codex do. Connect your account:

```bash
bowers github login            # sign in on GitHub (needs DOCKS_GITHUB_CLIENT_ID), or paste a token; --gh uses the GitHub CLI
bowers github status           # which account is connected
bowers github repos [search]   # your repositories
bowers github branches         # this project's branches
bowers github prs [--mine]     # open pull requests with their checks; --mine: yours and ones waiting for your review
bowers github watch owner/repo#12   # get told when its checks finish, a review comes in, or it's merged
bowers context add owner/repo  # another repo Bowers can read while it works here, kept in sync (read-only)
```

The token is saved in `~/.docks/github.json`, readable only by you (`GITHUB_TOKEN` and `gh auth login` also work). Signing in through GitHub's page needs a GitHub OAuth app of your own (Settings → Developer settings → OAuth Apps, with "Enable Device Flow" ticked); put its client ID in `DOCKS_GITHUB_CLIENT_ID`. Then:

```bash
bowers clone owner/repo        # clone and start working (add --web for the browser)
bowers fix 42                  # read issue #42, fix it on a branch, run tests, open a PR
bowers review 17               # review PR #17 and post comments on the exact lines
bowers pr                      # commit current changes on a branch and open a PR
```

The agent has GitHub tools too, so you can just say "fix issue 42" or "review PR 17" in a chat. It can read issues and PRs (including diffs), open pull requests, comment, and post reviews with inline comments. Pushing, opening PRs and posting comments always ask first unless auto-approve is on. Bowers never commits to the default branch or force-pushes. Your token is sent only to GitHub. It goes to git as an environment setting, never on the command line or into `.git/config`.

In the browser, the **GitHub** tab connects your account (sign in, or paste a token), lists your repositories (use any as context with one click), shows branches (switch with a click), and tracks pull requests with their checks: this repo's, yours, and ones waiting for your review. Watch any of them to get notified. It also shows uncommitted changes (with a diff) and has one-click Fix an issue, Review a pull request and Open a pull request. In an empty folder it can clone a repo for you.

### @bowers in issues and pull requests

Like `@claude` and `@codex`, you can mention **@bowers** (or the old `@docks`) right on GitHub and it does the work there:

```bash
bowers install-github     # writes .github/workflows/docks.yml (or use the button in the browser's GitHub tab)
gh secret set ANTHROPIC_API_KEY
```

Then, in Settings → Actions → General, allow GitHub Actions to create pull requests, and push the workflow. After that:

- **On an issue**, comment `@bowers fix this` (or label it `bowers`). Bowers makes the change on `docks/issue-N`, runs the tests, and opens a pull request that says `Fixes #N`. Asking again continues the same branch and updates the same PR.
- **On a pull request**, comment `@bowers rename this function` or `@bowers why does this fail?`. Bowers pushes the changes to the PR branch, or answers or reviews if no code change is needed. On a pull request from a fork it can only answer and review.
- **Auto review:** set the repo variable `DOCKS_AUTO_REVIEW=true` to have Bowers review every new pull request.

Bowers replies in the thread with a summary and a link to the run. Only owners, members and collaborators can trigger it, because each run spends your API credits and can push code. One limitation comes from GitHub: pull requests opened with the built-in Actions token don't trigger other workflows (like CI) until someone pushes to them.

## Images

With `OPENAI_API_KEY` set, Bowers makes images with OpenAI's GPT Image models: GPT Image 2.5 Flare (fast, the default) or Sunburst (more detail, slower).

```bash
bowers image "a cozy coffee shop at dawn, watercolor" -o public/hero.png --size wide
bowers image "make the sky purple" --edit public/hero.png
bowers image "logo for a bakery" --transparent -n 3
```

Claude can make them too (`generate_image`), for example a hero image for the site it's building, and it sees the result. In the browser, the **Images** tab has style presets, sizes, quality, transparency, a gallery, editing and a full-size viewer. Images are saved in the project (`assets/generated/` unless you choose a path). Each one costs money on your OpenAI account, so Bowers asks before making one unless you've allowed it.

## Building websites and apps

Bowers covers the core features of prompt-to-app builders like Lovable, Bolt and v0:

- **Templates:** in the browser, start from a landing page, React app, full-stack app (FastAPI + React), dashboard, browser game, mobile app (Expo), Chrome extension, REST API or portfolio.
- **Live running apps:** Bowers starts dev servers (Vite, Next.js, Flask, FastAPI…) in the background. The Preview shows the running app as soon as it prints its URL, and you can switch between or stop running apps from the pills above it.
- **Build from an image:** attach, paste or drop a screenshot, mockup or design, and Bowers builds the UI to match. In the terminal, use `bowers -i design.png "build this"`.
- **Deploy:** the Deploy button publishes the project. It uses Vercel if `VERCEL_TOKEN` is set, Netlify if `NETLIFY_AUTH_TOKEN` is set, and otherwise sets up GitHub Pages.

## MCP servers

Bowers connects to [MCP](https://modelcontextprotocol.io) servers, the same plug-ins Claude Code, Claude Desktop and Cursor use, and gives their tools to the agent.

```bash
bowers mcp add files -- npx -y @modelcontextprotocol/server-filesystem .   # a local server
bowers mcp add docs --url https://example.com/mcp --header "Authorization: Bearer \${DOCS_TOKEN}"   # a remote one
bowers mcp list                                                              # status and tools
bowers mcp remove files
```

Your servers live in `~/.docks/mcp.json`. A project can also ship a `.mcp.json` (the same format Claude Code uses). Because a project's servers run commands on your machine, Bowers asks before starting each one, and asks again if its command changes. In the browser, approve them under the gear menu. Read-only tools run freely. Others ask for approval like any change. `${VAR}` in a config is filled in from your environment, so secrets stay out of the file.

### Connect apps

Bowers has a catalog of ready-made app connections: Notion, Linear, Sentry, Stripe, Supabase, Figma, Vercel, Hugging Face and GitHub's own MCP server, plus local tools (folder access, knowledge-graph memory, web fetch, SQLite, time zones). In the browser, open **Explore → Connect apps** (or **Settings → Tools & safety**) and press **Connect**. From the terminal:

```bash
bowers mcp apps              # the catalog, with what's connected
bowers mcp connect notion    # adds it, then opens your browser to sign in
bowers mcp login linear      # sign in again to an app you already added
bowers mcp logout linear     # forget the sign-in
```

Signing in uses the MCP authorization spec, which is standard OAuth. Bowers finds the app's sign-in server, registers itself, and sends you to the app's own page to approve. Bowers never sees your password. The approval comes back to a one-time address on your computer (`127.0.0.1`), and Bowers checks it with PKCE and a random state value. It also checks the issuer when the server sends one. Sign-ins are stored in `~/.docks/mcp-auth.json`, readable only by you, and refresh themselves when they expire. A server that doesn't support registration needs a client ID you create with the app, set in its config as `"oauth": {"clientId": "..."}`. The GitHub entry uses your connected GitHub account instead. Local tools need Node.js (`npx`) or [uv](https://docs.astral.sh/uv/) (`uvx`), and the page tells you when one is missing.

## Bowers Router: one endpoint for every coding tool

`bowers router` is a self-hosted gateway, similar to OmniRoute but focused on coding. Point Claude Code, Cline, Aider, Continue, OpenCode, Cursor or Bowers at it, and it sends each request to whichever AI provider is available right now.

```bash
bowers router init             # writes ~/.docks/router.json (edit routes and models here)
export ANTHROPIC_API_KEY=...  # set keys for any providers you use
export DEEPSEEK_API_KEY=...
ollama pull qwen2.5-coder     # optional: free local model with no usage limits
bowers router serve            # http://127.0.0.1:8787, dashboard at /
bowers router setup claude-code   # prints setup for your tool (also: cline, aider, continue, opencode, cursor, docks)
bowers router routes           # shows which providers each route will use right now
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

## The Bowers apps

The browser app has one section per job, each with its own page in the sidebar (Bowie's icons) and in the **Ctrl+K** command palette. It has dark and light modes: use the sun/moon button at the top.

- **Bowers Motion**: videos with sound from text or from an image (LTX-2.5 Fast or Pro, 6–20 s, up to 4K, 16:9 or 9:16), plus the photo generator, templates, and your recent creations. Videos need `LTX_API_KEY` from [ltx.io](https://ltx.io) and are saved under `assets/videos`. From the terminal: `bowers video "a fox in the snow, slow push in" --seconds 8 --pro`.
- **Bowers Forge**: the coding section. It shows recent projects and a workspace with a file tree, a code view, a terminal (PowerShell on Windows), the AI assistant and a live preview. It also has starters such as a SaaS app, a store, a banking dashboard, payments, a mobile app, a project manager, a 3D editor, an animated UI kit and a shopping agent.
- **Bowers Care**: fixes Windows, Linux and Mac problems and code errors. It shows a health dashboard (memory, disks, warnings) and lists common problems you can pick. You can also describe your own problem or paste an error. Read-only checks cover system errors (journal or Event Log), failed services, disk, network, busy programs and updates. Bowie explains what's wrong and fixes it step by step; each command asks you first. From the terminal: `bowers care` or `bowers care "wifi keeps dropping"`.
- **Labs**: more tools inspired by open-source projects you might know:
  - Trading Desk: multi-agent research, never trades
  - Math Lab: SymPy solve, differentiate, integrate and plot
  - Model Arena: two models side by side, with votes and a leaderboard
  - Emote Maker: Twitch, Discord, Slack, YouTube and Telegram sizes
  - Interior Restyler and virtual staging
  - 3D Studio: three.js, PlayCanvas-style editor, Blender scripts
  - Video Clipper: highlight clips with captions
  - Site Audit: Lighthouse and SEO
  - Local CI: GitHub Actions with `act`
  - Web Crawler: site to Markdown
  - Skill Packs: install skills from GitHub
  - Free Resources

  Most also work as commands: `/trading-research`, `/site-audit`, `/local-ci`, `/crawl`, `/video-clips`, `/explain-codebase`, `/prompt-eval`, `/scene-3d`. Math and emotes need `pip install "docks[labs]"`.
- **Bowers Aether** (choose the Aether model): a voice assistant. Talk to Bowie with the mic, or turn on hands-free and say "Hey Bowie…". It answers out loud, shows each step it takes, and gives briefings ("Brief me"). Aether learns as it works: preferences it notices are saved to your memory file, and it uses them from then on. It only shows the **Knowledge Graph**, a map of how your projects, files, memories, tools, goals, creations and history connect, plus a **code map** of which files import which.
- **Bowie's voice**: Settings → Voice. The built-in voice is free; tune its pitch and speed. Or add `ELEVENLABS_API_KEY` and pick an ElevenLabs voice. You can design one in ElevenLabs Voice Design (for example "a small, cheerful, fluffy orange mascot with a warm, playful voice").

Bowers is a set of profiles and tools on top of Claude (and optionally OpenAI) models: Aether runs on Claude Fable. It doesn't train its own model. It "learns" by keeping notes in your memory files, which you can read and edit with `/memory`.

## Observer and replay

These two features are inspired by Meta's [Muse Code](https://techcrunch.com/2026/08/05/meta-launches-muse-code-an-ai-agent-for-large-code-bases/).

**Observer.** After each task that changes something, a second, read-only check compares what Bowers *said* it did with what actually happened: every action, its result, and the git diff. It flags:

- claims nothing backs up, such as "tests pass" when no tests ran
- parts of your request that weren't done
- failed steps that were never fixed
- preferences worth saving as a note

It never changes anything itself. Press **Fix it** (or type `/fix`) to send its points back to Bowers to verify or fix, and **Save note** to keep a preference. Turn it off with `/observer off`, the switch in **Settings → Tools & safety**, or `{"observer": false}` in settings.json. It uses a fast model; pick another with `{"observerModel": "..."}`.

**Replay.** Every conversation keeps a step-by-step log in `~/.docks/sessions/<id>.events.jsonl`: your messages, replies, each action with its result and timing, what helpers did, and the observer's notes. Watch it back or export it:

```bash
bowers replay                         # the latest conversation in this project
bowers replay NAME --step             # one step at a time
bowers replay --export html -o run.html   # a standalone page with play / step controls (also md or json)
```

In the browser, open **History** and press **Replay** on any conversation for the same timeline and the export buttons. `/replay` shows the current conversation in the terminal.

## Big and long tasks

- **Long sessions keep going.** When a conversation gets long, Claude's API summarizes the earlier part on its own (server-side compaction), and Bowers carries on instead of stopping at the context limit.
- **Undo anything.** Before every task, Bowers snapshots the project's files. In the terminal, `/undo` puts the files back and forgets the last task (repeat to go further back). In the browser, hover any of your messages and click **Undo from here**: files go back to how they were before that message, and the message reappears in the box so you can edit and resend it. Snapshots are kept in `~/.docks/checkpoints`, never in your repo's own git, and skip ignored files and heavy folders like `node_modules`. Changes outside the project, like installed packages, databases or pushes, can't be undone.
- **Helpers in parallel.** For big jobs, Claude can hand self-contained pieces to helper agents that run at the same time, each with a fresh context and the same tools. In the browser, each helper's steps appear inside its own card, and its final report goes back to the main agent.
- **A live plan.** On multi-step tasks, Claude keeps a checklist that's pinned above the message box in the browser (and printed in the terminal), with a progress bar.

## Plugins, commands, agents, skills and hooks

Bowers reads the same file layout as Claude Code, so existing plugins and `.claude/` folders work as they are. That includes commands, agents, skills, hooks, output styles, `.mcp.json` and `.lsp.json`.

```bash
bowers plugin install anthropics/claude-code --plugin commit-commands   # from a git repo or marketplace
bowers plugin install ./my-plugin                                       # or a local folder
bowers plugin list | enable NAME | disable NAME | remove NAME
```

- **Commands**: `commands/NAME.md` becomes `/NAME`. Supports frontmatter, `$ARGUMENTS`, `$1`…`$9`, and `` !`git status` `` to inline command output (only for commands from your home folder or plugins, never from a project you just cloned). Plugin commands are `/plugin:NAME`, or just `/NAME` when no other command shares it.
- **Agents**: `agents/NAME.md` (with `name`, `description`, `tools`, `model`) defines a specialist helper Claude can delegate to. Helpers can also run **in the background** while you keep working; their report arrives when they finish.
- **Skills**: `skills/NAME/SKILL.md` is loaded only when a task needs it.
- **Hooks**: `hooks/hooks.json`, or `"hooks"` in `.claude/settings.json`, run your scripts on `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `SessionStart`, `Stop`, `SubagentStop` (a helper finished; block to send it back), `Notification` (Bowers is waiting for you), `PreCompact` and `SessionEnd`. Exit code 2 (or `{"decision": "block"}`) blocks the action and tells Claude why. A project's own hooks run only after you approve them once.

Bowers looks in `~/.claude`, `~/.docks`, enabled plugins, and the project's `.claude/` and `.docks/` folders.

Built-in workflows:
- `/review`: several reviewers check the changes in parallel; only findings that survive a second check are reported.
- `/feature IDEA`: explore the code, ask questions, design, build, then review.
- `/commit`, `/commit-push-pr`: a good commit message (and a PR) in one go.
- `/init`: write a `DOCKS.md` that teaches Bowers your project.
- `/security-review`: trace real attack paths through your changes and report only the ones that hold up.

## Project instructions

Put a `DOCKS.md` (or `AGENTS.md` / `CLAUDE.md`) in your project root with conventions, commands, and context. Bowers reads it into its system prompt. See "Memory and instructions" above for personal, local and folder files.

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
  script.py       bowers -p (text, json, stream-json)
  sessions.py     saved conversations
  terminal.py     status line, notifications, vim mode, keybindings
  doctor.py       bowers doctor
  router/    the gateway: config, engine (failover), translate (formats), server, cli
  web/       browser UI: server.py (API, live events, preview) and app.html
```

Each turn streams from the Claude Messages API with adaptive thinking, progress notes between tool calls, prompt caching and server-side refusal fallback. When Claude calls tools, Bowers runs them locally, sends the results back, and loops until Claude finishes.

Add a tool by adding an entry to `TOOLS` in `docks/tools.py`.

## Develop

```bash
pip install -e . pytest
pytest
```
