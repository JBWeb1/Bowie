"""Sandboxed shell commands: everything can be read, but only the project folder (and a private /tmp) can be
written, credential folders are hidden, and the network can be switched off.

Linux uses bubblewrap (`bwrap`); macOS uses the built-in `sandbox-exec`. Turn it on with `bowers --sandbox`,
`/sandbox`, or in settings.json:

    {"sandbox": {"enabled": true, "network": true, "allowWrite": ["~/.npm", "~/.cache"],
                 "excludedCommands": ["docker"], "autoAllowBashIfSandboxed": true}}

- network: false cuts sandboxed commands off from the internet (and from local servers). Dev servers
  started in the background keep the network so you can preview them; files stay protected.
- allowWrite: extra folders commands may write to, such as package caches.
- excludedCommands: commands that run outside the sandbox (they ask for approval as usual).
- autoAllowBashIfSandboxed: in auto mode, sandboxed commands run without asking unless they look destructive.
"""

import os
import platform
import shutil
from dataclasses import dataclass, field
from pathlib import Path

# never readable from inside the sandbox
HIDDEN = ["~/.ssh", "~/.aws", "~/.gnupg", "~/.config/gcloud", "~/.azure", "~/.kube", "~/.docker",
          "~/.netrc", "~/.npmrc", "~/.pypirc", "~/.git-credentials", "~/.config/gh"]

INSTALL_HINT = {"Linux": "install bubblewrap (e.g. `sudo apt install bubblewrap` or `sudo dnf install bubblewrap`)",
                "Darwin": "sandbox-exec should come with macOS"}


class SandboxUnavailable(Exception):
    pass


def engine() -> str | None:
    if platform.system() == "Linux" and shutil.which("bwrap"):
        return "bwrap"
    if platform.system() == "Darwin" and shutil.which("sandbox-exec"):
        return "sandbox-exec"
    return None


def unavailable_reason() -> str:
    return (f"Sandboxing needs bubblewrap on Linux or sandbox-exec on macOS; {INSTALL_HINT.get(platform.system(), 'it is not supported on this system')}.")


@dataclass
class Sandbox:
    root: Path
    network: bool = True
    allow_write: list = field(default_factory=list)
    excluded: list = field(default_factory=list)
    auto_allow: bool = True

    @classmethod
    def from_settings(cls, root: Path, settings: dict) -> "Sandbox":
        spec = settings.get("sandbox") if isinstance(settings.get("sandbox"), dict) else {}
        if not engine():
            raise SandboxUnavailable(unavailable_reason())
        return cls(root, bool(spec.get("network", True)), list(spec.get("allowWrite") or []),
                   list(spec.get("excludedCommands") or []), bool(spec.get("autoAllowBashIfSandboxed", True)))

    def excludes(self, command: str) -> bool:
        first = command.strip().split()[:1]
        return bool(first) and any(first[0] == c or first[0].endswith("/" + c) for c in self.excluded)

    def _writable(self) -> list[str]:
        paths = [str(self.root.resolve())]
        for p in self.allow_write:
            path = Path(os.path.expanduser(p)).resolve()
            path.mkdir(parents=True, exist_ok=True)
            paths.append(str(path))
        return paths

    def argv(self, command: str, server: bool = False) -> list[str] | None:
        """The command line that runs `command` in the sandbox (None: run it unsandboxed).

        server: a dev server the user previews, which keeps the network so the preview can reach it."""
        if self.excludes(command):
            return None
        kind = engine()
        if kind == "bwrap":
            args = ["bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
                    "--die-with-parent", "--new-session", "--unshare-pid"]
            for hidden in HIDDEN:
                path = Path(os.path.expanduser(hidden))
                if path.is_dir():
                    args += ["--tmpfs", str(path)]
                elif path.exists():
                    args += ["--ro-bind", "/dev/null", str(path)]
            for path in self._writable():
                args += ["--bind", path, path]
            if not self.network and not server:
                args.append("--unshare-net")
            return args + ["--chdir", str(self.root.resolve()), "--", "/bin/sh", "-c", command]
        if kind == "sandbox-exec":
            quote = lambda p: '"' + p.replace('"', '\\"') + '"'  # noqa: E731
            writable = " ".join(f"(subpath {quote(p)})" for p in self._writable() + ["/private/tmp", "/private/var/folders"])
            hidden = " ".join(f"(subpath {quote(os.path.expanduser(h))})" for h in HIDDEN)
            profile = ("(version 1)(allow default)(deny file-write*)"
                       f"(allow file-write* {writable} (literal \"/dev/null\") (regex #\"^/dev/tty\"))"
                       f"(deny file-read* {hidden})" + ("" if self.network or server else "(deny network*)"))
            return ["sandbox-exec", "-p", profile, "/bin/sh", "-c", command]
        raise SandboxUnavailable(unavailable_reason())

    def describe(self) -> str:
        net = "network on" if self.network else "no network"
        extra = f", plus {', '.join(self.allow_write)}" if self.allow_write else ""
        return f"sandbox on ({engine()}): writes only in the project{extra}; {net}"

