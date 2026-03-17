#!/bin/bash
# Quick setup for connecting a dev Mac to centralized agent-memory
set -e

MINI_URL="${1:-https://macmini.tail:8888}"
VAULT_URL="${MINI_URL%:*}:8889"

echo "=== Agent Memory Client Setup ==="
echo "MCP Server: $MINI_URL"
echo "Vault API:  $VAULT_URL"
echo ""

# Check Tailscale
if ! command -v tailscale &> /dev/null; then
  echo "ERROR: Tailscale not installed. Install from https://tailscale.com"
  exit 1
fi

if ! tailscale status > /dev/null 2>&1; then
  echo "ERROR: Tailscale not running. Start with: tailscale up"
  exit 1
fi

# Check auth token env var
if [ -z "$AGENT_MEMORY_AUTH_TOKEN" ]; then
  echo "WARNING: AGENT_MEMORY_AUTH_TOKEN not set."
  echo "Add to ~/.zshrc: export AGENT_MEMORY_AUTH_TOKEN=\"your-token\""
  echo ""
fi

# Check connectivity to vault API health endpoint
echo "Checking connectivity..."
if curl -sf "${VAULT_URL}/health" > /dev/null 2>&1; then
  echo "✓ Vault API reachable at $VAULT_URL"
else
  echo "✗ Cannot reach $VAULT_URL — check Tailscale VPN and server status"
  exit 1
fi

echo ""
echo "=== Claude Code MCP Configuration ==="
echo ""
echo "Add to ~/.claude/settings.json (global) or .mcp.json (per-project):"
echo ""
cat <<JSONEOF
{
  "mcpServers": {
    "agent-memory": {
      "type": "http",
      "url": "${MINI_URL}/mcp",
      "headers": {
        "Authorization": "Bearer \${AGENT_MEMORY_AUTH_TOKEN}"
      }
    }
  }
}
JSONEOF
echo ""
echo "Ensure AGENT_MEMORY_AUTH_TOKEN is set in your shell profile (~/.zshrc)."
echo ""
echo "=== Setup Complete ==="
