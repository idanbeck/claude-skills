---
name: zergboard-skill
description: Read and manage Zergboard workspaces, boards, cards, and the knowledge base. Use when the user asks to check Zergboard, view/search cards, create or move work items, check sprint/cycle status, invite members or guests, browse the Zergboard KB, import a board from Linear/Jira/Notion/Trello, or split a board.
allowed-tools: Bash, Read
---

# Zergboard — Boards, Cards & Knowledge Base

Zergboard is Idan's kanban/work-tracking app (Nuxt + Postgres, deployed at `https://zergboard.fly.dev`).
Repo: `~/zerg-stack/zapps/zergboard`.

There are **two interfaces**. Pick by task:

| Use | Interface | Why |
|---|---|---|
| Reads, search, "what's assigned to me", quick card create/update/move/comment | **`zergboard_skill.py`** | Resolves friendly names — board *name* or *card prefix* (`CES`), card *external id* (`CES-1`), workspace name/slug. Token already configured. |
| Admin, tokens, invites, labels, subtasks, dependencies, KB, imports, board split, workspace runs | **`zb` CLI** | Full surface. Requires UUIDs for most flags. |

Default to the Python helper for anything it covers — it takes human-readable ids, so you don't need a UUID lookup round-trip.

---

## Auth & config

**Python helper** — `~/.claude/skills/zergboard-skill/config.json` (already set up):

```json
{
  "base_url": "https://zergboard.fly.dev",
  "api_token": "zb_...",
  "default_organization_id": "<uuid>"
}
```

**`zb` CLI** — binary at `~/.claude/skills/zergboard-skill/bin/zb`. It is **not** checked into the skills repo (platform-specific, ~10 MB), so build it if missing — see *Rebuild* below.
Config file defaults to `~/.zergboard/zb.json`; env vars override it:

| Env var | Effect |
|---|---|
| `ZB_CONFIG_PATH` | Use a different config file (isolate actors/tests) |
| `ZB_BASE_URL` | Override API base URL |
| `ZB_API_TOKEN` | API-token auth (durable automation) |
| `ZB_SESSION_TOKEN` | Session auth |
| `ZB_CURRENT_ORG_ID` | Default org for commands taking `--org-id` |

Simplest path — reuse the token the Python skill already holds:

```bash
export ZB_API_TOKEN=$(python3 -c "import json;print(json.load(open('$HOME/.claude/skills/zergboard-skill/config.json'))['api_token'])")
export ZB_CURRENT_ORG_ID=<org-uuid>
~/.claude/skills/zergboard-skill/bin/zb boards --json
```

Token scopes: `org:read`, `org:write`, `org:admin`, `cards:read`, `cards:write`, `workspace:admin`.

**Rebuild** — do this if `bin/zb` is missing, and after pulling zergboard changes. Any `cli/zb/zb` sitting in the app repo is an **untracked local build artifact**, not a checked-in binary, and goes stale silently — one had lagged far enough behind source to omit the entire `kb` command group from `--help`:

```bash
cd ~/zerg-stack/zapps/zergboard/cli/zb
GOCACHE=/tmp/zb-gocache GOMODCACHE=/tmp/zb-gomodcache go build -o ~/.claude/skills/zergboard-skill/bin/zb .
```

---

## Python helper — `zergboard_skill.py`

```bash
P=~/.claude/skills/zergboard-skill/zergboard_skill.py
```

All commands print JSON.

| Command | Notes |
|---|---|
| `python3 $P my-cards [--status S] [--limit N]` | Cards assigned to me across every visible board |
| `python3 $P workspaces` | Workspaces (organizations) |
| `python3 $P boards [WORKSPACE]` | WORKSPACE = name, slug, or UUID |
| `python3 $P cards BOARD [--status S] [--priority P] [--limit N]` | BOARD = UUID, name, or card prefix (`CES`) |
| `python3 $P card CARD_ID` | CARD_ID = UUID or external id (`CES-1`) |
| `python3 $P cycle BOARD` / `cycles BOARD [--limit N]` | Active cycle / all cycles |
| `python3 $P search "query" [--workspace W] [--board B] [--limit N]` | Substring over title, description, external id |
| `python3 $P create BOARD --title T [--description D] [--priority P] [--column C] [--assignee EMAIL]` | Defaults to first column |
| `python3 $P update CARD_ID [--title] [--description] [--priority] [--due YYYY-MM-DD] [--estimate N]` | |
| `python3 $P move CARD_ID --column "In Progress" [--position 0]` | |
| `python3 $P reorder CARD1 CARD2 ...` | Same column only; first id goes top |
| `python3 $P comments CARD_ID` / `comment CARD_ID --body "..."` | |
| `python3 $P invite-guest BOARD --email E [--role viewer\|editor\|admin]` | Existing user added directly, else emailed an invite |

Status: `todo` · `in_progress` · `done` · `canceled`. Priority: `urgent` · `high` · `medium` · `low`.

---

## `zb` CLI — full surface

Add `--json` to nearly every command. `--org-id` falls back to `ZB_CURRENT_ORG_ID` / `use-org`.

### Auth & tokens
```bash
zb signup --email E --password P --full-name N     # flags: --base-url
zb login --email E --password P                    # or: --api-token '<tok>'
zb logout | zb whoami | zb version
zb token create --name automation --org-id <id> --scopes org:read,org:write [--expires-in-days N] [--activate] --json
zb token list --json
zb token revoke --token-id <id>
zb config --show | zb config --base-url <url>
```
`token create` prints the raw token **once** — capture it immediately.

### Organizations & members
```bash
zb orgs [--json]
zb use-org <org-id>
zb org members --org-id <id> --json
zb org invite --org-id <id> --email E --role admin|editor|viewer --json
zb org invite-revoke --org-id <id> --invite-id <id> --json
zb org member-role   --org-id <id> --member-id <membership-id> --role R --json
zb org member-remove --org-id <id> --member-id <membership-id> --json
zb invite accept --token '<raw-token-or-invite-link>'
```
`org member role|remove` also exist as nested forms of the same operations.

### Boards
```bash
zb boards --org-id <id> --json
zb board create --org-id <id> --name N [--description D] [--columns "Backlog,Doing,Done"] \
                [--card-prefix CES] [--board-folder-id <id>] --json
zb board show    --board-id <id> --json
zb board columns --board-id <id> --json
zb board update  --board-id <id> [--name] [--description] [--status] --json
zb board close | reopen | archive --board-id <id> --json
zb board label --board-id <id> --name backend --color '#1d4ed8' --json
```

### Board split (plan → review → apply)
```bash
zb board split plan --source-board-id <id> --targets <spec> --out split.json --json
zb board split apply --manifest split.json --confirm-reviewed [--archive-source-if-empty] --json
```
Two-step by design: `plan` writes a manifest you inspect; `apply` refuses without `--confirm-reviewed`.

### Cards
```bash
zb card create --board-id <id> (--column-id <id> | --column-name Backlog) --title T \
               [--description D] [--priority P] [--assignee-user-id <id>] [--due-at <ts>] --json
zb card move     --card-id <id> (--target-column-id <id> | --board-id <id> --target-column-name N) [--target-position N] --json
zb card transfer --card-id <id> --target-board-id <id> (--target-column-id|--target-column-name) [--target-position N] --json
zb card assign --card-id <id> --assignee-user-id <id> --json
zb card unassign --card-id <id> --json
zb card labels --card-id <id> --label-ids id1,id2 --json
zb card comment  --card-id <id> --body "..." --json
zb card comments --card-id <id> --json
zb card subtasks --card-id <id> --json
zb card subtask-create --card-id <id> --title T --json      # also: subtask create
zb card subtask-update --card-id <id> ... --json            # also: subtask update
zb card subtask-delete --card-id <id> ... --json            # also: subtask delete
zb card deps --card-id <id> --blocked-by-card-ids id1,id2 --json   # alias: dependencies
```

### Knowledge base
Reads over the `/api/nodes/*` projection. Leading positional arg (path, node id, or query) then flags.
```bash
zb kb ls [<path>] --org-id <id> [--depth 3] [--kind K] [--entity E] [--path-prefix P] --json
zb kb cat <path-or-id> [--comments N] [--no-metadata] --json
zb kb find <query> --org-id <id> [--limit N] [--kind K] [--entity E] [--path-prefix P] --json
```

### Workspace sessions & runs (agent workspaces)
```bash
zb workspace-sessions list --org-id <id> --json
zb workspace-sessions create --org-id <id> --title T [--agent A] [--branch-name B] [--repository-id <id>] [--board-id <id>]
zb workspace-runs list --session-id <id> --json
```

### Imports
```bash
zb import linear  --org-id <id> --project <url> --api-key <tok> [--board-name N]
zb import notion  --org-id <id> --database <id>  --token <tok>  [--board-name N]
zb import jira    --org-id <id> --project-key K --base-url <url> --email E --api-token <tok> [--board-name N]
zb import trello  --org-id <id> --board <id> --key <k> --token <t> [--board-name N]
```

### TUI
```bash
zb tui    # Bubble Tea terminal UI — interactive; don't launch in an automated/non-TTY context
```

---

## Guardrails

- `card assign` only accepts users in the board's organization.
- `card move --target-column-name` **requires** `--board-id` (use `--target-column-id` alone otherwise).
- Closed boards reject writes until `board reopen`.
- Org-bound API tokens stay in their org and can only mint same-org child tokens with a **subset** of their own scopes.
- `token create` shows the raw token once.
- `invite accept` takes a raw token *or* a full invite link.
- `board split apply` needs `--confirm-reviewed`.
- Cards carry a `revision` for optimistic locking — concurrent edits can 409; re-read and retry rather than looping blindly.

## Card output fields

`external_id` (`CES-1`) · `title` · `description` · `status` · `priority` · `state_kind` · `state_name` · `column_name` · `board_id` · `board_name` · `board_card_prefix` · `organization_id` · `organization_name`

## Repo pointers

- App: `~/zerg-stack/zapps/zergboard` (Nuxt 3 + Postgres, Fly.io)
- CLI source: `cli/zb` (Go + Bubble Tea) — `cli/zb/internal/api/` is the request layer
- Docs: `docs/cli.md`, `docs/api.md`, `docs/architecture.md`, `docs/agentic-kb.md`
- In-repo agent skill: `skills/zergboard-cli/SKILL.md`
- Thin wrapper (smaller verb surface): `node scripts/zb_skill.mjs <action> ...`
- E2E: `./scripts/e2e_cli.sh` (local), `./scripts/e2e_cli_live.sh` (deployed)
- CLI tests: `npm run verify:cli` (`cd cli/zb && go test ./...`)
