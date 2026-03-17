# Deployment Guide

Installation, configuration, and operational guidance for agent-memory.

## Installation Methods

### Method 1: PyPI (Recommended)

**Install from PyPI:**
```bash
pip install agent-memory-server
```

**Verify installation:**
```bash
agent-memory-server --help
```

**Run directly:**
```bash
agent-memory-server
```

### Method 2: uvx (Zero-Install)

**Run without installation:**
```bash
uvx agent-memory-server
```

**Add to Claude Code:**
```bash
claude mcp add --transport stdio agent-memory -- uvx agent-memory-server
```

### Method 3: From Source

**Clone and install in development mode:**
```bash
git clone https://github.com/khanglvm/agent-memory.git
cd agent-memory
pip install -e ".[dev]"
```

**Run from source:**
```bash
python -m agent_memory
```

### Method 4: Docker

**Build image:**
```bash
docker build -t agent-memory .
```

**Run container:**
```bash
docker run -p 8888:8888 \
  -v ~/.agent-memory:/root/.agent-memory \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  agent-memory
```

## Configuration

### Zero-Config Default

Server works immediately without configuration:
- Storage: SQLite at `~/.agent-memory/memory.db`
- Transport: stdio
- Embedding: None (recency search only)
- Consolidation: None

Start with:
```bash
agent-memory-server
```

### Configuration File

Create `~/.agent-memory/config.yaml`:

**Minimal (with embeddings):**
```yaml
embedding:
  provider: openai
  api_key: ${OPENAI_API_KEY}
  model: text-embedding-3-small

consolidation:
  provider: openai
  api_key: ${OPENAI_API_KEY}
  model: gpt-4o-mini
```

**Full Configuration:**
```yaml
storage:
  db_path: ~/.agent-memory/memory.db

embedding:
  provider: openai              # openai | ollama | none
  base_url: https://api.openai.com/v1
  api_key: ${OPENAI_API_KEY}   # Or set via env var
  model: text-embedding-3-small
  dimensions: 1536

consolidation:
  provider: openai
  base_url: https://api.openai.com/v1
  api_key: ${OPENAI_API_KEY}
  model: gpt-4o-mini
  auto_interval_minutes: 60     # 0 = manual only
  min_memories: 5               # Minimum before consolidating

server:
  transport: stdio              # stdio | http
  http_host: 127.0.0.1
  http_port: 8888
  auth_token: ${AGENT_MEMORY_AUTH_TOKEN}

ingestion:
  allowed_paths:                # Empty = disabled
    - ~/projects
    - /data/docs
  max_file_size_mb: 1
  supported_extensions:
    - .txt
    - .md
    - .json
    - .csv
    - .yaml
    - .yml
    - .xml
    - .log

log_level: INFO                 # DEBUG | INFO | WARN | ERROR
```

### Environment Variables

Override any config value with `AGENT_MEMORY_*` prefix using `__` for nesting:

```bash
# Storage
export AGENT_MEMORY_STORAGE__DB_PATH=/custom/path/memory.db

# Embedding
export AGENT_MEMORY_EMBEDDING__PROVIDER=ollama
export AGENT_MEMORY_EMBEDDING__BASE_URL=http://localhost:11434
export AGENT_MEMORY_EMBEDDING__MODEL=nomic-embed-text

# Consolidation
export AGENT_MEMORY_CONSOLIDATION__PROVIDER=ollama
export AGENT_MEMORY_CONSOLIDATION__AUTO_INTERVAL_MINUTES=30

# Server
export AGENT_MEMORY_SERVER__TRANSPORT=http
export AGENT_MEMORY_SERVER__HTTP_HOST=0.0.0.0
export AGENT_MEMORY_SERVER__HTTP_PORT=8888
export AGENT_MEMORY_AUTH_TOKEN=your-secret-token

# Logging
export AGENT_MEMORY_LOG_LEVEL=DEBUG

# Ingestion
export AGENT_MEMORY_INGESTION__ALLOWED_PATHS=/projects,/data
export AGENT_MEMORY_INGESTION__MAX_FILE_SIZE_MB=5
```

## Transport Modes

### Stdio (Default)

**How it works:**
- MCP server reads from stdin, writes to stdout
- Used by MCP clients (Claude Code, Cursor, etc.)
- No exposed port; secure by default

**Usage:**
```bash
agent-memory-server --transport stdio
```

**In Claude Code MCP config:**
```json
{
  "mcpServers": {
    "agent-memory": {
      "type": "stdio",
      "command": "agent-memory-server"
    }
  }
}
```

### HTTP (Streamable)

**How it works:**
- Async HTTP server (uvicorn)
- POST /mcp with request body
- Streaming response over HTTP/1.1
- Bearer token authentication

**Start server:**
```bash
# Localhost only (no auth required)
agent-memory-server --transport http --host 127.0.0.1 --port 8888

# Remote exposure (auth required)
AGENT_MEMORY_AUTH_TOKEN=your-secret agent-memory-server \
  --transport http --host 0.0.0.0 --port 8888
```

**Client usage:**
```bash
curl -X POST http://127.0.0.1:8888/mcp \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer your-secret" \
  -d '{"jsonrpc": "2.0", "method": "tools/call", "params": {...}}'
```

## Embedding Providers

### OpenAI

**Setup:**
```yaml
embedding:
  provider: openai
  api_key: ${OPENAI_API_KEY}
  model: text-embedding-3-small
  dimensions: 1536
```

**Models:**
- `text-embedding-3-small` (1536 dim, $0.02/M tokens)
- `text-embedding-3-large` (3072 dim, $0.13/M tokens)
- `text-embedding-ada-002` (1536 dim, legacy)

**Cost Estimate:** 5,000 memories at 200 tokens avg = ~$0.20

### Ollama (Local, Free)

**Setup:**
1. Install Ollama: https://ollama.ai
2. Pull model: `ollama pull nomic-embed-text`
3. Configure server:

```yaml
embedding:
  provider: ollama
  base_url: http://localhost:11434
  model: nomic-embed-text
  dimensions: 768
```

**Available models:**
- `nomic-embed-text` (768 dim, 274M parameters)
- `all-minilm` (384 dim, smaller)
- `all-mpnet-base-v2` (768 dim)

### None (Graceful Degradation)

**Setup:**
```yaml
embedding:
  provider: none
```

**Behavior:**
- Embedding skipped
- Search falls back to recency order
- Consolidation still works (uses LLM without clustering)

## Consolidation LLM Providers

### OpenAI

**Setup:**
```yaml
consolidation:
  provider: openai
  api_key: ${OPENAI_API_KEY}
  model: gpt-4o-mini
```

**Recommended models:**
- `gpt-4o-mini` (fast, affordable)
- `gpt-4o` (more capable, higher cost)
- `gpt-3.5-turbo` (legacy, cheaper)

### Ollama

**Setup:**
1. Pull model: `ollama pull llama3.2` (or mistral, neural-chat)
2. Configure:

```yaml
consolidation:
  provider: ollama
  base_url: http://localhost:11434
  model: llama3.2
```

### None (Manual Only)

**Setup:**
```yaml
consolidation:
  provider: none
```

**Behavior:**
- `consolidate_memories` tool unavailable
- Consolidation skipped
- Memories accumulate indefinitely

## Multi-Device Setup (Obsidian Hub-Spoke via Tailscale)

### Overview

Transform agent-memory into a centralized multi-device memory hub using Tailscale mesh networking:
- **Mac Mini** runs agent-memory as single source of truth
- **Dev Macs** connect via Tailscale and use agent-memory via HTTP MCP transport
- **iPhone** runs Obsidian with agent-memory plugin for push-only input

### Architecture

```
                    Mac Mini (Hub)
                 [agent-memory on :8888 & :8889]
                          │
          Tailscale mesh (100.x.x.x)
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
    MacBook Pro      MacBook Air        iPhone
   Claude Code       Claude Code      Obsidian
   Obsidian+Plugin   Obsidian+Plugin   +Plugin
```

### Prerequisites

1. **Tailscale Installation**
   - Install on Mac Mini: `brew install tailscale`
   - Install on dev Macs: `brew install tailscale`
   - Install on iPhone: App Store (Obsidian or Tailscale app)

2. **MagicDNS Setup**
   - Enable in Tailscale admin: https://login.tailscale.com
   - Auto-generates stable hostnames: `macmini.tail.net`, etc.

### Configuration Steps

**On Mac Mini (Hub):**
1. Start agent-memory with HTTP transport on all IPs
2. Generate TLS cert via Tailscale's certificate authority
3. Start vault API on port 8889 with HTTPS

```bash
# Start with HTTP transport
AGENT_MEMORY_SERVER__TRANSPORT=http \
AGENT_MEMORY_SERVER__HTTP_HOST=0.0.0.0 \
AGENT_MEMORY_SERVER__HTTP_PORT=8888 \
agent-memory-server

# Vault API auto-starts on 8889 (if vault.enabled=true in config)
```

**On Dev Macs:**
1. Connect to Tailscale: `tailscale up`
2. Configure Claude Code to use centralized agent-memory
3. Set auth token via environment variable

```bash
# In ~/.zshrc or equivalent
export AGENT_MEMORY_AUTH_TOKEN="your-secure-token"
```

3. Update Claude Code MCP config (`~/.claude/settings.json`):
```json
{
  "mcpServers": {
    "agent-memory": {
      "type": "http",
      "url": "https://macmini.tail:8888/mcp",
      "headers": {
        "Authorization": "Bearer ${AGENT_MEMORY_AUTH_TOKEN}"
      }
    }
  }
}
```

**On iPhone:**
1. Install Tailscale from App Store
2. Connect to same tailnet as Mac Mini
3. Enable Tailscale VPN in Settings
4. Install Obsidian from App Store
5. Install agent-memory-sync plugin
6. Configure: `https://macmini.tail:8889`, auth token

### Security Considerations

**Tailscale ACLs:**
```json
{
  "acls": [
    {
      "action": "accept",
      "src": ["tag:dev-machines"],
      "dst": ["tag:memory-server:8888", "tag:memory-server:8889"]
    }
  ],
  "tagOwners": {
    "tag:memory-server": ["autogroup:admin"],
    "tag:dev-machines": ["autogroup:admin"]
  }
}
```

**Rate Limiting:**
- Vault API limited to 100 requests/min per client
- Prevents brute force or accidental DoS

**Auth Token Rotation:**
- Support for previous token during transition
- Update all clients before removing old token

---

## Security Hardening

### 1. Bearer Token (HTTP Only)

**For remote HTTP exposure:**
```bash
AGENT_MEMORY_AUTH_TOKEN=long-random-token agent-memory-server \
  --transport http --host 0.0.0.0
```

**Generate strong token:**
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### 2. Firewall Rules

**If exposed to network:**
```bash
# Allow only your agent IPs
ufw allow from 10.0.0.5 to 0.0.0.0 port 8888
```

### 3. Ingestion Allowlist

**Prevent arbitrary file reads:**
```yaml
ingestion:
  allowed_paths:
    - ~/projects
    - /data/docs
  max_file_size_mb: 1
```

Paths outside allowlist raise `ValueError`.

### 4. API Key Management

**Never commit secrets:**
- Use `${VAR_NAME}` in config.yaml (env var reference)
- Load keys from environment only
- Use .gitignore for local configs

### 5. SQLite Protection

**Database file permissions:**
```bash
chmod 600 ~/.agent-memory/memory.db
```

## Monitoring & Observability

### Log Levels

**Set logging:**
```bash
export AGENT_MEMORY_LOG_LEVEL=DEBUG
```

**Levels (least to most verbose):**
- `ERROR` — Failures only
- `WARN` — Degraded behavior (fallbacks, retries)
- `INFO` — Normal operations (defaults)
- `DEBUG` — Detailed flow (function calls, var values)

### Log Output

Logs written to stderr with format:
```
[LEVEL] module_name: message
```

Example:
```
[INFO] agent_memory.server: Memory stored: 550e8400-e29b-41d4-a716-446655440000
[WARN] agent_memory.embedding: Embedding failed: API timeout, using recency search
[ERROR] agent_memory.storage: Database write failed: disk I/O error
```

### Health Check

**Zero-config health:**
```bash
curl -s http://127.0.0.1:8888/mcp \
  -H "Authorization: Bearer $AGENT_MEMORY_AUTH_TOKEN" \
  -d '{"jsonrpc":"2.0","method":"resources/list","id":1}'
```

Returns list of available resources if healthy.

## Running in Production

### Systemd Service

**Create `/etc/systemd/system/agent-memory.service`:**
```ini
[Unit]
Description=Agent Memory MCP Server
After=network.target

[Service]
Type=simple
User=agent-memory
WorkingDirectory=/opt/agent-memory
ExecStart=/usr/local/bin/agent-memory-server --config ~/.agent-memory/config.yaml
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment="OPENAI_API_KEY=${OPENAI_API_KEY}"
Environment="AGENT_MEMORY_AUTH_TOKEN=${AUTH_TOKEN}"

[Install]
WantedBy=multi-user.target
```

**Enable and start:**
```bash
sudo systemctl enable agent-memory
sudo systemctl start agent-memory
sudo systemctl status agent-memory
```

### Supervisor

**Create `/etc/supervisor/conf.d/agent-memory.conf`:**
```ini
[program:agent-memory]
command=/usr/local/bin/agent-memory-server --transport http --host 0.0.0.0 --port 8888
user=agent-memory
autostart=true
autorestart=true
startretries=3
startsecs=10
stopasgroup=true
stopwaitsecs=30
stdout_logfile=/var/log/agent-memory/stdout.log
stderr_logfile=/var/log/agent-memory/stderr.log
environment=OPENAI_API_KEY=%(ENV_OPENAI_API_KEY)s,AGENT_MEMORY_AUTH_TOKEN=%(ENV_AGENT_MEMORY_AUTH_TOKEN)s
```

**Manage:**
```bash
supervisorctl reread
supervisorctl update
supervisorctl status agent-memory
```

### Docker Compose

**Create `docker-compose.yml`:**
```yaml
version: '3.8'

services:
  agent-memory:
    image: agent-memory:latest
    ports:
      - "8888:8888"
    volumes:
      - agent-memory-data:/root/.agent-memory
    environment:
      AGENT_MEMORY_SERVER__TRANSPORT: http
      AGENT_MEMORY_SERVER__HTTP_HOST: 0.0.0.0
      AGENT_MEMORY_EMBEDDING__PROVIDER: openai
      AGENT_MEMORY_EMBEDDING__API_KEY: ${OPENAI_API_KEY}
      AGENT_MEMORY_CONSOLIDATION__PROVIDER: openai
      AGENT_MEMORY_CONSOLIDATION__API_KEY: ${OPENAI_API_KEY}
      AGENT_MEMORY_AUTH_TOKEN: ${AUTH_TOKEN}
    restart: always

volumes:
  agent-memory-data:
```

**Run:**
```bash
docker-compose up -d
docker-compose logs -f agent-memory
```

## Troubleshooting

### Server Won't Start

**Check permissions:**
```bash
ls -la ~/.agent-memory/
chmod 755 ~/.agent-memory
touch ~/.agent-memory/memory.db && chmod 600 ~/.agent-memory/memory.db
```

**Check Python version:**
```bash
python --version  # Must be 3.11+
```

**Check dependencies:**
```bash
pip install -e "."  # Reinstall
```

### Embedding API Errors

**OpenAI API issues:**
```bash
echo $OPENAI_API_KEY  # Verify key set
curl https://api.openai.com/v1/models -H "Authorization: Bearer $OPENAI_API_KEY"
```

**Ollama connection issues:**
```bash
curl http://localhost:11434/api/tags  # Check Ollama running
ollama pull nomic-embed-text  # Ensure model available
```

### Search Returns No Results

**Recency fallback active (no embeddings):**
```yaml
embedding:
  provider: openai  # Configure provider
```

**Empty namespace:**
```bash
# Check memories stored in correct namespace
curl -X POST http://127.0.0.1:8888/mcp \
  -d '{"method":"tools/call","params":{"name":"get_memory_stats"}}'
```

### Consolidation Hangs

**Circuit breaker active (3+ consecutive failures):**
- Check LLM provider logs
- Verify API credentials
- Reset via manual consolidation or restart

**LLM timeout:**
```bash
export AGENT_MEMORY_LOG_LEVEL=DEBUG
# Look for timeout messages
```

### Database Locked

**SQLite write lock:**
- Check for concurrent processes
- Use WAL mode (default) for better concurrency
- Restart server if needed

```bash
sqlite3 ~/.agent-memory/memory.db "PRAGMA wal_checkpoint(RESTART);"
```

## Performance Tuning

### Vector Search Speed

**Index creation (one-time):**
```bash
sqlite3 ~/.agent-memory/memory.db "CREATE INDEX idx_namespace_created ON memories(namespace, created_at);"
```

**Query optimization:**
```yaml
embedding:
  provider: openai
  model: text-embedding-3-small  # Faster than large
```

### Memory Usage

**Reduce embedding dimension:**
```yaml
embedding:
  model: text-embedding-3-small  # 1536 dim
  # vs.
  model: all-minilm              # 384 dim (Ollama)
```

**Periodic cleanup:**
```bash
# After consolidation, mark memories for cleanup
sqlite3 ~/.agent-memory/memory.db "DELETE FROM memories WHERE consolidated = 1 AND created_at < datetime('now', '-30 days');"
```

### Consolidation Performance

**Reduce batch size:**
```yaml
consolidation:
  min_memories: 10  # Consolidate only when 10+ new memories
```

**Disable auto-consolidation:**
```yaml
consolidation:
  auto_interval_minutes: 0  # Manual only
```

## Backup & Recovery

**Backup database:**
```bash
cp ~/.agent-memory/memory.db ~/.agent-memory/memory.db.backup
```

**Restore from backup:**
```bash
cp ~/.agent-memory/memory.db.backup ~/.agent-memory/memory.db
systemctl restart agent-memory
```

**Export memories (post-MVP):**
```bash
sqlite3 ~/.agent-memory/memory.db "SELECT * FROM memories;" > memories.csv
```

## Uninstall

**Remove PyPI installation:**
```bash
pip uninstall agent-memory-server
rm -rf ~/.agent-memory
```

**Remove from Claude Code:**
```bash
claude mcp remove agent-memory
```
