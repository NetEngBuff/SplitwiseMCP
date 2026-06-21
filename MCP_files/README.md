# Splitwise MCP Server Files

This directory contains the MCP server implementation and app-specific files.

## Files

- `server.py`: MCP server entrypoint.
- `interactive.py`: optional terminal helper for manual Splitwise operations.
- `openapi.json`: bundled Splitwise API reference used while building the server.
- `claude_desktop_config.example.json`: example Claude Desktop server config.

Root-level files:

- `../install.sh`: prompts for credentials and prepares local dependencies.
- `../.env`: local credentials loaded by `server.py`.
- `../README.md`: GitHub-facing installation and client setup guide.

## Environment Loading

`server.py` loads credentials from the repo root `.env` first, then from `MCP_files/.env` as a fallback.

Required values:

```bash
SPLITWISE_CONSUMER_KEY=...
SPLITWISE_CONSUMER_SECRET=...
SPLITWISE_API_KEY=...
```

Optional values:

```bash
SPLITWISE_API_BASE_URL=https://secure.splitwise.com/api/v3.0
SPLITWISE_REQUEST_TIMEOUT_SECONDS=30
```

## Run Server

From the repo root:

```bash
venv/bin/python MCP_files/server.py
```

Normally you do not run this manually. MCP clients start it over stdio.

## Tool Layers

The server exposes two layers.

Convenience tools:

- `add_expense`
- `list_expenses`
- `delete_expense`
- `list_friends`
- `add_friend`
- `delete_friend`
- `list_groups`
- `get_group_details`
- `create_group`
- `delete_group`

Full documented API tools:

- Users: `get_current_user`, `get_user`, `update_user`
- Groups: `get_groups`, `get_group`, `create_group_full`, `undelete_group`, `add_user_to_group`, `remove_user_from_group`
- Friends: `get_friends`, `get_friend`, `create_friend`, `create_friends`
- Expenses: `get_expense`, `get_expenses`, `create_expense_full`, `update_expense_full`, `undelete_expense`
- Metadata: `get_currencies`, `get_categories`
- Comments: `get_comments`, `create_comment`, `delete_comment`
- Notifications: `get_notifications`
- Raw documented endpoints: `splitwise_api_get`, `splitwise_api_post`
- Discovery: `splitwise_api_capabilities`

## Full Expense Example

Unequal multi-user split:

```python
create_expense_full(
    description="Dinner",
    cost="120.00",
    group_id=0,
    shares=[
        {"user_id": 111, "paid_share": "120.00", "owed_share": "40.00"},
        {"user_id": 222, "paid_share": "0.00", "owed_share": "40.00"},
        {"user_id": 333, "paid_share": "0.00", "owed_share": "40.00"}
    ],
    currency_code="USD",
    details="Includes tax and tip"
)
```

Equal group split:

```python
create_expense_full(
    description="Groceries",
    cost="80.00",
    group_id=12345,
    split_equally=True
)
```

Each custom share must include:

- `paid_share`
- `owed_share`
- `user_id` or `id`, or `email` plus `first_name` and `last_name`

## Notes

- The server writes diagnostics to stderr so stdout remains valid MCP JSON-RPC.
- Raw endpoint tools only allow documented relative Splitwise API endpoints.
- The server validates obvious bad expense payloads before sending network requests.
