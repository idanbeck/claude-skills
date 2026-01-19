# Zmail Skill - Custom Email for Agents

Read and send email through the Zmail server at mail.zergai.com.

## Setup

Create `config.json`:

```json
{
  "api_url": "https://mail.zergai.com",
  "api_key": "your-api-key-here",
  "default_mailbox": "fake-idan@zergai.com"
}
```

## Usage

```bash
# Check server health
python zmail_skill.py health

# List inbox
python zmail_skill.py inbox
python zmail_skill.py inbox --mailbox fake-idan@zergai.com
python zmail_skill.py inbox --limit 50

# Read a message
python zmail_skill.py read 123
python zmail_skill.py read 123 --json

# Send an email
python zmail_skill.py send --to user@gmail.com --subject "Hello" --body "Message body"
python zmail_skill.py send -t user@gmail.com -s "Hello" -b "Message body"

# Reply to a message
python zmail_skill.py reply 123 --body "Thanks for your email!"

# List mailboxes
python zmail_skill.py mailboxes

# Create a new mailbox
python zmail_skill.py create-mailbox agent-2@zergai.com -d "Agent 2"

# Delete a message
python zmail_skill.py delete 123

# Get statistics
python zmail_skill.py stats
```

## Commands

| Command | Description |
|---------|-------------|
| `inbox` | List inbox messages |
| `read ID` | Read a specific message |
| `send` | Send an email |
| `reply ID` | Reply to a message |
| `mailboxes` | List all mailboxes |
| `create-mailbox` | Create a new mailbox |
| `delete ID` | Delete a message |
| `stats` | Get mailbox statistics |
| `health` | Check server health |

## Mailboxes

Each agent can have its own mailbox:
- `fake-idan@zergai.com` - Main AI assistant
- `swarm@zergai.com` - Agent swarm coordinator
- `postmaster@zergai.com` - System mailbox

## Server

The Zmail server runs on Fly.io at `mail.zergai.com`:
- Receives email via SMTP (port 25)
- REST API for reading/sending (HTTPS)
- SQLite storage for messages

Server code: `~/zerg/zmail/`
