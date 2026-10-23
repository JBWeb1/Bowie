"""Ready-made connections to apps and tools (MCP servers). Pick one with `bowers mcp connect NAME` or the
Connect apps section in the browser; remote apps then ask you to sign in.

Addresses come from each vendor's published MCP server. If an app moves its server, edit the address in
~/.docks/mcp.json (or remove and connect it again).
"""

import os
import shutil

# auth: "oauth" (sign in through your browser), "github" (uses your connected GitHub account),
#       "token" (an API key from an environment variable), or "none".
# inputs: values asked for when connecting, put into args as {key}.
APPS = [
    # remote apps you sign in to
    {"id": "notion", "name": "Notion", "category": "Docs & knowledge", "auth": "oauth",
     "description": "Search, read and update your Notion pages and databases.",
     "spec": {"type": "http", "url": "https://mcp.notion.com/mcp"}},
    {"id": "linear", "name": "Linear", "category": "Project management", "auth": "oauth",
     "description": "Find, create and update Linear issues and projects.",
     "spec": {"type": "http", "url": "https://mcp.linear.app/mcp"}},
    {"id": "sentry", "name": "Sentry", "category": "Developer tools", "auth": "oauth",
     "description": "Look up errors and issues in Sentry while fixing bugs.",
     "spec": {"type": "http", "url": "https://mcp.sentry.dev/mcp"}},
    {"id": "stripe", "name": "Stripe", "category": "Payments", "auth": "oauth",
     "description": "Work with Stripe customers, products, payments and the docs.",
     "spec": {"type": "http", "url": "https://mcp.stripe.com"}},
    {"id": "supabase", "name": "Supabase", "category": "Databases", "auth": "oauth",
     "description": "Manage Supabase projects, tables, queries and edge functions.",
     "spec": {"type": "http", "url": "https://mcp.supabase.com/mcp"}},
    {"id": "figma", "name": "Figma", "category": "Design", "auth": "oauth",
     "description": "Read Figma designs so Bowers can build them faithfully.",
     "spec": {"type": "http", "url": "https://mcp.figma.com/mcp"}},
    {"id": "vercel", "name": "Vercel", "category": "Hosting", "auth": "oauth",
     "description": "Deployments, logs and projects on Vercel.",
     "spec": {"type": "http", "url": "https://mcp.vercel.com"}},
    {"id": "huggingface", "name": "Hugging Face", "category": "AI & data", "auth": "oauth",
     "description": "Search models, datasets and Spaces on Hugging Face.",
     "spec": {"type": "http", "url": "https://huggingface.co/mcp"}},
    {"id": "github-mcp", "name": "GitHub (full)", "category": "Developer tools", "auth": "github",
     "description": "GitHub's own MCP server: issues, PRs, Actions, code search, using your connected account.",
     "spec": {"type": "http", "url": "https://api.githubcopilot.com/mcp/", "auth": "github"}},
    # tools that run on your computer
    {"id": "filesystem", "name": "Folder access", "category": "On your computer", "auth": "none", "needs": "npx",
     "description": "Let Bowers read and write another folder outside this project.",
     "spec": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "{path}"]},
     "inputs": [{"key": "path", "label": "Folder to share", "default": "~/Documents"}]},
    {"id": "memory", "name": "Knowledge graph memory", "category": "On your computer", "auth": "none", "needs": "npx",
     "description": "A long-term memory of people, projects and facts that Bowers builds as you work.",
     "spec": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-memory"]}},
    {"id": "fetch", "name": "Web fetch", "category": "On your computer", "auth": "none", "needs": "uvx",
     "description": "Fetch web pages as clean text (useful with engines that have no web tools).",
     "spec": {"command": "uvx", "args": ["mcp-server-fetch"]}},
    {"id": "sqlite", "name": "SQLite database", "category": "Databases", "auth": "none", "needs": "uvx",
     "description": "Query and change a SQLite database file.",
     "spec": {"command": "uvx", "args": ["mcp-server-sqlite", "--db-path", "{path}"]},
     "inputs": [{"key": "path", "label": "Database file", "default": "data.db"}]},
    {"id": "time", "name": "Time zones", "category": "On your computer", "auth": "none", "needs": "uvx",
     "description": "Current times and time-zone conversions.",
     "spec": {"command": "uvx", "args": ["mcp-server-time"]}},
]


def find(app_id: str) -> dict | None:
    return next((a for a in APPS if a["id"] == app_id.lower()), None)


def missing_tool(app: dict) -> str | None:
    """The program a local app needs that isn't installed, if any."""
    needs = app.get("needs")
    if needs and not shutil.which(needs):
        return {"npx": "Node.js (for npx)", "uvx": "uv (for uvx): https://docs.astral.sh/uv/"}.get(needs, needs)
    return None


def build_spec(app: dict, values: dict | None = None) -> dict:
    values = values or {}
    spec = {k: (list(v) if isinstance(v, list) else v) for k, v in app["spec"].items()}
    for item in app.get("inputs", []):
        value = str(values.get(item["key"]) or item["default"])
        if item["key"] == "path":
            value = os.path.expanduser(value)
        spec["args"] = [a.replace("{" + item["key"] + "}", value) for a in spec.get("args", [])]
    return spec


def listing(manager=None) -> list[dict]:
    """The catalog, marked with what's connected and what needs a sign-in."""
    out, order = [], list(dict.fromkeys(a["category"] for a in APPS))
    for app in sorted(APPS, key=lambda a: order.index(a["category"])):
        server = manager.servers.get(app["id"]) if manager else None
        out.append({**{k: app[k] for k in ("id", "name", "category", "description", "auth")},
                    "inputs": app.get("inputs", []), "missing": missing_tool(app),
                    "status": server.status if server else "not-connected"})
    return out
