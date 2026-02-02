---
name: linear-skill
description: Read and manage Linear issues, projects, and cycles. Use when the user asks to check Linear, view issues, find tasks, check sprint status, or manage work items. Helps inform daily standups and work planning.
allowed-tools: Bash, Read
---

# Linear Skill - Issue & Project Management

Read, search, and manage Linear issues. Access teams, cycles, and projects to inform daily work.

## First-Time Setup (~2 minutes)

### 1. Create a Personal API Key

1. Go to [Linear Settings](https://linear.app/settings/api)
2. Or: Settings > Account > Security & Access > Personal API keys
3. Click **Create key**
4. Name it (e.g., "Claude Assistant")
5. Select permissions: **Read** (minimum), or **Read + Write** for full access
6. Click **Create** and copy the key (starts with `lin_api_`)

### 2. Save API Key

Create the config file:
```bash
echo '{"api_key": "lin_api_YOUR_KEY_HERE"}' > ~/.claude/skills/linear-skill/config.json
```

## Commands

### My Issues (Assigned to Me)

```bash
python3 ~/.claude/skills/linear-skill/linear_skill.py my-issues [--limit N] [--status STATUS]
```

Shows issues assigned to you, perfect for daily standup prep.

### List Teams

```bash
python3 ~/.claude/skills/linear-skill/linear_skill.py teams
```

### Team Issues

```bash
python3 ~/.claude/skills/linear-skill/linear_skill.py issues TEAM [--limit N] [--status STATUS] [--priority PRIORITY]
```

**Arguments:**
- `TEAM` - Team key (e.g., `ENG`, `EPO`) or team name
- `--status` / `-s` - Filter by status: `backlog`, `todo`, `in_progress`, `done`, `canceled`
- `--priority` / `-p` - Filter by priority: `urgent`, `high`, `medium`, `low`, `none`
- `--limit` / `-l` - Number of issues (default: 20)

### Get Issue Details

```bash
python3 ~/.claude/skills/linear-skill/linear_skill.py issue ISSUE_ID
```

`ISSUE_ID` can be the issue identifier (e.g., `EPO-123`) or the UUID.

### Current Cycle (Sprint)

```bash
python3 ~/.claude/skills/linear-skill/linear_skill.py cycle TEAM
```

Shows the active cycle/sprint for a team with progress stats.

### List Cycles

```bash
python3 ~/.claude/skills/linear-skill/linear_skill.py cycles TEAM [--limit N]
```

### Search Issues

```bash
python3 ~/.claude/skills/linear-skill/linear_skill.py search "query" [--limit N]
```

### Create Issue

```bash
python3 ~/.claude/skills/linear-skill/linear_skill.py create TEAM --title "Title" [--description "Desc"] [--priority PRIORITY] [--project PROJECT]
```

**Arguments:**
- `TEAM` - Team key (e.g., `EPO`)
- `--title` / `-t` - Issue title (required)
- `--description` / `-d` - Issue description
- `--priority` / `-p` - Priority: `urgent`, `high`, `medium`, `low`, `none`
- `--project` - Project name to assign issue to

### Update Issue

```bash
python3 ~/.claude/skills/linear-skill/linear_skill.py update ISSUE_ID [--status STATUS] [--project PROJECT]
```

**Arguments:**
- `ISSUE_ID` - Issue identifier (e.g., `EPO-123`)
- `--status` / `-s` - New status
- `--project` - Move issue to a different project

### Reorder Issues

```bash
python3 ~/.claude/skills/linear-skill/linear_skill.py reorder ISSUE1 ISSUE2 ISSUE3...
```

Reorder issues within their lane by setting `sortOrder`. Issues are listed in priority order (first = top of list).

**Arguments:**
- `ISSUE1 ISSUE2...` - Issue identifiers in desired order
- `--base` - Starting sortOrder value (default: 0.0)
- `--increment` - Increment between issues (default: 1.0)

**Example:**
```bash
# Reorder In Progress lane: EPO-485 at top, then EPO-480, then EPO-397
python3 ~/.claude/skills/linear-skill/linear_skill.py reorder EPO-485 EPO-480 EPO-397
```

### List Projects

```bash
python3 ~/.claude/skills/linear-skill/linear_skill.py projects [TEAM]
```

## Workflow Examples

### Morning Standup Prep
```bash
# See what's assigned to you
python3 ~/.claude/skills/linear-skill/linear_skill.py my-issues --status in_progress

# Check current sprint status
python3 ~/.claude/skills/linear-skill/linear_skill.py cycle EPO
```

### Check Team Backlog
```bash
python3 ~/.claude/skills/linear-skill/linear_skill.py issues EPO --status todo --priority high
```

### Find Specific Work
```bash
python3 ~/.claude/skills/linear-skill/linear_skill.py search "authentication bug"
```

### Quick Issue Creation
```bash
python3 ~/.claude/skills/linear-skill/linear_skill.py create EPO --title "Fix login timeout" --priority high
```

### Create Issue in Project
```bash
python3 ~/.claude/skills/linear-skill/linear_skill.py create EPO --title "New feature" --project "Zerg AI Platform"
```

### Move Issue to Project
```bash
python3 ~/.claude/skills/linear-skill/linear_skill.py update EPO-123 --project "Zerg AI Platform"
```

## Output

All commands output JSON for easy parsing. Issue output includes:
- `identifier` - e.g., `EPO-123`
- `title`
- `status` - Current workflow state
- `priority` - 0 (none) to 1 (urgent)
- `assignee` - Who it's assigned to
- `cycle` - Sprint/cycle info if applicable
- `labels` - Applied labels
- `estimate` - Story points if set

## Status Values

Linear workflow states map to these common statuses:
- `backlog` - Not yet planned
- `todo` - Planned but not started
- `in_progress` - Currently being worked on
- `in_review` - Under review
- `done` - Completed
- `canceled` - Won't do

## Priority Values

- `urgent` (1) - Drop everything
- `high` (2) - Important
- `medium` (3) - Normal
- `low` (4) - Nice to have
- `none` (0) - No priority set

## Requirements

No external dependencies - uses Python standard library only.

## Security Notes

- API keys don't expire but can be revoked from Linear settings
- Token stored locally in `~/.claude/skills/linear-skill/config.json`
- Revoke access: Settings > Account > Security & Access > Personal API keys

## Sources

- [Linear API Docs](https://linear.app/developers)
- [GraphQL Reference](https://linear.app/developers/graphql)
- [Filtering](https://linear.app/developers/filtering)
