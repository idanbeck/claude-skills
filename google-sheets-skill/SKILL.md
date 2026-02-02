---
name: google-sheets-skill
description: Read and write Google Sheets. Use when the user asks to read spreadsheet data, update cells, create sheets, or work with Google Sheets.
allowed-tools: Bash, Read
---

# Google Sheets Skill

Read, write, and manage Google Sheets.

## Setup

Uses same Google OAuth as gmail-skill. If you have gmail-skill configured, this will work automatically.

Otherwise:
1. Go to https://console.cloud.google.com/apis/credentials
2. Create OAuth client (Desktop app)
3. Enable Google Sheets API
4. Download JSON to `~/.claude/skills/google-sheets-skill/credentials.json`
5. Run: `python3 ~/.claude/skills/google-sheets-skill/sheets_skill.py login`

## Commands

### List & Info

```bash
# List your spreadsheets
python3 ~/.claude/skills/google-sheets-skill/sheets_skill.py list [--limit N]

# Get spreadsheet info
python3 ~/.claude/skills/google-sheets-skill/sheets_skill.py get SPREADSHEET_ID
```

### Reading Data

```bash
# Read a range
python3 ~/.claude/skills/google-sheets-skill/sheets_skill.py read SPREADSHEET_ID "Sheet1!A1:C10"

# Read entire sheet
python3 ~/.claude/skills/google-sheets-skill/sheets_skill.py read SPREADSHEET_ID "Sheet1"
```

### Writing Data

```bash
# Write to range (overwrites)
python3 ~/.claude/skills/google-sheets-skill/sheets_skill.py write SPREADSHEET_ID "Sheet1!A1" --values '[["Header1","Header2"],["Row1","Data"]]'

# Append rows
python3 ~/.claude/skills/google-sheets-skill/sheets_skill.py append SPREADSHEET_ID "Sheet1" --values '[["New","Row"]]'

# Clear range
python3 ~/.claude/skills/google-sheets-skill/sheets_skill.py clear SPREADSHEET_ID "Sheet1!A1:C10"
```

### Sheet Management

```bash
# Create new spreadsheet
python3 ~/.claude/skills/google-sheets-skill/sheets_skill.py create --title "My Spreadsheet"

# Add sheet to existing spreadsheet
python3 ~/.claude/skills/google-sheets-skill/sheets_skill.py add-sheet SPREADSHEET_ID --title "New Tab"

# Delete sheet
python3 ~/.claude/skills/google-sheets-skill/sheets_skill.py delete-sheet SPREADSHEET_ID --sheet-id 123456
```

## Range Notation

- `Sheet1!A1:C10` - Specific range
- `Sheet1!A:C` - Entire columns A-C
- `Sheet1!1:10` - Rows 1-10
- `Sheet1` - Entire sheet
- `A1:C10` - Default sheet

## Spreadsheet ID

Found in the URL: `https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit`

## Output

All commands output JSON.
