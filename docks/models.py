"""The models Docks can work with, and how to reach each one.

Claude models go straight to the Anthropic API. Codex (OpenAI's coding model) and other non-Claude models go
through Docks Router, which translates the requests: Docks uses the router at DOCKS_ROUTER_URL if you run one,
or starts one inside its own process.

    docks -m fable       # Claude Fable 5.1: Anthropic's most capable model (costs about 2.5x Opus)
    docks -m codex       # OpenAI's Codex, needs OPENAI_API_KEY; the model is DOCKS_CODEX_MODEL (default gpt-5.3-codex)
    /model sonnet        # switch inside a session
"""

import os
import threading

CHOICES = [
    {"id": "claude-opus-5-5", "alias": "opus", "label": "Claude Opus 5.5", "note": "the default: strong and fast"},
    {"id": "claude-fable-5-1", "alias": "fable", "label": "Claude Fable 5.1",
     "note": "Anthropic's most capable model, for the hardest work; slower, about 2.5x the price of Opus"},
    {"id": "claude-sonnet-5-5", "alias": "sonnet", "label": "Claude Sonnet 5.5", "note": "quicker and cheaper"},
    {"id": "claude-haiku-5-5", "alias": "haiku", "label": "Claude Haiku 5.5", "note": "fastest and cheapest, for simple tasks"},
    {"id": "codex", "alias": "codex", "label": "Codex (OpenAI)",
     "note": "OpenAI's coding model through Docks Router; needs OPENAI_API_KEY"},
]
ALIASES = {c["alias"]: c["id"] for c in CHOICES} | {"claude-fable-5": "claude-fable-5", "gpt-codex": "codex"}

# models that take the newest web search / fetch tools; others get the basic versions
NEW_WEB_TOOL_MODELS = ("claude-opus-5-5", "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6",
                       "claude-sonnet-5-5", "claude-sonnet-5", "claude-sonnet-4-6")


class ModelError(Exception):
    pass


def codex_model() -> str:
    return os.environ.get("DOCKS_CODEX_MODEL", "gpt-5.3-codex")


def resolve(name: str) -> str:
    """'fable' -> 'claude-fable-5-1'; full model IDs pass through."""
    name = (name or "").strip()
    return ALIASES.get(name.lower(), name)


def uses_router(model: str) -> bool:
    """Non-Claude models are reached through Docks Router."""
    return not model.startswith("claude-")


def is_direct_anthropic(client) -> bool:
    """True for a client that talks to Anthropic's own API (not a router or a test double)."""
    base = str(getattr(client, "base_url", "") or "")
    return base.startswith("https://api.anthropic.com")


def label(model: str) -> str:
    choice = next((c for c in CHOICES if c["id"] == model), None)
    if choice is None:
        return model
    return f"{choice['label']} ({codex_model()})" if model == "codex" else choice["label"]


def web_tools(model: str) -> list[dict]:
    if model in NEW_WEB_TOOL_MODELS:
        return [{"type": "web_search_20260209", "name": "web_search"}, {"type": "web_fetch_20260209", "name": "web_fetch"}]
    if model.startswith("claude-"):
        return [{"type": "web_search_20250305", "name": "web_search"}, {"type": "web_fetch_20250910", "name": "web_fetch"}]
    return []  # other providers have no server-side web tools


# ---------------------------------------------------------------- the router

_router = {"url": None, "engine": None}
_router_lock = threading.Lock()


def _start_router() -> str:
    """Run Docks Router inside this process on a free local port. Returns its URL."""
    from http.server import ThreadingHTTPServer

    from .router import config
    from .router.engine import Engine
    from .router.server import make_handler

    cfg = config.load()
    engine = Engine(cfg)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(engine, None))
    threading.Thread(target=server.serve_forever, daemon=True, name="docks-router").start()
    _router["engine"] = engine
    return f"http://127.0.0.1:{server.server_address[1]}"


def check_codex() -> str | None:
    """Why Codex can't run here, or None if it can."""
    if os.environ.get("DOCKS_ROUTER_URL"):
        return None  # your own router decides
    if not os.environ.get("OPENAI_API_KEY"):
        return "Codex needs an OpenAI API key: set OPENAI_API_KEY (or run Docks Router yourself and set DOCKS_ROUTER_URL)"
    return None


def router_client(model: str):
    """An Anthropic-format client that reaches `model` through Docks Router."""
    import anthropic
    if model == "codex":
        problem = check_codex()
        if problem:
            raise ModelError(problem)
    url = os.environ.get("DOCKS_ROUTER_URL")
    if not url:
        with _router_lock:
            if _router["url"] is None:
                _router["url"] = _start_router()
            url = _router["url"]
    key = os.environ.get("DOCKS_ROUTER_KEY") or "docks-local"
    return anthropic.Anthropic(base_url=url, api_key=key, max_retries=0)  # Docks retries itself
