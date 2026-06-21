#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$ROOT_DIR/.env"
VENV_DIR="$ROOT_DIR/venv"

prompt_secret() {
  local label="$1"
  local value=""

  while [[ -z "$value" ]]; do
    printf "%s: " "$label" >&2
    IFS= read -r -s value
    printf "\n" >&2
    if [[ -z "$value" ]]; then
      printf "Value cannot be empty. Paste it again.\n" >&2
    fi
  done

  printf "%s" "$value"
}

write_env_file() {
  local consumer_key="$1"
  local consumer_secret="$2"
  local api_key="$3"

  umask 077
  cat > "$ENV_FILE" <<EOF
SPLITWISE_CONSUMER_KEY=$consumer_key
SPLITWISE_CONSUMER_SECRET=$consumer_secret
SPLITWISE_API_KEY=$api_key

# Optional
SPLITWISE_API_BASE_URL=https://secure.splitwise.com/api/v3.0
SPLITWISE_REQUEST_TIMEOUT_SECONDS=30
EOF
  chmod 600 "$ENV_FILE"
}

install_dependencies() {
  if ! command -v python3 >/dev/null 2>&1; then
    printf "python3 is required but was not found on PATH.\n" >&2
    exit 1
  fi

  if [[ ! -d "$VENV_DIR" ]]; then
    python3 -m venv "$VENV_DIR"
  fi

  "$VENV_DIR/bin/python" -m pip install --upgrade pip
  "$VENV_DIR/bin/python" -m pip install -r "$ROOT_DIR/requirements.txt"
}

print_next_steps() {
  cat <<EOF

Configured $ENV_FILE

Next steps:
1. Add this MCP server to your client.
2. Restart the client.

Codex CLI:
codex mcp add splitwise -- "$ROOT_DIR/venv/bin/python" "$ROOT_DIR/MCP_files/server.py"

Claude Code CLI:
claude mcp add splitwise -- "$ROOT_DIR/venv/bin/python" "$ROOT_DIR/MCP_files/server.py"

Claude Desktop JSON:
{
  "mcpServers": {
    "splitwise": {
      "type": "stdio",
      "command": "$ROOT_DIR/venv/bin/python",
      "args": ["$ROOT_DIR/MCP_files/server.py"],
      "env": {}
    }
  }
}
EOF
}

cat <<EOF
Splitwise MCP installer

Before continuing, fetch these values from Splitwise:
1. Open https://secure.splitwise.com/apps
2. Sign in to Splitwise.
3. Create a new app, or open an existing app.
4. Copy the Consumer Key.
5. Copy the Consumer Secret.
6. Generate or copy the API key from the app details page.

Paste each value when prompted. Input is hidden while you paste.
EOF

if [[ -f "$ENV_FILE" ]]; then
  printf "\n%s already exists. Overwrite it? [y/N]: " "$ENV_FILE" >&2
  IFS= read -r overwrite_choice
  case "$overwrite_choice" in
    y|Y|yes|YES|Yes)
      ;;
    *)
      printf "Keeping existing .env. Exiting without changes.\n" >&2
      exit 0
      ;;
  esac
fi

consumer_key="$(prompt_secret "Paste SPLITWISE_CONSUMER_KEY")"
consumer_secret="$(prompt_secret "Paste SPLITWISE_CONSUMER_SECRET")"
api_key="$(prompt_secret "Paste SPLITWISE_API_KEY")"

write_env_file "$consumer_key" "$consumer_secret" "$api_key"

printf "\nInstall/update Python dependencies now? [Y/n]: " >&2
IFS= read -r install_choice
install_choice="${install_choice:-Y}"
case "$install_choice" in
  y|Y|yes|YES|Yes)
    install_dependencies
    ;;
  *)
    printf "Skipped dependency installation. Run python3 -m venv venv and pip install -r requirements.txt before using the server.\n" >&2
    ;;
esac

print_next_steps
