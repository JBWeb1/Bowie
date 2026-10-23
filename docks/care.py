"""Bowers Care: find and fix problems on Windows, Linux and macOS computers.

The system_check tool gathers facts read-only (it never changes anything): the OS, memory, disks, failed services,
recent system errors, network, the busiest programs and pending updates. Bowers then explains what's wrong and
proposes fixes, which run as normal commands, so each one asks you first (in PowerShell on Windows).
"""

import os
import platform
import shutil
import socket
import subprocess
import time
from pathlib import Path

SYSTEM = platform.system()  # Linux, Windows, Darwin
SECTIONS = ("overview", "errors", "services", "disk", "network", "processes", "updates")

SCHEMA = {
    "description": (
        "Look at this computer's health without changing anything: overview (OS, uptime, CPU, memory, disks and "
        "warnings), errors (recent system errors from the journal or Windows Event Log), services (failed or "
        "stopped ones), disk (usage and the biggest folders in the home folder), network (interfaces, DNS, "
        "internet), processes (the busiest programs), updates (pending updates). Use it first when the person "
        "has a computer problem, then explain what you found and propose fixes one at a time."),
    "properties": {
        "sections": {"type": "array", "items": {"type": "string", "enum": list(SECTIONS)},
                     "description": "which checks to run (default: overview)"},
    },
    "required": [],
}

CARE_NOTE = """
Computer care: when the person has a problem with their computer (slow, crashing, no Wi-Fi, full disk, broken
updates, an app that won't start, error messages), first run system_check, then explain the cause in plain words.
Fix one thing at a time with commands they can see, safest first; say what each one does and how to undo it. Never
delete personal files, change passwords or disable security software. Ask before restarting anything.
"""


def shell_name() -> str:
    if SYSTEM == "Windows":
        return "PowerShell"
    return os.path.basename(os.environ.get("SHELL", "sh"))


def shell_argv(command: str) -> list[str] | None:
    """On Windows, commands run in PowerShell (pwsh when installed); elsewhere the default shell runs them."""
    if SYSTEM != "Windows":
        return None
    exe = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
    return [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command]


def _run(argv, timeout: int = 20) -> str:
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return (proc.stdout or proc.stderr).strip()
    except FileNotFoundError:
        return ""
    except (OSError, subprocess.SubprocessError) as e:
        return f"(couldn't run: {e})"


def _ps(script: str, timeout: int = 30) -> str:
    return _run(shell_argv(script), timeout)


def _gb(n: float) -> str:
    return f"{n / 1024 ** 3:.1f} GB"


def _memory() -> tuple[int, int] | None:
    """(total, available) bytes."""
    try:
        if SYSTEM == "Linux":
            info = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines() if ":" in line)
            kb = lambda k: int(info[k].split()[0]) * 1024  # noqa: E731
            return kb("MemTotal"), kb("MemAvailable")
        if SYSTEM == "Darwin":
            total = int(_run(["sysctl", "-n", "hw.memsize"]) or 0)
            pages = _run(["vm_stat"])
            free = sum(int(line.split()[-1].rstrip(".")) for line in pages.splitlines()
                       if line.startswith(("Pages free", "Pages inactive", "Pages speculative"))) * 4096
            return (total, free) if total else None
        if SYSTEM == "Windows":
            out = _ps("$o=Get-CimInstance Win32_OperatingSystem; \"$($o.TotalVisibleMemorySize) $($o.FreePhysicalMemory)\"")
            total, free = (int(x) * 1024 for x in out.split()[:2])
            return total, free
    except (OSError, ValueError, KeyError, IndexError):
        return None
    return None


def _uptime() -> str:
    try:
        if SYSTEM == "Linux":
            secs = float(Path("/proc/uptime").read_text().split()[0])
        elif SYSTEM == "Windows":
            secs = float(_ps("[int]((Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime).TotalSeconds") or 0)
        else:
            boot = _run(["sysctl", "-n", "kern.boottime"])  # { sec = 1700000000, usec = 0 } ...
            secs = time.time() - int(boot.split("sec =")[1].split(",")[0])
    except (OSError, ValueError, IndexError):
        return "unknown"
    days, rest = divmod(int(secs), 86400)
    return f"{days}d {rest // 3600}h" if days else f"{rest // 3600}h {rest % 3600 // 60}m"


def _os_name() -> str:
    if SYSTEM == "Linux":
        try:
            info = dict(line.split("=", 1) for line in Path("/etc/os-release").read_text().splitlines() if "=" in line)
            return info.get("PRETTY_NAME", "Linux").strip('"') + f" (kernel {platform.release()})"
        except OSError:
            return f"Linux {platform.release()}"
    if SYSTEM == "Darwin":
        return f"macOS {platform.mac_ver()[0]}"
    if SYSTEM == "Windows":
        return f"Windows {platform.release()} ({platform.version()})"
    return platform.platform()


def _disks() -> list[tuple[str, int, int]]:
    """(mount, total, free) for the main drives."""
    places = []
    if SYSTEM == "Windows":
        places = [f"{d}:\\" for d in "CDEFGH" if os.path.exists(f"{d}:\\")]
    else:
        places = ["/", str(Path.home())]
    seen, out = set(), []
    for p in places:
        try:
            u = shutil.disk_usage(p)
        except OSError:
            continue
        if (u.total, u.free) in seen:
            continue
        seen.add((u.total, u.free))
        out.append((p, u.total, u.free))
    return out


def overview() -> tuple[str, list[str]]:
    """The summary text and a list of warnings."""
    warnings = []
    lines = [f"Computer: {socket.gethostname()} · {_os_name()} · {platform.machine()}",
             f"Up for {_uptime()} · {os.cpu_count()} CPU threads · shell {shell_name()}"]
    if hasattr(os, "getloadavg"):
        load = os.getloadavg()
        lines.append(f"Load average: {load[0]:.2f} {load[1]:.2f} {load[2]:.2f}")
        if load[0] > (os.cpu_count() or 1) * 1.5:
            warnings.append(f"the CPU is overloaded (load {load[0]:.1f} on {os.cpu_count()} threads)")
    mem = _memory()
    if mem:
        total, free = mem
        lines.append(f"Memory: {_gb(total - free)} used of {_gb(total)} ({free / total:.0%} free)")
        if free / total < 0.1:
            warnings.append(f"memory is almost full ({free / total:.0%} free)")
    for mount, total, free in _disks():
        lines.append(f"Disk {mount}: {_gb(free)} free of {_gb(total)} ({free / total:.0%} free)")
        if free / total < 0.1:
            warnings.append(f"disk {mount} is almost full ({_gb(free)} left)")
    return "\n".join(lines), warnings


def errors() -> str:
    if SYSTEM == "Linux":
        out = _run(["journalctl", "-p", "3", "-b", "--no-pager", "-n", "40", "-o", "short"])
        return out or _run(["dmesg", "--level=err,crit,alert,emerg"])[-4000:] or "(no access to the system log)"
    if SYSTEM == "Windows":
        return _ps("Get-WinEvent -FilterHashtable @{LogName='System','Application'; Level=1,2; "
                   "StartTime=(Get-Date).AddDays(-2)} -MaxEvents 30 -ErrorAction SilentlyContinue | "
                   "Format-Table TimeCreated, ProviderName, Id, Message -AutoSize -Wrap | Out-String -Width 220", 60)
    return _run(["log", "show", "--last", "1h", "--predicate", "messageType == error", "--style", "compact"], 60)[-6000:]


def services() -> str:
    if SYSTEM == "Linux":
        out = _run(["systemctl", "--failed", "--no-legend", "--plain"])
        return out or "no failed services (or systemd isn't running here)"
    if SYSTEM == "Windows":
        return _ps("Get-CimInstance Win32_Service | Where-Object { $_.StartMode -eq 'Auto' -and $_.State -ne 'Running' } "
                   "| Select-Object Name, DisplayName, State, ExitCode | Format-Table -AutoSize | Out-String -Width 200") \
            or "every automatic service is running"
    return _run(["launchctl", "list"])[:4000]


def disk() -> str:
    lines = [f"{m}: {_gb(t - f)} used, {_gb(f)} free of {_gb(t)}" for m, t, f in _disks()]
    home = Path.home()
    sizes = []
    try:
        children = list(home.iterdir())
    except OSError:
        children = []
    deadline = time.monotonic() + 15
    for child in children:
        if time.monotonic() > deadline:
            lines.append("(stopped measuring folders after 15 seconds)")
            break
        if child.is_symlink() or not child.is_dir():
            continue
        total = 0
        for dirpath, _dirs, files in os.walk(child, onerror=lambda e: None):
            for f in files:
                try:
                    total += os.lstat(os.path.join(dirpath, f)).st_size
                except OSError:
                    pass
            if time.monotonic() > deadline:
                break
        sizes.append((total, child.name))
    if sizes:
        lines.append("Biggest folders in your home folder:")
        lines += [f"  {_gb(s):>9}  {n}" for s, n in sorted(sizes, reverse=True)[:12]]
    return "\n".join(lines)


def network() -> str:
    lines = []
    try:
        socket.create_connection(("1.1.1.1", 443), timeout=4).close()
        lines.append("Internet: reachable")
    except OSError as e:
        lines.append(f"Internet: NOT reachable ({e})")
    try:
        socket.getaddrinfo("example.com", 443)
        lines.append("DNS: working")
    except OSError as e:
        lines.append(f"DNS: NOT working ({e})")
    if SYSTEM == "Windows":
        lines.append(_ps("Get-NetIPConfiguration | Select-Object InterfaceAlias, IPv4Address, IPv4DefaultGateway, "
                         "DNSServer | Format-List | Out-String -Width 160"))
    elif SYSTEM == "Linux":
        lines.append(_run(["ip", "-brief", "address"]) or _run(["ifconfig"]))
        nm = _run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"])
        if nm:
            lines.append(nm)
    else:
        lines.append(_run(["ifconfig"])[:3000])
    return "\n".join(x for x in lines if x)


def processes() -> str:
    if SYSTEM == "Windows":
        return _ps("Get-Process | Sort-Object CPU -Descending | Select-Object -First 15 Name, Id, "
                   "@{n='CPU(s)';e={[int]$_.CPU}}, @{n='Memory(MB)';e={[int]($_.WorkingSet64/1MB)}} | "
                   "Format-Table -AutoSize | Out-String -Width 160")
    out = _run(["ps", "-eo", "pid,pcpu,pmem,comm", "--sort=-pcpu"]) if SYSTEM == "Linux" else \
        _run(["ps", "-Aro", "pid,pcpu,pmem,comm"])
    return "\n".join(out.splitlines()[:16])


def updates() -> str:
    if SYSTEM == "Windows":
        return _ps("$s=New-Object -ComObject Microsoft.Update.Session; $r=$s.CreateUpdateSearcher().Search('IsInstalled=0'); "
                   "if ($r.Updates.Count -eq 0) { 'Windows is up to date' } else { $r.Updates | ForEach-Object { $_.Title } }", 120)
    if SYSTEM == "Darwin":
        return _run(["softwareupdate", "-l"], 120)
    for argv in (["apt", "list", "--upgradable"], ["dnf", "check-update", "-q"], ["pacman", "-Qu"], ["zypper", "-q", "lu"]):
        if shutil.which(argv[0]):
            out = _run(argv, 60)
            return out[:4000] or "no pending updates"
    return "no known package manager found"


def check(sections: list[str] | None = None) -> str:
    parts = []
    for name in sections or ["overview"]:
        if name == "overview":
            text, warnings = overview()
            parts.append("## overview\n" + text + ("\nWarnings:\n- " + "\n- ".join(warnings) if warnings else "\nNo warnings."))
        elif name in SECTIONS:
            parts.append(f"## {name}\n" + (globals()[name]() or "(nothing found)"))
    return "\n\n".join(parts)


def snapshot() -> dict:
    """The Care page's dashboard: quick facts and warnings (no slow checks)."""
    text, warnings = overview()
    mem = _memory()
    return {"system": SYSTEM, "os": _os_name(), "host": socket.gethostname(), "uptime": _uptime(),
            "cpus": os.cpu_count(), "shell": shell_name(),
            "memory": {"total": mem[0], "free": mem[1]} if mem else None,
            "disks": [{"mount": m, "total": t, "free": f} for m, t, f in _disks()],
            "load": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
            "warnings": warnings, "text": text}
