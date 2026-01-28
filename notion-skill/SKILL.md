---
name: notion-skill
description: Read Notion databases and pages. Use when the user asks to pull data from Notion, list databases, query database entries, or export Notion content for migration.
allowed-tools: Bash, Read, Write
---

# Notion Skill - Database & Page Access

Read and query Notion databases and pages. Supports multiple workspaces. Useful for data migration and export.

## First-Time Setup (~3 minutes per workspace)

### 1. Create an Internal Integration (per workspace)

1. Go to [Notion Integrations](https://www.notion.so/my-integrations)
2. Click **+ New integration**
3. Name it (e.g., "Claude Assistant")
4. Select the workspace you want to access
5. Under **Capabilities**, ensure "Read content" is enabled
6. Click **Submit**
7. Copy the **Internal Integration Secret** (starts with `ntn_` or `secret_`)

**Note:** Each Notion workspace requires its own integration. Create one integration per workspace.

### 2. Share Pages/Databases with the Integration

**Important:** Notion integrations can only access pages explicitly shared with them.

1. Open any database or page you want to access
2. Click **...** (menu) in the top right
3. Click **Add connections**
4. Search for your integration name and select it
5. Repeat for all databases/pages you need

### 3. Configure Accounts

Create `~/.claude/skills/notion-skill/config.json`:

```json
{
  "default_account": "personal",
  "accounts": {
    "personal": {
      "email": "you@gmail.com",
      "workspace": "Personal",
      "token": "ntn_..."
    },
    "work": {
      "email": "you@company.com",
      "workspace": "Company",
      "token": "ntn_..."
    }
  }
}
```

## Commands

### List Accounts

```bash
python3 ~/.claude/skills/notion-skill/notion_skill.py accounts
```

### List Databases

```bash
python3 ~/.claude/skills/notion-skill/notion_skill.py databases [-a ACCOUNT]
```

Lists all databases shared with the integration.

**Examples:**
```bash
# Use default account
python3 ~/.claude/skills/notion-skill/notion_skill.py databases

# Use specific account
python3 ~/.claude/skills/notion-skill/notion_skill.py databases -a epoch
```

### Query Database

```bash
python3 ~/.claude/skills/notion-skill/notion_skill.py query DATABASE_ID [-a ACCOUNT] [--limit N] [--filter PROPERTY:VALUE]
```

**Arguments:**
- `DATABASE_ID` - The database ID (from URL or databases command)
- `-a` / `--account` - Account/workspace to use
- `--limit` / `-l` - Number of results (default: 100)
- `--filter` / `-f` - Filter by property (e.g., `--filter "Status:Active"`)

**Example:**
```bash
python3 ~/.claude/skills/notion-skill/notion_skill.py query abc123 -a personal --limit 50
```

### Get Page

```bash
python3 ~/.claude/skills/notion-skill/notion_skill.py page PAGE_ID [-a ACCOUNT]
```

Gets a page's properties and content.

### Search

```bash
python3 ~/.claude/skills/notion-skill/notion_skill.py search "query" [-a ACCOUNT] [--type database|page]
```

**Arguments:**
- `query` - Search term
- `-a` / `--account` - Account/workspace to use
- `--type` / `-t` - Filter by type: `database` or `page`

### Export Database to JSON

```bash
python3 ~/.claude/skills/notion-skill/notion_skill.py export DATABASE_ID [-a ACCOUNT] [--output FILE]
```

Exports all entries from a database to JSON for migration.

**Arguments:**
- `DATABASE_ID` - The database to export
- `-a` / `--account` - Account/workspace to use
- `--output` / `-o` - Output file (default: stdout)

## Migration Workflow

### 1. List Accounts
```bash
python3 ~/.claude/skills/notion-skill/notion_skill.py accounts
```

### 2. Find Your Databases
```bash
python3 ~/.claude/skills/notion-skill/notion_skill.py databases -a personal
python3 ~/.claude/skills/notion-skill/notion_skill.py databases -a epoch
```

### 3. Preview Data Structure
```bash
python3 ~/.claude/skills/notion-skill/notion_skill.py query DATABASE_ID -a personal --limit 5
```

### 4. Export Full Database
```bash
python3 ~/.claude/skills/notion-skill/notion_skill.py export DATABASE_ID -a personal --output people.json
```

### 5. Migrate to Obsidian
Use the exported JSON to create pages in the vault.

## Output Format

All commands output JSON. Database entries include:
- `id` - Page ID
- `url` - Notion URL
- `created_time` - Creation timestamp
- `last_edited_time` - Last edit timestamp
- `properties` - All database properties with values

## Property Types

The skill handles these Notion property types:
- `title` - Page title
- `rich_text` - Text content
- `number` - Numeric values
- `select` - Single select
- `multi_select` - Multiple selections
- `status` - Status field
- `date` - Date/date range
- `people` - Notion users
- `email` - Email addresses
- `phone_number` - Phone numbers
- `url` - URLs
- `checkbox` - Boolean
- `relation` - Links to other databases
- `rollup` - Computed values
- `formula` - Formula results
- `files` - File attachments
- `created_time` / `last_edited_time` - Timestamps
- `created_by` / `last_edited_by` - Users

## Finding Database IDs

Database IDs can be found in the URL:
```
https://www.notion.so/workspace/DATABASE_ID?v=VIEW_ID
                         ^^^^^^^^^^^^^^^^
```

Or use the `databases` command to list all accessible databases with their IDs.

## Requirements

No external dependencies - uses Python standard library only.

## Security Notes

- Integration tokens don't expire but can be revoked
- Token stored locally in `~/.claude/skills/notion-skill/config.json`
- Config file is gitignored (contains secrets)
- Revoke access: [Notion Integrations](https://www.notion.so/my-integrations) > Delete integration

## Sources

- [Notion API Docs](https://developers.notion.com/)
- [Database API](https://developers.notion.com/reference/database)
- [Query Database](https://developers.notion.com/reference/post-database-query)
