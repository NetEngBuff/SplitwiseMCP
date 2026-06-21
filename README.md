# SplitwiseMCP

Installation guide for the Splitwise MCP server. The MCP server implementation and app-specific documentation live in [`MCP_files/`](MCP_files/).

## What This Installs

This repo provides a local Model Context Protocol server for Splitwise. After setup, MCP clients such as Codex, Claude Code, and Claude Desktop can use Splitwise tools for expenses, friends, groups, comments, currencies, categories, notifications, and raw documented API calls.

## Fetch Splitwise Keys

You need three values before installation:

- `SPLITWISE_CONSUMER_KEY`
- `SPLITWISE_CONSUMER_SECRET`
- `SPLITWISE_API_KEY`

Get them from Splitwise:

1. Open https://secure.splitwise.com/apps
2. Sign in to Splitwise.
3. Create a new app, or open an existing app.
4. Copy the Consumer Key.
5. Copy the Consumer Secret.
6. Generate or copy the API key from the app details page.

Treat the API key like a password. The installer writes it to `.env`, and `.env` is ignored by git.

## Install

From the repo root:

```bash
chmod +x install.sh
./install.sh
```

The installer prompts for the three Splitwise values one after another, writes them to `.env`, locks the file to mode `600`, and can install dependencies into `venv`.

Manual dependency install:

```bash
python3 -m venv venv
venv/bin/python -m pip install --upgrade pip
venv/bin/python -m pip install -r requirements.txt
```

## Codex CLI Setup

Copy and paste from the repo root:

```bash
codex mcp add splitwise -- "$(pwd)/venv/bin/python" "$(pwd)/MCP_files/server.py"
```

Restart Codex or start a new Codex session.

## Claude Code CLI Setup

Copy and paste from the repo root:

```bash
claude mcp add splitwise -- "$(pwd)/venv/bin/python" "$(pwd)/MCP_files/server.py"
```

Restart Claude Code or start a new session.

## Claude Desktop Setup

Copy and paste from the repo root on macOS:

```bash
python3 - <<'PY'
import json
from pathlib import Path

root = Path.cwd().resolve()
config_path = Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
config_path.parent.mkdir(parents=True, exist_ok=True)

if config_path.exists():
    data = json.loads(config_path.read_text())
else:
    data = {}

data.setdefault("mcpServers", {})["splitwise"] = {
    "type": "stdio",
    "command": str(root / "venv/bin/python"),
    "args": [str(root / "MCP_files/server.py")],
    "env": {},
}

config_path.write_text(json.dumps(data, indent=2) + "\n")
print(f"Updated {config_path}")
PY
```

Restart Claude Desktop after updating the config.

Manual Claude Desktop JSON:

```json
{
  "mcpServers": {
    "splitwise": {
      "type": "stdio",
      "command": "/absolute/path/to/SplitwiseMCP/venv/bin/python",
      "args": ["/absolute/path/to/SplitwiseMCP/MCP_files/server.py"],
      "env": {}
    }
  }
}
```

## Verify

From the repo root:

```bash
venv/bin/python - <<'PY'
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(
        command="venv/bin/python",
        args=["MCP_files/server.py"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"{len(tools.tools)} tools registered")

asyncio.run(main())
PY
```

Expected result: `37 tools registered`.

## Project Layout

```text
.
├── README.md
├── install.sh
├── requirements.txt
├── .env.example
└── MCP_files/
    ├── README.md
    ├── server.py
    ├── interactive.py
    ├── openapi.json
    └── claude_desktop_config.example.json
```

## Security

- Never commit `.env`.
- Rotate your Splitwise API key if it is exposed.
- Mutating tools can create, update, delete, and restore Splitwise records. Use read-only tools first if you are unsure.
