---
name: gmail-reader
description: Read and search Gmail emails and Google contacts. Use when the user asks to check email, find emails, search messages, look up contacts, or find someone's email/phone. Read-only access. Supports multiple accounts.
allowed-tools: Bash, Read
---

# Gmail Reader - Email & Contacts Access

Read and search Gmail emails and Google contacts. **Read-only** - no sending, deleting, or modifying.

## First-Time Setup (One-Time, ~2 minutes)

On first run, the script will guide you through setup. You need to create a Google Cloud OAuth client once:

1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Create a project (or select existing)
3. Enable **Gmail API** and **People API** (APIs & Services → Library)
4. Configure OAuth consent screen:
   - User Type: External
   - App name: Gmail Reader
   - Add yourself as test user
5. Create OAuth client ID:
   - Application type: **Desktop app**
   - Download JSON → save as `~/.claude/skills/gmail-reader/credentials.json`

Then just run any command - browser opens, you approve, done. Works for all your accounts.

## Commands

### Search Emails

```bash
python3 ~/.claude/skills/gmail-reader/gmail_reader.py search "query" [--max-results N] [--account EMAIL]
```

**Query examples:**
- `from:john@example.com` - from specific sender
- `subject:meeting after:2026/01/01` - subject + date
- `has:attachment filename:pdf` - with PDF attachments
- `is:unread` - unread emails
- `"exact phrase"` - exact match

### Read Email

```bash
python3 ~/.claude/skills/gmail-reader/gmail_reader.py read EMAIL_ID [--account EMAIL]
```

### List Recent Emails

```bash
python3 ~/.claude/skills/gmail-reader/gmail_reader.py list [--max-results N] [--label LABEL] [--account EMAIL]
```

### List Labels

```bash
python3 ~/.claude/skills/gmail-reader/gmail_reader.py labels [--account EMAIL]
```

### List Contacts

```bash
python3 ~/.claude/skills/gmail-reader/gmail_reader.py contacts [--max-results N] [--account EMAIL]
```

### Search Contacts

```bash
python3 ~/.claude/skills/gmail-reader/gmail_reader.py search-contacts "query" [--account EMAIL]
```

### Manage Accounts

```bash
# List all authenticated accounts
python3 ~/.claude/skills/gmail-reader/gmail_reader.py accounts

# Remove an account
python3 ~/.claude/skills/gmail-reader/gmail_reader.py logout --account user@gmail.com
```

## Multi-Account Support

Add accounts by using `--account` with a new email - browser opens for that account:

```bash
# First account (auto-authenticates)
python3 ~/.claude/skills/gmail-reader/gmail_reader.py list

# Add work account
python3 ~/.claude/skills/gmail-reader/gmail_reader.py list --account work@company.com

# Add personal account
python3 ~/.claude/skills/gmail-reader/gmail_reader.py list --account personal@gmail.com

# Use specific account
python3 ~/.claude/skills/gmail-reader/gmail_reader.py search "from:boss" --account work@company.com
```

Tokens are stored per-account in `~/.claude/skills/gmail-reader/tokens/`

## Examples

### Find unread emails from this week

```bash
python3 ~/.claude/skills/gmail-reader/gmail_reader.py search "is:unread after:2026/01/01"
```

### Read a specific email

```bash
python3 ~/.claude/skills/gmail-reader/gmail_reader.py read 18d5a3b2c1f4e5d6
```

### Find someone's contact info

```bash
python3 ~/.claude/skills/gmail-reader/gmail_reader.py search-contacts "John Smith"
```

### Check work email from personal machine

```bash
python3 ~/.claude/skills/gmail-reader/gmail_reader.py list --account work@company.com --max-results 5
```

## Output

All commands output JSON for easy parsing.

## Requirements

- Python 3.9+
- `pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client requests`

## Security Notes

- **Read-only access** - cannot send, delete, or modify
- Tokens stored locally in `~/.claude/skills/gmail-reader/tokens/`
- Revoke access anytime: https://myaccount.google.com/permissions
- Apps in "testing" mode may require re-auth every 7 days (publish app to avoid)
