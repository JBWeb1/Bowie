"""`bowers router ...` subcommands."""

import argparse
import json
import sys
from pathlib import Path

from . import config

SETUP = {
    "claude-code": """# Claude Code (add to your shell profile)
export ANTHROPIC_BASE_URL={url}
export ANTHROPIC_AUTH_TOKEN={key}
export ANTHROPIC_MODEL=code-best          # optional: use a router route
export ANTHROPIC_SMALL_FAST_MODEL=code-fast""",
    "docks": """# Bowers
export ANTHROPIC_BASE_URL={url}
export ANTHROPIC_API_KEY={key}
bowers -m code-best""",
    "aider": """aider --openai-api-base {url}/v1 --openai-api-key {key} --model openai/code-best""",
    "cline": """# Cline / Roo Code / Kilo Code
API Provider: OpenAI Compatible
Base URL:     {url}/v1
API Key:      {key}
Model ID:     code-best""",
    "continue": """# ~/.continue/config.yaml
models:
  - name: Bowers Router
    provider: openai
    model: code-best
    apiBase: {url}/v1
    apiKey: {key}""",
    "opencode": json.dumps({"provider": {"docks": {
        "npm": "@ai-sdk/openai-compatible", "name": "Bowers Router",
        "options": {"baseURL": "{url}/v1", "apiKey": "{key}"},
        "models": {"code-best": {}, "code-fast": {}, "code-local": {}}}}}, indent=2),
    "cursor": """# Cursor: Settings > Models
OpenAI API Key:           {key}
Override OpenAI Base URL: {url}/v1
Add model:                code-best
# Cursor calls the base URL from its own servers, so localhost won't work:
# expose the router with a tunnel (e.g. cloudflared) and set DOCKS_ROUTER_KEY first.""",
}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="bowers router", description="Route coding tools across AI providers.")
    parser.add_argument("--config", type=Path, help=f"config file (default {config.config_path()})")
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="start the router")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    sub.add_parser("init", help="write a starter config you can edit")
    sub.add_parser("routes", help="show how each route resolves right now")
    st = sub.add_parser("setup", help="print setup for a coding tool")
    st.add_argument("tool", choices=sorted(SETUP))
    args = parser.parse_args(argv)

    cfg = config.load(args.config)
    if args.cmd == "init":
        path = config.write_default(args.config)
        print(f"config at {path}\nset API keys as environment variables, e.g. ANTHROPIC_API_KEY, DEEPSEEK_API_KEY;")
        print("install Ollama and run `ollama pull qwen2.5-coder` for an unlimited local fallback.")
        return 0
    if args.cmd == "serve":
        from .server import serve
        if args.host:
            cfg["host"] = args.host
        if args.port:
            cfg["port"] = args.port
        serve(cfg)
        return 0
    if args.cmd == "routes":
        from .engine import Engine
        engine = Engine(cfg)
        for name in engine.routes:
            labels = [t.label for t in engine.resolve(name)]
            print(f"{name:12} -> {' -> '.join(labels) or '(nothing available)'}")
        return 0
    url = f"http://{cfg['host']}:{cfg['port']}"
    key = "$" + cfg["client_key_env"] if cfg.get("client_key_env") else "any-value"
    print(SETUP[args.tool].replace("{url}", url).replace("{key}", key))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
