"""Router configuration: provider presets, routes, and how model names resolve."""

import json
import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PORT = 8787

# Well-known providers. "type" is the wire format the provider speaks.
PRESETS = {
    "anthropic":  {"type": "anthropic", "base_url": "https://api.anthropic.com", "api_key_env": "ANTHROPIC_API_KEY"},
    "openai":     {"type": "openai", "base_url": "https://api.openai.com/v1", "api_key_env": "OPENAI_API_KEY"},
    "deepseek":   {"type": "openai", "base_url": "https://api.deepseek.com/v1", "api_key_env": "DEEPSEEK_API_KEY"},
    "gemini":     {"type": "openai", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "api_key_env": "GEMINI_API_KEY"},
    "mistral":    {"type": "openai", "base_url": "https://api.mistral.ai/v1", "api_key_env": "MISTRAL_API_KEY"},
    "groq":       {"type": "openai", "base_url": "https://api.groq.com/openai/v1", "api_key_env": "GROQ_API_KEY"},
    "openrouter": {"type": "openai", "base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY"},
    "xai":        {"type": "openai", "base_url": "https://api.x.ai/v1", "api_key_env": "XAI_API_KEY"},
    "together":   {"type": "openai", "base_url": "https://api.together.xyz/v1", "api_key_env": "TOGETHER_API_KEY"},
    "fireworks":  {"type": "openai", "base_url": "https://api.fireworks.ai/inference/v1", "api_key_env": "FIREWORKS_API_KEY"},
    "cerebras":   {"type": "openai", "base_url": "https://api.cerebras.ai/v1", "api_key_env": "CEREBRAS_API_KEY"},
    # Local models: no API key, no usage limits.
    "ollama":     {"type": "openai", "base_url": "http://localhost:11434/v1", "api_key_env": None, "local": True},
    "lmstudio":   {"type": "openai", "base_url": "http://localhost:1234/v1", "api_key_env": None, "local": True},
}

# Edit model IDs to taste; the router skips providers you have no key for.
DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": DEFAULT_PORT,
    "client_key_env": "DOCKS_ROUTER_KEY",
    "fallback_to_default": True,
    "max_wait_seconds": 300,
    "providers": {name: {} for name in PRESETS},
    "routes": {
        "code-best": {"strategy": "fallback", "targets": [
            "anthropic/claude-opus-5-5", "deepseek/deepseek-chat", "ollama/qwen2.5-coder"]},
        "code-fast": {"strategy": "fallback", "targets": [
            "anthropic/claude-haiku-5-5", "deepseek/deepseek-chat", "ollama/qwen2.5-coder"]},
        "code-local": {"strategy": "fallback", "targets": ["ollama/qwen2.5-coder", "lmstudio/local-model"]},
    },
    "aliases": {
        "claude-haiku-5-5": "code-fast",
    },
    "model_prefixes": {
        "claude-": "anthropic", "gpt-": "openai", "o3": "openai", "o4": "openai",
        "deepseek-": "deepseek", "gemini-": "gemini", "mistral-": "mistral", "codestral-": "mistral",
        "grok-": "xai",
    },
    "default_route": "code-best",
}


@dataclass
class Provider:
    name: str
    type: str                 # "anthropic" | "openai"
    base_url: str
    api_key_env: str | None = None
    api_key: str | None = None
    local: bool = False
    max_tokens: int | None = None   # only set if the provider rejects large values

    def key(self) -> str | None:
        return self.api_key or (os.environ.get(self.api_key_env) if self.api_key_env else None)

    @property
    def available(self) -> bool:
        return self.local or bool(self.key())


@dataclass
class Route:
    name: str
    strategy: str
    targets: list[str]


def config_path() -> Path:
    return Path(os.environ.get("DOCKS_HOME", Path.home() / ".docks")) / "router.json"


def load(path: Path | None = None) -> dict:
    path = path or config_path()
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    if path.is_file():
        user = json.loads(path.read_text())
        for key, value in user.items():
            if isinstance(value, dict) and isinstance(cfg.get(key), dict) and key != "routes":
                cfg[key].update(value)
            else:
                cfg[key] = value
    # Model routes Bowers offers by name; a route of the same name in your router.json wins.
    from .. import models
    opus = models.current("opus")
    for name in ("codex", "chatgpt"):
        cfg["routes"].setdefault(name, {"strategy": "fallback", "targets": [f"openai/{models.current(name)}", f"anthropic/{opus}"]})
    cfg["routes"].setdefault("fable", {"strategy": "fallback", "targets": [f"anthropic/{models.current('fable')}", f"anthropic/{opus}"]})
    return cfg


def write_default(path: Path | None = None) -> Path:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(json.dumps(DEFAULT_CONFIG, indent=2) + "\n")
    return path


def build_providers(cfg: dict) -> dict[str, Provider]:
    providers = {}
    for name, overrides in cfg["providers"].items():
        spec = {**PRESETS.get(name, {}), **(overrides or {})}
        if "type" not in spec or "base_url" not in spec:
            raise ValueError(f"provider {name!r} needs 'type' and 'base_url'")
        providers[name] = Provider(name=name, type=spec["type"], base_url=spec["base_url"].rstrip("/"),
                                   api_key_env=spec.get("api_key_env"), api_key=spec.get("api_key"),
                                   local=spec.get("local", False), max_tokens=spec.get("max_tokens"))
    return providers


def build_routes(cfg: dict) -> dict[str, Route]:
    return {name: Route(name, r.get("strategy", "fallback"), list(r["targets"]))
            for name, r in cfg["routes"].items()}
