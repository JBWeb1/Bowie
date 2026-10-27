"""Integrations: install the open-source projects Bowers works with, on your own computer.

    bowers integrations                    the catalog, with what's installed
    bowers integrations install ID [ID…]   install (shows the steps first)
    bowers integrations install --kind plugin   every plugin and skill pack
    bowers integrations run ID             start an installed app
    bowers integrations remove ID

Each project is installed the way its own docs say, never copied into Bowers:
  plugin    Claude Code plugins, skill packs and agent libraries -> ~/.docks/plugins (Bowers loads them)
  tool      command-line tools (pip/uv, npm)
  app       apps cloned into ~/Bowers Apps/<id> and set up there (Docker or Node/Python)
  template  starter projects copied into ~/Bowers Projects as a new project
  system    programs from your OS package manager (winget, brew, apt/snap)
  library   packages added to the open project (npm)
  link      websites and reading lists (nothing to install)

Installs run commands on your computer, so each one shows its exact steps and asks first. Logs go to
~/.docks/integrations/<id>.log.
"""

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

WIN, MAC = sys.platform == "win32", sys.platform == "darwin"


def home() -> Path:
    return Path(os.environ.get("DOCKS_HOME", Path.home() / ".docks")) / "integrations"


def apps_home() -> Path:
    return Path(os.environ.get("BOWERS_APPS", Path.home() / "Bowers Apps"))


def gh(repo: str) -> str:
    return f"https://github.com/{repo}"


# How to get each prerequisite. Auto: Bowers can install it for you (after asking).
PREREQS = {
    "git": {"check": "git", "win": "winget install --id Git.Git -e", "mac": "xcode-select --install", "linux": "sudo apt install -y git", "auto_win": True},
    "node": {"check": "node", "win": "winget install --id OpenJS.NodeJS.LTS -e", "mac": "brew install node", "linux": "sudo apt install -y nodejs npm  (or use nvm)", "auto_win": True},
    "pnpm": {"check": "pnpm", "all": "npm install -g pnpm", "auto": True},
    "bun": {"check": "bun", "win": "powershell -c \"irm bun.sh/install.ps1 | iex\"", "unix": "curl -fsSL https://bun.sh/install | bash", "auto": True},
    "uv": {"check": "uv", "all": f'"{sys.executable}" -m pip install --user uv', "auto": True},
    "docker": {"check": "docker", "win": "winget install --id Docker.DockerDesktop -e  (then start Docker Desktop)",
               "mac": "brew install --cask docker  (then open Docker)", "linux": "https://docs.docker.com/engine/install/"},
    "python": {"check": "python3" if not WIN else "python", "win": "winget install --id Python.Python.3.12 -e", "mac": "brew install python@3.12", "linux": "sudo apt install -y python3 python3-venv"},
    "make": {"check": "make", "win": "winget install --id GnuWin32.Make -e", "mac": "xcode-select --install", "linux": "sudo apt install -y make"},
    "blender": {"check": "blender", "win": "winget install --id BlenderFoundation.Blender -e", "mac": "brew install --cask blender", "linux": "sudo snap install blender --classic"},
    "gpu": {"check": None, "note": "an NVIDIA GPU with enough VRAM"},
}

E = []  # the catalog


def add(id, name, kind, agent=None, repo=None, url=None, steps=(), needs=(), check=None, run=None, open_url=None,
        keys=(), license="", notes="", only=None, no_hooks=False, size=""):
    E.append({"id": id, "name": name, "kind": kind, "agent": agent, "repo": repo, "url": url or (gh(repo) if repo else ""),
              "steps": list(steps), "needs": list(needs), "check": check, "run": run, "open": open_url, "keys": list(keys),
              "license": license, "notes": notes, "only": only, "no_hooks": no_hooks, "size": size})


# ---------------------------------------------------------------- plugins, skill packs and agent libraries
add("understand-anything", "Understand Anything", "plugin", "codebase-cartographer", "Egonex-AI/Understand-Anything", license="MIT",
    notes="Builds an interactive knowledge graph of a codebase (/understand). Its hooks (which keep the graph fresh) stay off until you turn them on.")
add("claude-seo", "Claude SEO", "plugin", "growth-marketer", "AgriciDaniel/claude-seo", license="MIT", notes="35 SEO skills and 19 SEO agents.")
add("hallmark", "Hallmark", "plugin", "ui-designer", "Nutlope/hallmark", license="MIT", notes="Design skill with 48 themes that avoids generic AI-looking pages.")
add("ponytail", "Ponytail", "plugin", "lean-coder", "DietrichGebert/ponytail", license="MIT", notes="Write only the code a task needs; /ponytail-review, /ponytail-audit.")
add("superpowers", "Superpowers", "plugin", "tdd-engineer", "obra/superpowers", license="MIT", notes="TDD, debugging, brainstorming and planning skills.")
add("ui-ux-pro-max", "UI/UX Pro Max", "plugin", "ui-designer", "nextlevelbuilder/ui-ux-pro-max-skill", license="MIT", notes="Design intelligence: styles, palettes, font pairings, UX rules.")
add("ruflo", "Ruflo (core, swarm, workflows, goals)", "plugin", "workflow-architect", "ruvnet/ruflo", license="MIT",
    only=["ruflo-core", "ruflo-swarm", "ruflo-workflows", "ruflo-goals"], no_hooks=True,
    notes="Agent swarm and workflow skills. Installed without Ruflo's hooks, which would run on every command and edit; the full harness is `npm i -g ruflo`.")
add("knowledge-work-plugins", "Knowledge Work Plugins", "plugin", None, "anthropics/knowledge-work-plugins", license="Apache-2.0",
    notes="22 plugins: data, design, engineering, finance, legal, marketing, product, sales, support and more.")
add("commerce-agents", "Commerce Agents", "plugin", "commerce-builder", "anthropics/commerce-agents", license="Apache-2.0")
add("lemo-opuscar", "Lemo Opuscar film styles", "plugin", "launch-film-director", "lemomo-ai/lemo-opuscar", license="MIT", notes="59 film styles made in code.")
add("onetake", "onetake", "plugin", "launch-film-director", "feitangyuan/onetake", notes="Launch films as one continuous motion-graphics take.")
add("hyperframes-skills", "HyperFrames skills", "plugin", "launch-film-director", "heygen-com/hyperframes", license="Apache-2.0",
    notes="HeyGen's video-making skills: story and storylines, launch films, explainers, captions, 450 ready-made blocks, media and sound. "
          "Pair with the HyperFrames CLI to render.")
add("remotion-skills", "Remotion skills", "plugin", "video-producer", "remotion-dev/skills",
    notes="Best practices for making videos in React with Remotion.")
add("agency-agents", "The Agency (agents)", "plugin", None, "msitarzewski/agency-agents", license="MIT", notes="Hundreds of specialist agent roles across engineering, design, marketing, testing, product and more.")
add("emote-forge", "Emote Forge", "plugin", "emote-artist", "holy-templar/emote-forge", license="GPL-3.0")
add("minimax-h3", "MiniMax H3 skills", "plugin", "video-producer", "MiniMax-AI/MiniMax-H3", keys=["MINIMAX_API_KEY"], notes="Prompt-writing and generation skills for MiniMax H3 video (hosted API).")
add("rea", "REA reverse-engineering skills", "plugin", "reverse-engineer", "morluto/rea", license="MIT", notes="Only for software you own or are allowed to test.")
add("autoclip-skills", "AutoClip skills", "plugin", "video-producer", "zhouxiaoka/autoclip", license="MIT")
add("awesome-claude-skills", "Awesome Claude Skills (pick skills)", "collection", None, "ComposioHQ/awesome-claude-skills",
    notes="Over 800 skills: browse and install the ones you want.")

# ---------------------------------------------------------------- command-line tools
PY = f'"{sys.executable}" -m pip install --user --upgrade'
add("graphify", "Graphify", "tool", "codebase-cartographer", "Graphify-Labs/graphify", license="Apache-2.0", check="graphify",
    steps=[{"uv": "graphifyy", "pip": "graphifyy"}], notes="Codebase knowledge graphs (`graphify install --project`).")
add("tradingagents", "TradingAgents", "tool", "trading-analyst", "TauricResearch/TradingAgents", license="Apache-2.0", check="tradingagents",
    steps=[{"uv": "git+https://github.com/TauricResearch/TradingAgents", "pip": "git+https://github.com/TauricResearch/TradingAgents"}],
    keys=["OPENAI_API_KEY or another provider"], notes="Multi-agent trading research CLI. Research only.")
add("litellm", "LiteLLM proxy", "tool", "model-router", "BerriAI/litellm", license="MIT", check="litellm", steps=[{"uv": "litellm[proxy]", "pip": "litellm[proxy]"}])
add("omniroute", "OmniRoute", "tool", "model-router", "cheaper-inference/OmniRoute", license="MIT", check="omniroute", needs=["node"],
    steps=["npm install -g omniroute"], run="omniroute", open_url="http://localhost:20128", notes="Self-hosted AI gateway with fallbacks and a dashboard.")
add("promptfoo", "promptfoo", "tool", "prompt-evaluator", "promptfoo/promptfoo", license="MIT", check="promptfoo", needs=["node"], steps=["npm install -g promptfoo"])
add("lighthouse", "Lighthouse", "tool", "performance-auditor", "GoogleChrome/lighthouse", license="Apache-2.0", check="lighthouse", needs=["node"], steps=["npm install -g lighthouse"])
add("clinic", "Clinic.js", "tool", "performance-auditor", "clinicjs/node-clinic", license="MIT", check="clinic", needs=["node"], steps=["npm install -g clinic"])
add("firecrawl", "Firecrawl CLI and SDK", "tool", "rag-engineer", "firecrawl/firecrawl", license="AGPL-3.0", check="firecrawl", needs=["node"],
    steps=["npm install -g firecrawl-cli", f"{PY} firecrawl"], keys=["FIRECRAWL_API_KEY"], notes="Hosted API by default; self-hosting is in its SELF_HOST.md.")
add("langgraph", "LangGraph", "tool", "workflow-architect", "langchain-ai/langgraph", license="MIT", steps=[f"{PY} langgraph"], check="py:langgraph")
add("hyperframes", "HyperFrames CLI", "tool", "launch-film-director", "heygen-com/hyperframes", license="Apache-2.0", check="hyperframes", needs=["node"],
    steps=["npm install -g hyperframes", "hyperframes browser ensure"],
    notes="Write HTML, render MP4: frame-exact videos from code, with a live preview studio (hyperframes preview, render, check). Needs Node 22+ and FFmpeg.")
add("sympy", "SymPy", "tool", "math-tutor", "sympy/sympy", license="BSD", steps=[f"{PY} sympy"], check="py:sympy")
add("kokoro-voice", "Kokoro voice", "tool", None, "thewh1teagle/kokoro-onnx", license="Apache-2.0 (model by hexgrad)", size="115 MB",
    check="call:docks.voice:local_available",
    steps=[{"py": "kokoro-onnx", "module": "kokoro_onnx"}, {"call": "docks.voice:install_local", "say": "download the Kokoro-82M model and voices"}],
    notes="Gives Bowie a natural voice that runs on this computer: free, offline and private. Pick it in Settings > Voice.")
add("faster-whisper", "faster-whisper", "tool", None, "SYSTRAN/faster-whisper", license="MIT", check="py:faster_whisper",
    steps=[{"py": "faster-whisper", "module": "faster_whisper"}],
    notes="Speech recognition on this computer, so talking to Aether works in every browser (Firefox, Safari) and offline. "
          "The first use downloads a small Whisper model (about 150 MB).")
add("openhands", "OpenHands", "tool", "autonomous-engineer", "All-Hands-AI/OpenHands", license="MIT", check="agent-canvas", needs=["node"],
    steps=["npm install -g @openhands/agent-canvas"], run="agent-canvas", open_url="http://localhost:8000")
add("hermes", "Hermes Agent", "tool", "autonomous-engineer", "NousResearch/hermes-agent", license="MIT", check="hermes",
    steps=[{"unix": "curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash",
            "win": "wsl -- bash -c \"curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash\""}],
    run="hermes", notes="Runs its official install script. On Windows it installs inside WSL.")
add("blade", "BLADE desktop agent", "tool", "autonomous-engineer", "sb-arnav/BLADE", check="blade",
    steps=[{"unix": "curl -sSL slayerblade.in/install | sh", "win": "iwr -useb slayerblade.in/install.ps1 | iex"}], notes="Runs BLADE's official install script.")

# ---------------------------------------------------------------- system programs
add("act", "act (GitHub Actions locally)", "system", "ci-runner", "nektos/act", license="MIT", check="act", needs=["docker"],
    steps=[{"win": "winget install --id nektos.act -e", "mac": "brew install act",
            "linux": "curl -fsSL https://raw.githubusercontent.com/nektos/act/master/install.sh | bash -s -- -b ~/.local/bin"}])
add("blender", "Blender", "system", "game-3d-builder", "blender/blender", license="GPL", check="blender",
    steps=[{"win": "winget install --id BlenderFoundation.Blender -e", "mac": "brew install --cask blender", "linux": "sudo snap install blender --classic"}])

# ---------------------------------------------------------------- apps (cloned into ~/Bowers Apps and set up there)
add("mirofish", "MiroFish", "app", "scenario-simulator", "666ghj/MiroFish", license="AGPL-3.0", needs=["git", "docker"],
    steps=[{"env": ".env.example"}, "docker compose up -d"], run="docker compose up -d", open_url="http://localhost:3000", keys=["LLM API key in .env"])
add("ragflow", "RAGFlow", "app", "rag-engineer", "infiniflow/ragflow", license="Apache-2.0", needs=["git", "docker"],
    steps=["docker compose -f docker/docker-compose.yml up -d"], run="docker compose -f docker/docker-compose.yml up -d", open_url="http://localhost",
    notes="Needs ~16 GB RAM. With Elasticsearch on Linux: sudo sysctl -w vm.max_map_count=262144.", size="large")
add("huly", "Huly", "app", "project-ops", "hcengineering/huly-selfhost", license="EPL-2.0", needs=["git", "docker"],
    steps=[{"unix": "./setup.sh --quick", "win": "wsl -- ./setup.sh --quick"}], run="docker compose up -d", open_url="http://localhost:8087")
add("doable", "Doable", "app", "project-ops", "doable-me/doable", license="MIT", needs=["git", "docker"],
    steps=[{"unix": "./deployment/docker/setup.sh", "win": ".\\deployment\\docker\\setup.ps1"}], run="docker compose -f deployment/docker/docker-compose.yml up -d")
add("hyperswitch", "Hyperswitch", "app", "commerce-builder", "juspay/hyperswitch", license="Apache-2.0", needs=["git", "docker"],
    steps=[{"unix": "scripts/setup.sh", "win": "wsl -- scripts/setup.sh"}], notes="Open-source payments switch (test mode).", size="large")
add("quantdinger", "QuantDinger", "app", "trading-analyst", "OpenByteInc/QuantDinger", license="Apache-2.0", needs=["git", "docker"],
    steps=[{"env": ".env.example"}, "docker compose up -d --build"], run="docker compose up -d", notes="Quant research platform. Research only.")
add("arcreel", "ArcReel", "app", "video-producer", "ArcReel/ArcReel", license="AGPL-3.0", needs=["git", "docker"],
    steps=[{"cd": "deploy"}, {"env": ".env.example"}, "docker compose up -d"], run="docker compose up -d", keys=["video/image model keys in deploy/.env"])
add("autoclip", "AutoClip", "app", "video-producer", "zhouxiaoka/autoclip", license="MIT", needs=["git", "docker"],
    steps=["docker compose up -d --build"], run="docker compose up -d")
add("openmontage", "OpenMontage", "app", "video-producer", "calesthio/OpenMontage", license="AGPL-3.0", needs=["git", "python", "make"],
    steps=["make setup", {"plugin": "."}], notes="Its 140 production skills are added to Bowers too.")
add("openhouse-3d", "OpenHouse 3D", "app", "property-visualizer", "yunfanye/openhouse-3d", license="MIT", needs=["git", "python"],
    steps=[{"venv": True}, {"pip": "-e ."}], notes="Rebuilds a house in 3D from listing photos and renders a walkthrough with Blender (install the Blender integration to render).")
add("realestateos", "RealEstateOS", "app", "property-visualizer", "engrtitooo/RealEstateOS", license="MIT", needs=["git", "node"],
    steps=["npm install"], run="npm run dev", open_url="http://localhost:3000", keys=["GOOGLE_API_KEY"])
add("ai-real-estate-stager", "AI Real Estate Stager", "app", "property-visualizer", "SamurAIGPT/ai-real-estate-stager", needs=["git", "node"],
    steps=["npm install", "npx prisma generate", "npx prisma db push"], run="npm run dev", open_url="http://localhost:3000")
add("spaceai-interior", "SpaceAI Interior Studio", "app", "property-visualizer", "negineeraj331/spaceai-interior-studio", needs=["git", "node"],
    steps=["npm install"], run="npm run dev", open_url="http://localhost:3000")
add("ai-interior-restyler", "AI Interior Restyler", "app", "property-visualizer", "anton-karlovskiy/ai-interior-restyler", needs=["git", "node", "pnpm"],
    steps=["pnpm install"], run="pnpm dev", open_url="http://localhost:3000", keys=["GEMINI_API_KEY"])
add("roomsmith", "Roomsmith", "link", "property-visualizer", url="https://rumeasiyan.github.io/roomsmith/")
add("gods-eye-view", "God's Eye View", "app", "geo-visualizer", "uhrichsam4/gods-eye-view", license="MIT", needs=["git", "node"],
    steps=["npm install"], run="npm run dev -- --host localhost --port 4173", open_url="http://localhost:4173")
add("three-editor", "three-editor", "app", "game-3d-builder", "z2586300277/three-editor", license="MulanPSL-2.0", needs=["git", "node"],
    steps=["npm install"], run="npm run dev")
add("stemstudio", "StemStudio Engine", "app", "game-3d-builder", "Stem-Studio/Engine", license="MIT", needs=["git", "bun"],
    steps=["git submodule update --init --recursive", "bun install"], run="bun run dev")
add("playcanvas", "PlayCanvas engine", "library", "game-3d-builder", "playcanvas/engine", license="MIT", steps=["npm install playcanvas"])
add("vibra-code", "Vibra Code", "app", "mobile-app-builder", "sa4hnd/vibra-code", license="AGPL-3.0", needs=["git", "node"],
    steps=["npm install"], run="npm run dev", open_url="http://localhost:3000", keys=["E2B, Convex and model keys (see its README)"])
add("nativebot", "NativeBot", "link", "mobile-app-builder", url="https://nativebot.vercel.app/")
add("interpreter-workstation", "Interpreter Workstation", "app", "autonomous-engineer", "openinterpreter/interpreter-workstation", needs=["git", "node", "pnpm"],
    steps=["pnpm install", "pnpm run build"], run="pnpm start")
add("emojimaker", "Emoji Maker", "app", "emote-artist", "CodeForgeX/emojimaker", license="MIT", needs=["git", "node", "pnpm"],
    steps=["pnpm install"], run="pnpm dev")
add("emoteresizer", "Emote Resizer", "library", "emote-artist", "KatherineGuoGuo/emoteresizer-open", license="MIT", steps=["npm install emoteresizer-open"])
add("soup", "Soup (fine-tuning)", "app", "local-model-engineer", "MakazhanAlpamys/Soup", license="Apache-2.0", needs=["git", "python"],
    steps=[{"venv": True}, {"pip": "-e ."}], notes="Fine-tune LLMs from one YAML. Training needs a GPU; the Docker image is ghcr.io/makazhanalpamys/soup.")
add("edge0", "Edge0", "app", "local-model-engineer", "Edge0-AI/Edge0", license="Apache-2.0", needs=["git", "python"],
    steps=[{"cd": "python"}, {"venv": True}, {"pip": "-e .[fetch]"}], notes="Runs big MoE models from SSD. Models download separately (the 35B is about 23 GB).", size="large")
add("skyreels-v2", "SkyReels V2", "app", "video-producer", "SkyworkAI/SkyReels-V2", needs=["git", "python", "gpu"],
    steps=[{"venv": True}, {"pip": "-r requirements.txt"}], notes="Local long-video model. Needs an NVIDIA GPU (about 15 GB VRAM for 540P with the 1.3B model).", size="large")

# ---------------------------------------------------------------- starter templates (become a new project)
add("saas-starter", "Next.js SaaS Starter", "template", "commerce-builder", "nextjs/saas-starter", license="MIT", needs=["git", "node", "pnpm"],
    steps=["pnpm install"], run="pnpm dev", notes="Then: pnpm db:setup, pnpm db:migrate, pnpm db:seed (needs Postgres and Stripe test keys).")
add("yournextstore", "Your Next Store", "template", "commerce-builder", "yournextstore/yournextstore", license="MIT", needs=["git", "bun"],
    steps=["bun install", {"env": ".env.example", "to": ".env.local"}], run="bun dev", keys=["YNS_API_KEY"])
add("banking", "Banking app", "template", "commerce-builder", "adrianhajdin/banking", license="MIT", needs=["git", "node"],
    steps=["npm install"], run="npm run dev", keys=["Appwrite, Plaid and Dwolla sandbox keys"])
add("claude-animation-base", "Claude Animation Base", "template", "launch-film-director", "JohnHeibel/ClaudeAnimationBase", license="MIT", needs=["git", "node"],
    steps=["npm install"], run="node render.mjs --clip --out=out/video.mp4", notes="Hand-painted cartoon starter (p5.js); render to MP4.")
add("remotion", "Remotion starter", "template", "video-producer", "remotion-dev/template-helloworld", needs=["git", "node"],
    url="https://github.com/remotion-dev/template-helloworld", steps=["npm install"], run="npx remotion studio", open_url="http://localhost:3000",
    license="Remotion License (free for individuals and companies of up to 3 people; larger companies need a company license)",
    notes="Make videos in React: a new project with Remotion Studio. Render with `npx remotion render`. Source: github.com/remotion-dev/remotion.")

# ---------------------------------------------------------------- libraries for the open project
add("jsxgraph", "JSXGraph", "library", "math-tutor", "jsxgraph/jsxgraph", steps=["npm install jsxgraph"])
add("sandcastle", "Sandcastle", "library", "autonomous-engineer", "mattpocock/sandcastle", license="MIT", needs=["node", "docker"],
    steps=["npm install --save-dev @ai-hero/sandcastle", "npx @ai-hero/sandcastle init --agent claude-code --sandbox docker --template simple-loop --issue-tracker custom --install-template-deps false --build-image false"],
    notes="Runs AI coding agents (Claude Code, Codex and others) in isolated Docker or Podman sandboxes, each on its own branch, then merges "
          "their commits back. Good for several agents working in parallel. Then: npx @ai-hero/sandcastle docker build-image, edit .sandcastle/main.mts, "
          "and run it with npx tsx .sandcastle/main.mts.")
add("nerdamer", "nerdamer", "library", "math-tutor", "jiggzson/nerdamer", license="MIT", steps=["npm install nerdamer"])
add("react-bits", "React Bits", "link", "ui-designer", "DavidHDev/react-bits", license="MIT", notes="Add components per project with the shadcn CLI: the ui-designer agent does it for you.")
add("magicui", "Magic UI", "link", "ui-designer", "magicuidesign/magicui", license="MIT", notes="Add components with: npx shadcn@latest add @magicui/<component>.")

# ---------------------------------------------------------------- reading lists and sites
add("awesome-remote-mcp-servers", "Awesome Remote MCP Servers", "link", None, "ovladon/awesome-remote-mcp-servers", license="CC0",
    notes="All 141 servers from this list are built into Explore > Connect apps (search them there), next to the featured apps.")
for id_, name, repo in [("free-for-dev", "free-for-dev", "ripienaar/free-for-dev"), ("awesome-selfhosted", "awesome-selfhosted", "awesome-selfhosted/awesome-selfhosted"),
                        ("free-programming-books", "free-programming-books", "EbookFoundation/free-programming-books")]:
    add(id_, name, "link", "learning-guide", repo)
add("arena", "LMArena", "link", "prompt-evaluator", url="https://arena.ai/", notes="Bowers' own Model Arena is in Labs.")

NOT_INSTALLED = {"system_prompts_leaks": "Leaked copies of other companies' private system prompts; Bowers doesn't use them."}


# ---------------------------------------------------------------- status

def find(id_: str) -> dict | None:
    return next((e for e in E if e["id"] == id_), None)


def app_dir(e: dict) -> Path:
    return apps_home() / e["id"]


def _which(cmd: str) -> bool:
    if shutil.which(cmd):
        return True
    extra = [Path.home() / ".local" / "bin", Path.home() / ".bun" / "bin", Path.home() / ".cargo" / "bin"]
    return any((d / cmd).exists() or (d / (cmd + ".exe")).exists() for d in extra)


def _state() -> dict:
    try:
        return json.loads((home() / "state.json").read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(data: dict) -> None:
    home().mkdir(parents=True, exist_ok=True)
    (home() / "state.json").write_text(json.dumps(data, indent=2))


def status(e: dict) -> str:
    """installed | not-installed | link"""
    if e["kind"] == "link":
        return "link"
    st = _state().get(e["id"], {})
    if e["kind"] in ("plugin", "collection"):
        from .plugins import plugins_dir
        names = st.get("plugins") or []
        return "installed" if names and all((plugins_dir() / n).is_dir() for n in names) else "not-installed"
    if e["kind"] in ("app",):
        return "installed" if (app_dir(e) / ".bowers-installed").is_file() else "not-installed"
    if e["kind"] == "template":
        return "installed" if st.get("project") and Path(st["project"]).is_dir() else "not-installed"
    if e["kind"] == "library":
        return "installed" if st.get("done") else "not-installed"
    check = e.get("check")
    if check and check.startswith("call:"):  # a Bowers function that says whether it's ready
        import importlib
        mod, _, fn = check[5:].partition(":")
        return "installed" if getattr(importlib.import_module(mod), fn)() else "not-installed"
    if check and check.startswith("py:"):
        import importlib.util
        return "installed" if importlib.util.find_spec(check[3:]) else "not-installed"
    if check:
        return "installed" if _which(check) else "not-installed"
    return "installed" if st.get("done") else "not-installed"


def missing_prereqs(e: dict) -> list[dict]:
    out = []
    for need in e["needs"]:
        p = PREREQS.get(need)
        if not p or not p.get("check"):
            continue
        if not _which(p["check"]):
            how = p.get("all") or (p.get("win") if WIN else p.get("mac") if MAC else p.get("linux")) or p.get("unix", "")
            if not WIN and "unix" in p:
                how = p["unix"]
            out.append({"name": need, "how": how, "auto": bool(p.get("auto") or (WIN and p.get("auto_win")))})
    return out


def listing() -> list[dict]:
    rows = []
    for e in E:
        rows.append({k: e[k] for k in ("id", "name", "kind", "agent", "url", "license", "notes", "keys", "size", "open")} |
                    {"status": status(e), "missing": missing_prereqs(e), "plan": plan(e), "runnable": bool(e["run"]),
                     "hooks_held": _state().get(e["id"], {}).get("hooks_held", [])})
    return rows


# ---------------------------------------------------------------- installing

def _pick(step: dict):
    """The command for this OS from a {'win':…, 'mac':…, 'linux':…, 'unix':…} step."""
    if WIN:
        return step.get("win")
    return step.get("mac" if MAC else "linux") or step.get("unix")


def plan(e: dict) -> list[str]:
    """Human-readable steps (shown before installing)."""
    lines = []
    if e["kind"] in ("plugin", "collection"):
        lines.append(f"download {e['url']} and add its plugins/skills/agents to Bowers" + (" (without hooks)" if e["no_hooks"] else ""))
        return lines
    if e["kind"] == "link":
        return [f"open {e['url']}"]
    if e["kind"] in ("app", "template"):
        where = app_dir(e) if e["kind"] == "app" else "a new project in ~/Bowers Projects"
        lines.append(f"git clone --depth 1 {e['url']}  →  {where}")
    if e["kind"] == "library":
        lines.append("in the open project:")
    for step in e["steps"]:
        if isinstance(step, str):
            lines.append(step)
        elif "uv" in step:
            lines.append(f"uv tool install {step['uv']}" if _which("uv") else f"pip install --user {step['pip']}")
        elif "venv" in step:
            lines.append("python -m venv .venv")
        elif "pip" in step:
            lines.append(f".venv python -m pip install {step['pip']}")
        elif "env" in step:
            lines.append(f"copy {step['env']} to {step.get('to', '.env')} (if missing; add your keys there)")
        elif "cd" in step:
            lines.append(f"cd {step['cd']}")
        elif "plugin" in step:
            lines.append("add its skills to Bowers")
        elif "py" in step:
            lines.append(f"pip install --user {step['py']}")
        elif "call" in step:
            lines.append(step.get("say") or step["call"])
        else:
            cmd = _pick(step)
            lines.append(cmd or "(not available on this OS)")
    if any(re.search(r"(curl|iwr|irm)\b.*\|\s*(sh|bash|iex)\b", line) for line in lines):
        lines.append("⚠ this downloads and runs the project's own install script from its website")
    return lines


class InstallError(Exception):
    pass


def _run(cmd, cwd: Path, log) -> None:
    from .care import shell_argv
    log(f"$ {cmd}")
    argv = cmd if isinstance(cmd, list) else (shell_argv(cmd) or cmd)
    proc = subprocess.Popen(argv, cwd=cwd, shell=isinstance(argv, str), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, errors="replace", env={**os.environ, "CI": "1", "npm_config_yes": "true"})
    for line in proc.stdout:
        log(line.rstrip())
    if proc.wait() != 0:
        raise InstallError(f"`{cmd if isinstance(cmd, str) else ' '.join(cmd)}` failed (exit {proc.returncode})")


def _venv_python(folder: Path) -> Path:
    return folder / ".venv" / ("Scripts/python.exe" if WIN else "bin/python")


def install(id_: str, log=print, install_prereqs: bool = False, project: Path | None = None, skills: list | None = None) -> dict:
    """Install one integration. log(text) hears progress. Returns its state entry."""
    from . import plugins
    e = find(id_)
    if e is None:
        raise InstallError(f"no integration called {id_!r} (see bowers integrations)")
    if e["kind"] == "link":
        return {"url": e["url"]}
    missing = missing_prereqs(e)
    for m in missing:
        if install_prereqs and m["auto"]:
            log(f"installing {m['name']}…")
            _run(m["how"], Path.home(), log)
        else:
            raise InstallError(f"{e['name']} needs {m['name']} first: {m['how']}")
    home().mkdir(parents=True, exist_ok=True)
    state = _state()
    entry = {"installed": time.time()}
    if e["kind"] in ("plugin", "collection"):
        if e["kind"] == "collection" and not skills:
            raise InstallError("pick which skills to install from this collection")
        log(f"downloading {e['repo']}…")
        if e["kind"] == "collection":
            names = install_from_collection(e, skills, log)
        else:
            names = plugins.install(e["repo"], e["only"])
        held = []
        for n in names:  # third-party hooks run code on every action: keep them off until you turn them on
            if _hold_hooks(plugins.plugins_dir() / n, delete=e["no_hooks"]):
                held.append(n)
        entry["plugins"] = names
        entry["hooks_held"] = [] if e["no_hooks"] else held
        if held and not e["no_hooks"]:
            log(f"its hooks are off until you turn them on: bowers integrations enable-hooks {e['id']}")
        log("added to Bowers: " + ", ".join(names))
    elif e["kind"] in ("app", "template"):
        if e["kind"] == "app":
            dest = app_dir(e)
        else:
            from .web import library
            dest = library.projects_home() / e["name"]
            n = 2
            while dest.exists():
                dest = library.projects_home() / f"{e['name']} {n}"
                n += 1
        if not (dest / ".git").is_dir():
            dest.parent.mkdir(parents=True, exist_ok=True)
            src = e["url"] + ".git" if e["url"].startswith("https://github.com/") else e["url"]
            _run(["git", "clone", "--depth", "1", src, str(dest)], dest.parent, log)
        else:
            _run(["git", "-C", str(dest), "pull", "--ff-only"], dest, log)
        cwd = dest
        for step in e["steps"]:
            if isinstance(step, str):
                _run(step, cwd, log)
            elif "cd" in step:
                cwd = cwd / step["cd"]
            elif "venv" in step:
                if not _venv_python(cwd).exists():
                    _run([sys.executable, "-m", "venv", ".venv"], cwd, log)
            elif "pip" in step:
                _run([str(_venv_python(cwd)), "-m", "pip", "install", *step["pip"].split()], cwd, log)
            elif "env" in step:
                src, to = cwd / step["env"], cwd / step.get("to", ".env")
                if src.is_file() and not to.exists():
                    shutil.copy(src, to)
                    log(f"made {to.name}: add your keys there")
            elif "plugin" in step:
                entry["plugins"] = plugins.install(str(cwd / step["plugin"]))
                log("added to Bowers: " + ", ".join(entry["plugins"]))
            else:
                cmd = _pick(step)
                if not cmd:
                    raise InstallError(f"{e['name']} has no install step for {platform.system()}")
                _run(cmd, cwd, log)
        if e["kind"] == "app":
            (dest / ".bowers-installed").write_text(time.strftime("%Y-%m-%d %H:%M"))
            entry["path"] = str(dest)
        else:
            subprocess.run(["git", "-C", str(dest), "remote", "rename", "origin", "template"], capture_output=True)
            entry["project"] = str(dest)
            log(f"new project: {dest}")
    elif e["kind"] == "library":
        if project is None:
            raise InstallError("open a project first: libraries are added to the open project")
        for step in e["steps"]:
            _run(step if isinstance(step, str) else _pick(step), project, log)
        entry["done"] = True
        entry["project"] = str(project)
    else:  # tool, system
        for step in e["steps"]:
            if isinstance(step, str):
                _run(step, Path.home(), log)
            elif "py" in step:  # a Python package Bowers itself imports
                import importlib.util
                if importlib.util.find_spec(step["module"]):
                    log(f"{step['py']} is already available")
                elif getattr(sys, "frozen", False):
                    raise InstallError(f"this build of Bowers doesn't include {step['py']}; install Bowers with pip to add it")
                else:
                    _run([sys.executable, "-m", "pip", "install", "--user", "--upgrade", step["py"]], Path.home(), log)
                    importlib.invalidate_caches()
            elif "call" in step:  # a function in Bowers, e.g. downloading model files
                import importlib
                mod, _, fn = step["call"].partition(":")
                try:
                    getattr(importlib.import_module(mod), fn)(log)
                except Exception as err:
                    raise InstallError(f"couldn't {step.get('say', fn)}: {err}")
            elif "uv" in step:
                if _which("uv"):
                    _run(["uv", "tool", "install", "--force", step["uv"]], Path.home(), log)
                else:
                    _run([sys.executable, "-m", "pip", "install", "--user", "--upgrade", step["pip"]], Path.home(), log)
            else:
                cmd = _pick(step)
                if not cmd:
                    raise InstallError(f"{e['name']} has no install step for {platform.system()}")
                _run(cmd, Path.home(), log)
        entry["done"] = True
    state[e["id"]] = entry
    _save_state(state)
    log(f"✓ {e['name']} is installed")
    return entry


def _hold_hooks(folder: Path, delete: bool = False) -> bool:
    """Switch off a plugin's hooks (moved aside, or deleted). True if it had any."""
    had = False
    hooks = folder / "hooks"
    if (hooks / "hooks.json").is_file():
        had = True
        if delete:
            shutil.rmtree(hooks)
        else:
            (hooks / "hooks.json").rename(hooks / "hooks.json.off")
    manifest = folder / ".claude-plugin" / "plugin.json"
    try:
        data = json.loads(manifest.read_text())
        if "hooks" in data:
            had = True
            value = data.pop("hooks")
            if not delete:
                data["hooks.off"] = value
            manifest.write_text(json.dumps(data, indent=2))
    except (OSError, json.JSONDecodeError):
        pass
    return had


def held_hooks(id_: str) -> list[dict]:
    """The hook commands an integration's plugins would run, for review before turning them on."""
    from .plugins import plugins_dir
    out = []
    for n in _state().get(id_, {}).get("hooks_held", []):
        f = plugins_dir() / n / "hooks" / "hooks.json.off"
        try:
            spec = json.loads(f.read_text()).get("hooks", {})
        except (OSError, json.JSONDecodeError):
            spec = {}
        try:
            spec = {**spec, **json.loads((plugins_dir() / n / ".claude-plugin" / "plugin.json").read_text()).get("hooks.off", {})}
        except (OSError, json.JSONDecodeError, TypeError):
            pass
        for event, groups in (spec.items() if isinstance(spec, dict) else []):
            for g in groups if isinstance(groups, list) else []:
                for h in g.get("hooks", []) if isinstance(g, dict) else []:
                    out.append({"plugin": n, "event": event, "matcher": g.get("matcher", ""), "command": h.get("command", "")[:300]})
    return out


def held_hooks_for(names: list[str]) -> list[dict]:
    """Like held_hooks, for plugins installed outside the catalog (Labs > Skill Packs)."""
    state = _state()
    state["custom"] = {"hooks_held": names}
    _save_state(state)
    return held_hooks("custom")


def enable_hooks(id_: str) -> list[str]:
    from .plugins import plugins_dir
    state = _state()
    names = state.get(id_, {}).get("hooks_held", [])
    for n in names:
        off = plugins_dir() / n / "hooks" / "hooks.json.off"
        if off.is_file():
            off.rename(off.with_name("hooks.json"))
        manifest = plugins_dir() / n / ".claude-plugin" / "plugin.json"
        try:
            data = json.loads(manifest.read_text())
            if "hooks.off" in data:
                data["hooks"] = data.pop("hooks.off")
                manifest.write_text(json.dumps(data, indent=2))
        except (OSError, json.JSONDecodeError):
            pass
    if id_ in state:
        state[id_]["hooks_held"] = []
        _save_state(state)
    return names


def collection_skills(e: dict) -> list[dict]:
    """The skills in a collection repo (downloaded once)."""
    from .plugins import _skill_dirs, docks_home, parse_frontmatter
    src = docks_home() / "plugin-sources" / e["id"]
    if not src.is_dir():
        src.parent.mkdir(parents=True, exist_ok=True)
        url = e["url"] + ".git" if e["url"].startswith("https://github.com/") else e["url"]
        subprocess.run(["git", "clone", "-q", "--depth", "1", url, str(src)], capture_output=True, timeout=900)
    out = []
    for d in _skill_dirs(src):
        meta, _ = parse_frontmatter((d / "SKILL.md").read_text(errors="replace"))
        out.append({"name": meta.get("name") or d.name, "description": str(meta.get("description", ""))[:200], "path": str(d.relative_to(src))})
    return out


def install_from_collection(e: dict, wanted: list, log) -> list[str]:
    from .plugins import _write_plugin, docks_home, plugins_dir
    src = docks_home() / "plugin-sources" / e["id"]
    chosen = [s for s in collection_skills(e) if s["name"] in wanted or s["path"] in wanted]
    if not chosen:
        raise InstallError("none of those skills are in the collection")
    dest = plugins_dir() / e["id"]
    existing = sorted((dest / "skills").iterdir()) if (dest / "skills").is_dir() else []
    keep = {p.name: p for p in existing}
    tmp = home() / "tmp-skills"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    for name, p in keep.items():
        shutil.copytree(p, tmp / name)
    for s in chosen:
        target = tmp / Path(s["path"]).name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(src / s["path"], target)
        log(f"skill: {s['name']}")
    _write_plugin(dest, e["id"], f"Skills picked from {e['repo']}", sorted(tmp.iterdir()))
    shutil.rmtree(tmp)
    return [e["id"]]


def remove(id_: str, log=print) -> bool:
    from . import plugins
    e = find(id_)
    if e is None:
        return False
    state = _state()
    st = state.pop(id_, {})
    for n in st.get("plugins", []):
        plugins.remove(n)
    if e["kind"] == "app" and app_dir(e).is_dir():
        shutil.rmtree(app_dir(e), ignore_errors=True)
        log(f"removed {app_dir(e)}")
    elif e["kind"] in ("tool", "system", "template", "library"):
        log("left the program installed; uninstall it with your package manager (pip/uv/npm/winget/brew) if you want")
    _save_state(state)
    return True


RUNNING: dict = {}


def run(id_: str) -> dict:
    """Start an installed app (in the background). Returns {pid, open, log}."""
    from .care import shell_argv
    e = find(id_)
    if e is None or not e["run"]:
        raise InstallError("that integration has nothing to start")
    if status(e) != "installed":
        raise InstallError(f"install {e['name']} first")
    cwd = app_dir(e) if e["kind"] == "app" else Path(_state().get(e["id"], {}).get("project") or Path.home())
    for step in e["steps"]:
        if isinstance(step, dict) and "cd" in step:
            cwd = cwd / step["cd"]
    log_path = home() / f"{e['id']}.run.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    out = log_path.open("a")
    argv = shell_argv(e["run"]) or e["run"]
    proc = subprocess.Popen(argv, cwd=cwd, shell=isinstance(argv, str), stdout=out, stderr=subprocess.STDOUT, start_new_session=not WIN)
    RUNNING[e["id"]] = proc
    return {"pid": proc.pid, "open": e["open"], "log": str(log_path)}


def stop(id_: str) -> bool:
    proc = RUNNING.pop(id_, None)
    if proc and proc.poll() is None:
        proc.terminate()
        return True
    return False


def install_in_background(id_: str, on_line, on_done, **kw) -> None:
    def work():
        try:
            log_file = (home() / f"{id_}.log")
            home().mkdir(parents=True, exist_ok=True)
            with log_file.open("a") as f:
                def log(text):
                    f.write(text + "\n")
                    f.flush()
                    on_line(text)
                install(id_, log, **kw)
            on_done(None)
        except Exception as e:  # report every failure to the page
            on_done(str(e))
    threading.Thread(target=work, daemon=True).start()


def system_note() -> str:
    """What's installed, for the agent's instructions, so helpers use the real tools."""
    lines = []
    for e in E:
        if e["kind"] == "link" or status(e) != "installed":
            continue
        where = ""
        if e["kind"] == "app":
            where = f" at {app_dir(e)}" + (f" (start: `{e['run']}`" + (f", open {e['open']}" if e["open"] else "") + ")" if e["run"] else "")
        elif e["kind"] in ("tool", "system") and e.get("check") and not e["check"].startswith(("py:", "call:")):
            where = f" (command `{e['check']}`)"
        elif e["kind"] in ("plugin", "collection"):
            where = " (its skills and agents are loaded)"
        lines.append(f"- {e['name']}{where}" + (f"; used by the {e['agent']} helper" if e["agent"] else ""))
    if not lines:
        return ""
    return "\nInstalled integrations (use them for matching work):\n" + "\n".join(lines) + "\n"
