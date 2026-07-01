---
name: render-skill
description: Inspect and operate Render services, databases, deploys, env vars, and logs. Use when the user references Render hosting, asks to grab a Render database URL or env var, wants to trigger a deploy, or wants to check service / deploy status. The skill exposes service + Postgres lookups, env-var read/write, deploy triggers, and recent logs.
allowed-tools: Bash, Read
---

# Render Skill - Service & Postgres Management

Inspect and operate Render-hosted services and Postgres instances. Pull live connection strings, env vars, trigger deploys, and read recent logs without leaving the terminal.

## First-Time Setup (~1 minute)

### 1. Create a Render API key

1. Go to https://dashboard.render.com/u/settings#api-keys
2. Click **Create API Key**, name it (e.g. "Claude Assistant")
3. Copy the key (starts with `rnd_`)

### 2. Save the key

```bash
echo '{"api_key": "rnd_YOUR_KEY_HERE"}' > ~/.claude/skills/render-skill/config.json
```

The skill caches the resolved owner ID and a name→id map under
`~/.claude/skills/render-skill/cache.json` after the first call. Delete that file to force a refresh.

## Commands

All commands print JSON to stdout. Pipe to `jq` for readable output. Most accept service or database identifiers as either the Render ID (`srv-...` / `dpg-...`) **or** the human name (resolved via cache).

### Services

```bash
# List all services (filter by type/name)
python3 ~/.claude/skills/render-skill/render_skill.py services [--type web|worker|static|cron|background|private] [--name SUBSTRING] [--limit N]

# Get one service
python3 ~/.claude/skills/render-skill/render_skill.py service NAME_OR_ID

# Env vars for a service (returns key+value)
python3 ~/.claude/skills/render-skill/render_skill.py service-env NAME_OR_ID [--key KEY]

# Set an env var (queues a deploy unless --no-deploy)
python3 ~/.claude/skills/render-skill/render_skill.py service-env-set NAME_OR_ID KEY VALUE [--no-deploy]

# Recent deploys
python3 ~/.claude/skills/render-skill/render_skill.py deploys NAME_OR_ID [--limit N]

# Trigger a deploy
python3 ~/.claude/skills/render-skill/render_skill.py deploy NAME_OR_ID [--clear-cache] [--commit SHA]

# Recent logs (defaults to last 200 lines)
python3 ~/.claude/skills/render-skill/render_skill.py logs NAME_OR_ID [--limit N] [--since "10m"|"1h"|"2d"]
```

### Postgres databases

```bash
# List all Postgres instances
python3 ~/.claude/skills/render-skill/render_skill.py databases [--name SUBSTRING]

# Get one database
python3 ~/.claude/skills/render-skill/render_skill.py database NAME_OR_ID

# Get the connection string (the killer command for migrations / psql)
python3 ~/.claude/skills/render-skill/render_skill.py database-url NAME_OR_ID [--internal|--external]
```

`--internal` returns the private network URL (use from inside Render). `--external` returns the public URL (use from your laptop). Default: `--external`.

### Convenience

```bash
# Open a psql shell against a Render Postgres
python3 ~/.claude/skills/render-skill/render_skill.py psql NAME_OR_ID

# Print export statements you can eval into your shell
python3 ~/.claude/skills/render-skill/render_skill.py exports NAME_OR_ID    # for a service: prints all env vars as `export KEY=VALUE`
python3 ~/.claude/skills/render-skill/render_skill.py exports-db NAME_OR_ID # for a database: prints `export DATABASE_URL=...`
```

## Common workflows

### Pull the zergai DATABASE_URL for a migration

```bash
python3 ~/.claude/skills/render-skill/render_skill.py database-url zergai-postgres --external
# or
eval "$(python3 ~/.claude/skills/render-skill/render_skill.py exports-db zergai-postgres)"
psql "$DATABASE_URL"
```

### Pull a service env var

```bash
python3 ~/.claude/skills/render-skill/render_skill.py service-env zergai-api --key ZERGAI_SERVICE_TOKEN
```

### Set a secret then redeploy

```bash
python3 ~/.claude/skills/render-skill/render_skill.py service-env-set zergai-api SOMETHING newvalue
```

### Tail logs of the API service

```bash
python3 ~/.claude/skills/render-skill/render_skill.py logs zergai-api --limit 500 --since 30m
```

## Output format

All commands print one JSON document. On HTTP errors the skill exits non-zero and prints `{"error":..., "status":..., "body":...}`.

## Security

- API key lives in `~/.claude/skills/render-skill/config.json` (gitignored by your home dir conventions).
- Cache file (`cache.json`) only stores owner ID + service/database id↔name lookups. No secrets.
- The skill never logs env-var values to disk; it prints them to stdout only when explicitly requested.

## API reference

Render REST API docs: https://api-docs.render.com
