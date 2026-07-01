---
name: zep-cli
description: Use when operating the ZeP (Ze Experiments Platform) through its first-party `zep` CLI — authenticating (local or "Sign in with Zerg" SSO), minting/listing/revoking scoped API tokens, inspecting experiments/runs/datasets/backends, submitting runs, and reading the integration API discovery doc.
---

# ZeP CLI

Use the `zep` CLI instead of scraping the ZeP web UI when you need to inspect or operate experiments, runs, datasets, scrapers, backends, storage, or API tokens.

## Defaults

- Run from `/Users/idanbeck/zerg-ze/ze` (invoke with `poetry run zep ...`, or `zep ...` if installed on PATH).
- Config is `~/.zep/config.json`; environment overrides are `ZEP_API_URL`, `ZEP_TOKEN`, `ZEP_API_KEY`, `ZEP_WORKSPACE_ID`, `ZEP_CONFIG_PATH` (env wins over the saved file).
- Default API base is `http://localhost:8080`. Set once with `zep config set-api-url <url>`.
- Prefer a scoped `zep_` **API token** for automation; use `zep auth login` for interactive/operator tasks.
- Many commands accept `--json` or already print JSON; prefer JSON for scripting.

## Authenticate

Local credentials:

```bash
zep auth login you@example.com           # prompts for password
zep auth whoami
```

Sign in with Zerg (SSO against zergai.com, if enabled on the server):

```bash
zep auth login you@zergai.com --sso       # prompts for your zergai.com password
```

## Mint a scoped automation token

```bash
zep auth token create \
  --name agent \
  --workspace 1 \
  --scopes experiment:read,run:read,dataset:read,run:write \
  --expires-in-days 30
# The raw zep_... token is printed ONCE. Store it, e.g.:
export ZEP_TOKEN=zep_xxxxxxxx
```

List / revoke tokens:

```bash
zep auth token list
zep auth token revoke <id>
```

## Inspect & operate

```bash
zep discovery                 # integration API capabilities (version, scopes, resources)
zep experiments list
zep runs list
zep runs submit <experiment> --backend modal
zep datasets list
zep backends list
```

Target a specific workspace with `--workspace <id>` or `ZEP_WORKSPACE_ID`. A
workspace-pinned token ignores other workspace selections.

## Scopes

Scopes are `<resource>:<action>` (e.g. `run:read`, `experiment:write`). A
`:write` scope implies `:read`. Run `zep discovery` to see the authoritative
list and each resource's required scopes. A token can never be minted with
broader scopes than its creator holds.

## Safety

- Do NOT submit runs, cancel, or delete unless the user asks.
- Show the target workspace before any mutating command.
- Never echo a raw `zep_...` token into logs or chat; prefer `export ZEP_TOKEN=...` set out-of-band.
- For agent automation, always use a narrowly-scoped `zep_` token, never an operator session token.
