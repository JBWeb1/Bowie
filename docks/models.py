"""The models Bowers can work with, how to reach each one, and keeping them up to date.

Engines: short names pick a model family, and Bowers keeps each one pointing at the newest model in it:

    opus     Claude Opus (the default)          fable    Claude Fable: Anthropic's most capable
    sonnet   Claude Sonnet: quicker, cheaper    haiku    Claude Haiku: fastest, cheapest
    codex    OpenAI's Codex coding model        chatgpt  OpenAI's flagship GPT model

Claude models go straight to the Anthropic API. OpenAI's go through Bowers Router, which translates the requests:
Bowers uses the router at DOCKS_ROUTER_URL if you run one, or starts one inside its own process (needs
OPENAI_API_KEY).

Updates: once a day (in the background) or with `bowers models update`, Bowers asks Anthropic and OpenAI which
models your keys can use and moves each short name to the newest one in its family. The choices are saved in
~/.docks/models.json. Pin one with an environment variable (DOCKS_FABLE_MODEL, DOCKS_CODEX_MODEL, ...), or turn
updates off with {"autoUpdateModels": false} in settings.
"""

import json
import os
import re
import threading
import time
import urllib.request
from pathlib import Path

DEFAULTS = {"opus": "claude-opus-5-5", "fable": "claude-fable-5-1", "sonnet": "claude-sonnet-5-5",
            "haiku": "claude-haiku-5-5", "codex": "gpt-5.3-codex", "chatgpt": "gpt-5.5"}
OPENAI_FAMILIES = ("codex", "chatgpt")  # reached through the router, by these route names
INFO = {
    "opus": ("Claude Opus", "the default: strong and fast"),
    "fable": ("Claude Fable", "Anthropic's most capable model, for the hardest work; slower, about 2.5x the price of Opus"),
    "sonnet": ("Claude Sonnet", "quicker and cheaper"),
    "haiku": ("Claude Haiku", "fastest and cheapest, for simple tasks"),
    "codex": ("Codex (OpenAI)", "OpenAI's coding model through Bowers Router; needs OPENAI_API_KEY"),
    "chatgpt": ("ChatGPT model (OpenAI)", "OpenAI's flagship GPT model through Bowers Router; needs OPENAI_API_KEY"),
}
EXTRA_ALIASES = {"gpt": "chatgpt", "gpt-codex": "codex", "openai": "chatgpt"}
UPDATE_EVERY = 24 * 3600

# models that take the newest web search / fetch tools; others get the basic versions
NEW_WEB_TOOL_MODELS = ("claude-opus-5-5", "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6",
                       "claude-sonnet-5-5", "claude-sonnet-5", "claude-sonnet-4-6")


class ModelError(Exception):
    pass


# Bowers' own models: each one is a tuned profile (an engine, how hard it thinks, and its own way of working)
# on top of the newest model in a family, so they improve as the engines do.
PROFILES = {
    "syntra": {
        "name": "Bowers Syntra 1", "engine": "opus", "effort": "high",
        "tagline": "Modern and technical: software, automation and complex workflows",
        "prompt": ("You are Bowers Syntra, Bowers' model for building software. Be precise and pragmatic: understand "
                   "the codebase before changing it, prefer small verified steps, run the tests and the app, and "
                   "automate what repeats. Report like a senior engineer: what changed, how you checked it, what's left."),
    },
    "aether": {
        "name": "Bowers Aether 1", "engine": "fable", "effort": "xhigh",
        "tagline": "The flagship: deep reasoning, research and creativity",
        "prompt": ("You are Bowers Aether, Bowers' flagship model for the hardest problems. Think broadly before "
                   "settling on an approach: weigh alternatives, research what you don't know, and bring original, "
                   "creative ideas, then carry the work through to a polished result."),
    },
    "solace": {
        "name": "Bowers Solace 1", "engine": "sonnet", "effort": "medium",
        "tagline": "Calm and clear: understands what you need and explains as it goes",
        "prompt": ("You are Bowers Solace, Bowers' calm and thoughtful model. Take time to understand what the person "
                   "really wants; ask a short question when it's unclear. Explain in plain, warm language without "
                   "jargon, keep the person in the loop, and make complex things feel simple."),
    },
}
DEFAULT_PROFILE = "syntra"


def profile_of(name: str) -> str | None:
    """'aether', 'Bowers Aether 1' or 'bowers-aether-1' -> 'aether'."""
    key = re.sub(r"[\s_]+", "-", (name or "").strip().lower()).removeprefix("bowers-")
    key = re.sub(r"-\d+$", "", key)
    return key if key in PROFILES else None


# ---------------------------------------------------------------- saved choices

def saved_path() -> Path:
    return Path(os.environ.get("DOCKS_HOME", Path.home() / ".docks")) / "models.json"


def _saved() -> dict:
    try:
        return json.loads(saved_path().read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _env_name(family: str) -> str:
    return f"DOCKS_{family.upper()}_MODEL"


def current(family: str) -> str:
    """The model a short name points at: a pinned environment variable, else the newest found, else the default."""
    return os.environ.get(_env_name(family)) or _saved().get(family) or DEFAULTS[family]


def codex_model() -> str:
    return current("codex")


def choices() -> list[dict]:
    out = [{"id": key, "alias": key, "label": p["name"], "note": p["tagline"], "group": "Bowers",
            "engine": current(p["engine"])} for key, p in PROFILES.items()]
    for family in DEFAULTS:
        name, note = INFO[family]
        model = current(family)
        out.append({"id": family if family in OPENAI_FAMILIES else model, "alias": family,
                    "label": f"{name} ({model})" if family in OPENAI_FAMILIES else _pretty(model), "note": note,
                    "group": "Engines"})
    return out


def _pretty(model: str) -> str:
    m = re.fullmatch(r"claude-([a-z]+)-(\d+)(?:-(\d+))?", model)
    if not m:
        return model
    return f"Claude {m.group(1).title()} {m.group(2)}" + (f".{m.group(3)}" if m.group(3) else "")


def resolve(name: str) -> str:
    """'fable' -> the current Fable model ID; 'codex' / 'chatgpt' stay route names; full IDs pass through."""
    key = (name or "").strip().lower()
    key = EXTRA_ALIASES.get(key, key)
    if key in OPENAI_FAMILIES:
        return key
    if key in DEFAULTS:
        return current(key)
    return (name or "").strip()


def uses_router(model: str) -> bool:
    """Non-Claude models are reached through Bowers Router."""
    return not model.startswith("claude-")


def is_direct_anthropic(client) -> bool:
    """True for a client that talks to Anthropic's own API (not a router or a test double)."""
    base = str(getattr(client, "base_url", "") or "")
    return base.startswith("https://api.anthropic.com")


def label(model: str) -> str:
    for c in choices():
        if c["id"] == model:
            return c["label"]
    return _pretty(model)


def web_tools(model: str) -> list[dict]:
    if model in NEW_WEB_TOOL_MODELS:
        return [{"type": "web_search_20260209", "name": "web_search"}, {"type": "web_fetch_20260209", "name": "web_fetch"}]
    if model.startswith("claude-"):
        return [{"type": "web_search_20250305", "name": "web_search"}, {"type": "web_fetch_20250910", "name": "web_fetch"}]
    return []  # other providers have no server-side web tools


# ---------------------------------------------------------------- finding the newest models

def _family_of_claude(model_id: str) -> str | None:
    m = re.match(r"claude-(opus|fable|sonnet|haiku)-\d", model_id)
    return m.group(1) if m else None


def _family_of_openai(model_id: str) -> str | None:
    if "codex" in model_id and not re.search(r"mini|nano|preview", model_id):
        return "codex"
    if re.fullmatch(r"gpt-\d+(\.\d+)?", model_id):
        return "chatgpt"
    return None


def _created(value) -> float:
    if hasattr(value, "timestamp"):
        return value.timestamp()
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def newest_models(anthropic_client=None) -> tuple[dict, list[str]]:
    """{family: newest model ID} from the providers you have keys for, plus notes about any that couldn't be checked."""
    found, notes = {}, []
    best = {}
    try:
        import anthropic
        client = anthropic_client or anthropic.Anthropic()
        for info in client.models.list(limit=1000):
            family = _family_of_claude(info.id)
            if family and _created(info.created_at) >= best.get(family, (0, ""))[0]:
                best[family] = (_created(info.created_at), info.id)
    except TypeError:  # the SDK found no credentials
        notes.append("Claude not checked (no ANTHROPIC_API_KEY)")
    except Exception as e:  # offline, a router in front
        notes.append(f"couldn't list Claude models ({type(e).__name__})")
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        try:
            req = urllib.request.Request(f"{base}/models", headers={"Authorization": f"Bearer {key}"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read()).get("data", [])
            for info in data:
                family = _family_of_openai(info.get("id", ""))
                if family and _created(info.get("created")) >= best.get(family, (0, ""))[0]:
                    best[family] = (_created(info.get("created")), info["id"])
        except Exception as e:
            notes.append(f"couldn't list OpenAI models ({type(e).__name__})")
    else:
        notes.append("OpenAI not checked (no OPENAI_API_KEY)")
    for family, (_, model) in best.items():
        found[family] = model
    return found, notes


def update(anthropic_client=None) -> tuple[dict, list[str]]:
    """Point each short name at the newest model in its family. Returns ({family: (old, new)}, notes)."""
    found, notes = newest_models(anthropic_client)
    if not found:
        notes.insert(0, "no provider could be checked, so nothing changed")
    saved = _saved()
    changes = {}
    for family, model in found.items():
        if os.environ.get(_env_name(family)):
            continue  # pinned
        old = current(family)
        if model != old:
            changes[family] = (old, model)
        saved[family] = model
    if found:  # a failed check is tried again next time
        saved["checked"] = time.time()
    path = saved_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(saved, indent=2) + "\n")
    return changes, notes


def update_in_background(settings: dict, on_change=None, anthropic_client=None) -> threading.Thread | None:
    """Check for newer models once a day, without slowing anything down."""
    if settings.get("autoUpdateModels", True) is False:
        return None
    if time.time() - float(_saved().get("checked", 0)) < UPDATE_EVERY:
        return None

    def work():
        try:
            changes, _ = update(anthropic_client)
        except Exception:
            return
        if changes and on_change:
            on_change(changes)
    thread = threading.Thread(target=work, daemon=True, name="docks-model-update")
    thread.start()
    return thread


def describe_changes(changes: dict) -> str:
    return "; ".join(f"{family} is now {new} (was {old})" for family, (old, new) in changes.items())


# ---------------------------------------------------------------- the router

_router = {"url": None, "engine": None}
_router_lock = threading.Lock()


def _start_router() -> str:
    """Run Bowers Router inside this process on a free local port. Returns its URL."""
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


def check_openai(model: str = "codex") -> str | None:
    """Why an OpenAI model can't run here, or None if it can."""
    if os.environ.get("DOCKS_ROUTER_URL"):
        return None  # your own router decides
    if not os.environ.get("OPENAI_API_KEY"):
        name = INFO.get(model, (model, ""))[0]
        return (f"{name} needs an OpenAI API key: set OPENAI_API_KEY "
                "(or run Bowers Router yourself and set DOCKS_ROUTER_URL)")
    return None


check_codex = check_openai


def router_client(model: str):
    """An Anthropic-format client that reaches `model` through Bowers Router."""
    import anthropic
    if model in OPENAI_FAMILIES or not model.startswith("claude-"):
        problem = check_openai(model)
        if problem:
            raise ModelError(problem)
    url = os.environ.get("DOCKS_ROUTER_URL")
    if not url:
        with _router_lock:
            if _router["url"] is None:
                _router["url"] = _start_router()
            url = _router["url"]
    key = os.environ.get("DOCKS_ROUTER_KEY") or "docks-local"
    return anthropic.Anthropic(base_url=url, api_key=key, max_retries=0)  # Bowers retries itself
