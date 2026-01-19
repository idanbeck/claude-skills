---
name: gcal-skill
description: Read, create, and manage Google Calendar events. Use when the user asks to check calendar, view schedule, find meetings, create events, or see what's on the agenda. Supports multiple accounts.
allowed-tools: Bash, Read
---

# Google Calendar Skill - Calendar & Events

Read, create, and manage Google Calendar events. View agenda, create meetings, check availability.

## CRITICAL: Event Creation Confirmation Required

**Before creating ANY calendar event, you MUST get explicit user confirmation.**

When the user asks to create an event:
1. First, show them the complete event details:
   - Title
   - Start time
   - End time
   - Location (if any)
   - Attendees (if any)
2. Ask: "Do you want me to create this event?"
3. ONLY run the create command AFTER the user explicitly confirms

## First-Time Setup

This skill reuses credentials from gmail-skill if available. Otherwise:

1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Enable **Google Calendar API** (APIs & Services -> Library)
3. Use existing OAuth client or create new Desktop app client
4. Download JSON -> save as `~/.claude/skills/gcal-skill/credentials.json`

Then just run any command - browser opens for auth.

## Commands

### Today's Events

```bash
python3 ~/.claude/skills/gcal-skill/gcal_skill.py today [--account EMAIL]
```

### This Week's Events

```bash
python3 ~/.claude/skills/gcal-skill/gcal_skill.py week [--account EMAIL]
```

### Agenda (N days)

```bash
python3 ~/.claude/skills/gcal-skill/gcal_skill.py agenda --days 14 [--account EMAIL]
```

### Get Event Details

```bash
python3 ~/.claude/skills/gcal-skill/gcal_skill.py event EVENT_ID [--account EMAIL]
```

### Create Event (Requires Confirmation)

```bash
python3 ~/.claude/skills/gcal-skill/gcal_skill.py create \
  --title "Meeting with John" \
  --start "2026-01-20 14:00" \
  --end "2026-01-20 15:00" \
  --location "Zoom" \
  --attendees "john@example.com,jane@example.com" \
  [--account EMAIL]
```

**Required arguments:**
- `--title` / `-t` - Event title
- `--start` / `-s` - Start time (various formats supported)

**Optional arguments:**
- `--end` / `-e` - End time (defaults to 1 hour after start)
- `--location` / `-l` - Event location
- `--description` / `-d` - Event description
- `--attendees` - Comma-separated attendee emails
- `--account` / `-a` - Calendar account

**Time formats supported:**
- `2026-01-20 14:00`
- `2026-01-20 2:00 PM`
- `14:00` (today at that time)
- `2:00 PM` (today at that time)

### Delete Event

```bash
python3 ~/.claude/skills/gcal-skill/gcal_skill.py delete EVENT_ID [--account EMAIL]
```

### Search Events

```bash
python3 ~/.claude/skills/gcal-skill/gcal_skill.py search "query" [--max-results N] [--account EMAIL]
```

### List Calendars

```bash
python3 ~/.claude/skills/gcal-skill/gcal_skill.py calendars [--account EMAIL]
```

### Manage Accounts

```bash
# List authenticated accounts
python3 ~/.claude/skills/gcal-skill/gcal_skill.py accounts

# Remove an account
python3 ~/.claude/skills/gcal-skill/gcal_skill.py logout --account EMAIL
```

## Multi-Account Support

Add accounts by using `--account` with a new email:

```bash
# First account (auto-authenticates)
python3 ~/.claude/skills/gcal-skill/gcal_skill.py today

# Add work account
python3 ~/.claude/skills/gcal-skill/gcal_skill.py today --account work@company.com

# Use specific account
python3 ~/.claude/skills/gcal-skill/gcal_skill.py week --account personal@gmail.com
```

## Examples

### Check what's on today

```bash
python3 ~/.claude/skills/gcal-skill/gcal_skill.py today
```

### Look at the week ahead

```bash
python3 ~/.claude/skills/gcal-skill/gcal_skill.py week
```

### Find all meetings with "standup"

```bash
python3 ~/.claude/skills/gcal-skill/gcal_skill.py search "standup"
```

### Schedule a meeting

```bash
python3 ~/.claude/skills/gcal-skill/gcal_skill.py create \
  --title "1:1 with Sarah" \
  --start "2026-01-21 10:00" \
  --end "2026-01-21 10:30"
```

## Output

All commands output JSON for easy parsing.

## Requirements

- Python 3.9+
- `pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client requests`

## Security Notes

- Tokens stored locally in `~/.claude/skills/gcal-skill/tokens/`
- Revoke access anytime: https://myaccount.google.com/permissions
- Event creation always requires user confirmation
