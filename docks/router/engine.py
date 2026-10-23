"""Pick a provider for each request, fail over on errors, and track provider health.

The engine never gives up just because one provider is limited: it moves on to
the next target, and if every target is cooling down it waits for the first one
to recover (up to max_wait_seconds) instead of returning an error.
"""

import itertools
import json
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque
from dataclasses import dataclass

from . import translate
from .config import Provider, Route, build_providers, build_routes

TRANSIENT = {408, 409, 429, 500, 502, 503, 504, 529}
QUOTA_MARKERS = ("insufficient_quota", "credit balance", "quota exceeded", "exceeded your current quota",
                 "billing", "payment required")


class ClientError(Exception):
    """The request itself is bad (HTTP 400); retrying elsewhere won't help."""

    def __init__(self, status: int, body: bytes):
        super().__init__(f"upstream returned {status}")
        self.status, self.body = status, body


class Exhausted(Exception):
    pass


@dataclass
class UpstreamError(Exception):
    status: int | None
    message: str
    retry_after: float | None = None

    def __str__(self):
        return f"{self.status or 'connection'}: {self.message[:300]}"


@dataclass
class Target:
    provider: Provider
    model: str

    @property
    def label(self) -> str:
        return f"{self.provider.name}/{self.model}"


class Health:
    """Cooldowns per provider and per target, with exponential backoff."""

    def __init__(self):
        self.lock = threading.Lock()
        self.until = {}                      # key -> monotonic time it's usable again
        self.failures = defaultdict(int)     # key -> consecutive failures
        self.last_error = {}
        self.transient = {}                  # key -> True if the error clears by itself (worth waiting for)

    def ready_at(self, target: Target) -> float:
        with self.lock:
            return max(self.until.get(target.provider.name, 0), self.until.get(target.label, 0))

    def ok(self, target: Target) -> None:
        with self.lock:
            for key in (target.provider.name, target.label):
                self.failures.pop(key, None)
                self.until.pop(key, None)

    def fail(self, target: Target, err: UpstreamError) -> float:
        msg = err.message.lower()
        if err.status == 404:
            key, base, cap = target.label, 3600, 3600          # model doesn't exist there
        elif err.status in (401, 403):
            key, base, cap = target.provider.name, 3600, 3600  # bad or missing key
        elif err.status == 402 or any(m in msg for m in QUOTA_MARKERS):
            key, base, cap = target.provider.name, 1800, 3600  # out of credits / quota
        elif err.status == 429:
            key, base, cap = target.provider.name, 15, 600     # rate limited
        else:
            key, base, cap = target.provider.name, 10, 300     # 5xx, overloaded, connection
        with self.lock:
            self.failures[key] += 1
            delay = err.retry_after or min(base * 2 ** (self.failures[key] - 1), cap)
            self.until[key] = time.monotonic() + delay
            self.last_error[key] = str(err)
            quota = err.status == 402 or any(m in msg for m in QUOTA_MARKERS)
            self.transient[key] = not quota and (err.status in TRANSIENT or
                                                 (err.status is None and not target.provider.local))
        return delay

    def worth_waiting(self, target: Target) -> bool:
        """True unless the target is blocked by something that won't clear soon (bad key, no quota, local server down)."""
        now = time.monotonic()
        with self.lock:
            blockers = [k for k in (target.provider.name, target.label) if self.until.get(k, 0) > now]
            return all(self.transient.get(k, False) for k in blockers)

    def snapshot(self) -> dict:
        now = time.monotonic()
        with self.lock:
            return {k: {"cooldown_s": round(t - now, 1), "failures": self.failures.get(k, 0),
                        "last_error": self.last_error.get(k)}
                    for k, t in self.until.items() if t > now}


class Stats:
    def __init__(self, keep: int = 500):
        self.lock = threading.Lock()
        self.recent = deque(maxlen=keep)
        self.totals = defaultdict(lambda: {"requests": 0, "errors": 0, "input_tokens": 0,
                                           "output_tokens": 0, "latency_s": 0.0})
        self.started = time.time()

    def record(self, **entry) -> None:
        entry["time"] = time.time()
        with self.lock:
            self.recent.append(entry)
            t = self.totals[entry.get("target") or "none"]
            t["requests"] += 1
            t["errors"] += 0 if entry.get("ok") else 1
            t["input_tokens"] += entry.get("input_tokens", 0)
            t["output_tokens"] += entry.get("output_tokens", 0)
            t["latency_s"] += entry.get("latency_s", 0.0)

    def avg_latency(self, label: str) -> float:
        with self.lock:
            t = self.totals.get(label)
            return t["latency_s"] / t["requests"] if t and t["requests"] else 0.0

    def snapshot(self) -> dict:
        with self.lock:
            return {"uptime_s": round(time.time() - self.started), "totals": dict(self.totals),
                    "recent": list(self.recent)[-50:][::-1]}


def _retry_after(headers) -> float | None:
    try:
        return float(headers.get("retry-after")) if headers and headers.get("retry-after") else None
    except ValueError:
        return None


class Engine:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.providers = build_providers(cfg)
        self.routes = build_routes(cfg)
        self.health = Health()
        self.stats = Stats()
        self._rr = defaultdict(itertools.count)

    # ---------------------------------------------------------- resolution

    def _parse_target(self, spec: str) -> Target | None:
        name, _, model = spec.partition("/")
        provider = self.providers.get(name)
        return Target(provider, model) if provider and model else None

    def _route_targets(self, route: Route) -> list[Target]:
        targets = [t for t in map(self._parse_target, route.targets) if t]
        if route.strategy == "round-robin" and targets:
            shift = next(self._rr[route.name]) % len(targets)
            targets = targets[shift:] + targets[:shift]
        elif route.strategy == "latency":
            targets.sort(key=lambda t: self.stats.avg_latency(t.label))
        return targets

    def resolve(self, model: str) -> list[Target]:
        model = self.cfg["aliases"].get(model, model)
        if model in self.routes:
            targets = self._route_targets(self.routes[model])
        elif "/" in model and (t := self._parse_target(model)):
            targets = [t]
        else:
            prefix = next((p for p in self.cfg["model_prefixes"] if model.startswith(p)), None)
            provider = self.providers.get(self.cfg["model_prefixes"][prefix]) if prefix else None
            targets = [Target(provider, model)] if provider else []
        default = self.routes.get(self.cfg.get("default_route", ""))
        if default and (self.cfg.get("fallback_to_default", True) or not targets):
            seen = {t.label for t in targets}
            targets += [t for t in self._route_targets(default) if t.label not in seen]
        return [t for t in targets if t.provider.available]

    def models(self) -> list[str]:
        names = list(self.routes) + list(self.cfg["aliases"])
        for route in self.routes.values():
            names += [s for s in route.targets if (t := self._parse_target(s)) and t.provider.available]
        return list(dict.fromkeys(names))

    # ------------------------------------------------------------- upstream

    def build_body(self, client_fmt: str, body: dict, target: Target) -> dict:
        cap = target.provider.max_tokens
        if target.provider.type == client_fmt:
            out = {**body, "model": target.model}
            for key in ("max_tokens", "max_completion_tokens"):
                if cap and out.get(key):
                    out[key] = min(out[key], cap)
            return out
        if client_fmt == "anthropic":
            return translate.anthropic_to_openai_request(body, target.model, cap)
        return translate.openai_to_anthropic_request(body, target.model, cap)

    def open(self, target: Target, payload: dict, client_headers: dict, path: str = ""):
        p = target.provider
        headers = {"content-type": "application/json", "accept": "application/json, text/event-stream"}
        if p.type == "anthropic":
            url = f"{p.base_url}/v1/messages{path}"
            headers["anthropic-version"] = client_headers.get("anthropic-version", "2023-06-01")
            if client_headers.get("anthropic-beta"):
                headers["anthropic-beta"] = client_headers["anthropic-beta"]
            if p.key():
                headers["x-api-key"] = p.key()
        else:
            url = f"{p.base_url}/chat/completions"
            if p.key():
                headers["authorization"] = f"Bearer {p.key()}"
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
        try:
            return urllib.request.urlopen(req, timeout=600)
        except urllib.error.HTTPError as e:
            raw = e.read()
            if e.code in (400, 413, 422):
                raise ClientError(e.code, raw)
            raise UpstreamError(e.code, raw.decode(errors="replace"), _retry_after(e.headers))
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            raise UpstreamError(None, str(getattr(e, "reason", e)))

    def dispatch(self, client_fmt: str, body: dict, client_headers: dict, path: str = ""):
        """Return (target, upstream_response). Fails over and waits; never stops at one provider's limit."""
        targets = self.resolve(body.get("model", ""))
        if not targets:
            raise Exhausted(f"no available provider for model {body.get('model')!r}; "
                            "set an API key or add a local model (see `bowers router init`)")
        deadline = time.monotonic() + self.cfg.get("max_wait_seconds", 300)
        errors = []
        while True:
            now = time.monotonic()
            for target in targets:
                if self.health.ready_at(target) > now:
                    continue
                if path and target.provider.type != "anthropic":
                    continue  # count_tokens only exists on Anthropic
                try:
                    resp = self.open(target, self.build_body(client_fmt, body, target), client_headers, path)
                except UpstreamError as err:
                    delay = self.health.fail(target, err)
                    errors.append(f"{target.label} -> {err} (cooling {delay:.0f}s)")
                    continue
                self.health.ok(target)
                return target, resp
            waitable = [self.health.ready_at(t) for t in targets if self.health.worth_waiting(t)]
            soonest = min(waitable, default=float("inf"))
            if path or soonest > deadline:
                raise Exhausted("all providers failed or are limited:\n" + "\n".join(errors[-10:]))
            time.sleep(max(soonest - time.monotonic(), 0.05))
