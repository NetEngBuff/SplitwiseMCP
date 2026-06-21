# SplitwiseMCP

Installation guide for the Splitwise MCP server. The MCP server implementation and app-specific documentation live in [`MCP_files/`](MCP_files/).

## What This Installs

This repo provides a local Model Context Protocol server for Splitwise. After setup, MCP clients such as Codex, Claude Code, Claude Desktop, and ChatGPT Desktop can use Splitwise tools for expenses, friends, groups, comments, currencies, categories, notifications, and raw documented API calls.

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

Open Claude Desktop's MCP/server configuration and add this server manually.

Use this JSON, replacing `/absolute/path/to/SplitwiseMCP` with your local repo path:

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

Restart Claude Desktop after updating the config.

## ChatGPT Desktop Setup

If your ChatGPT Desktop build exposes local MCP/custom connector settings, add a new local stdio MCP server manually.

Use these values, replacing `/absolute/path/to/SplitwiseMCP` with your local repo path:

```text
Name: splitwise
Transport: stdio
Command: /absolute/path/to/SplitwiseMCP/venv/bin/python
Arguments: /absolute/path/to/SplitwiseMCP/MCP_files/server.py
Environment: leave empty
```

The server reads credentials from the repo root `.env`, so you do not need to paste Splitwise keys into ChatGPT. Restart ChatGPT Desktop after adding the server. If your ChatGPT Desktop app does not show MCP/custom connector settings, your current app/account build may not support local MCP servers yet.

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
