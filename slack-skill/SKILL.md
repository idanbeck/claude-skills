---
name: slack-skill
description: Read, search, and send Slack messages. Use when the user asks to check Slack, send messages, read channels, find conversations, or look up users. Supports multiple workspaces.
allowed-tools: Bash, Read
---

# Slack Skill - Messaging & Channels

Read, search, and send Slack messages. Access channels and DMs.

## CRITICAL: Message Sending Confirmation Required

**Before sending ANY message, you MUST get explicit user confirmation.**

When the user asks to send a Slack message:
1. First, show them the complete message details:
   - Workspace (if multiple)
   - Channel/User
   - Message text (or thread context if replying)
2. Ask: "Do you want me to send this message?"
3. ONLY run the send command AFTER the user explicitly confirms
4. NEVER send a message without this confirmation

## First-Time Setup (~3 minutes)

### 1. Create a Slack App

1. Go to [Slack API Apps](https://api.slack.com/apps)
2. Click **Create New App** → **From scratch**
3. Name it (e.g., "Claude Assistant") and select your workspace
4. Click **Create App**

### 2. Add Bot Scopes

1. In the sidebar, click **OAuth & Permissions**
2. Scroll to **Scopes** → **Bot Token Scopes**
3. Add these scopes:
   - `channels:history` - Read public channel messages
   - `channels:read` - List public channels
   - `chat:write` - Send messages
   - `groups:history` - Read private channel messages
   - `groups:read` - List private channels
   - `im:history` - Read DM messages
   - `im:read` - List DMs
   - `im:write` - Send DMs
   - `mpim:history` - Read group DM messages
   - `mpim:read` - List group DMs
   - `users:read` - List users
   - `reactions:write` - Add/remove emoji reactions
   - `search:read` - Search messages (optional)

### 3. Install to Workspace

1. Scroll up to **OAuth Tokens for Your Workspace**
2. Click **Install to Workspace**
3. Review permissions and click **Allow**
4. Copy the **Bot User OAuth Token** (starts with `xoxb-`)

### 4. Save Token

Create the config file:
```bash
echo '{"default": {"token": "xoxb-YOUR-TOKEN-HERE", "workspace": "your-workspace"}}' > ~/.claude/skills/slack-skill/config.json
```

### 5. Add Bot to Channels

The bot must be invited to channels to read/send messages:
- In Slack, go to the channel
- Type `/invite @YourBotName`

## Commands

### List Channels

```bash
python3 ~/.claude/skills/slack-skill/slack_skill.py channels [--workspace NAME]
```

### List Users

```bash
python3 ~/.claude/skills/slack-skill/slack_skill.py users [--workspace NAME]
```

### Read Channel Messages

```bash
python3 ~/.claude/skills/slack-skill/slack_skill.py read CHANNEL [--limit N] [--workspace NAME]
```

`CHANNEL` can be:
- Channel name: `#general`
- Channel ID: `C0XXXXXX`
- User for DM: `@username`

### Send Message (Requires Confirmation)

```bash
python3 ~/.claude/skills/slack-skill/slack_skill.py send CHANNEL --message "Your message" [--thread-ts TIMESTAMP] [--workspace NAME]
```

**Arguments:**
- `CHANNEL` - Channel name (`#general`), ID, or user (`@username`)
- `--message` / `-m` - Message text (required)
- `--thread-ts` / `-t` - Reply in thread (optional)
- `--workspace` / `-w` - Use specific workspace

### Search Messages

```bash
python3 ~/.claude/skills/slack-skill/slack_skill.py search "query" [--limit N] [--workspace NAME]
```

### Get Thread

```bash
python3 ~/.claude/skills/slack-skill/slack_skill.py thread CHANNEL THREAD_TS [--workspace NAME]
```

### User Info

```bash
python3 ~/.claude/skills/slack-skill/slack_skill.py user USERNAME_OR_ID [--workspace NAME]
```

### Add/Remove Emoji Reaction

```bash
python3 ~/.claude/skills/slack-skill/slack_skill.py react CHANNEL TS EMOJI [--remove] [--workspace NAME]
```

**Arguments:**
- `CHANNEL` - Channel name or ID
- `TS` - Message timestamp
- `EMOJI` - Emoji name (e.g., `eyes`, `white_check_mark`, or `:thumbsup:`)
- `--remove` / `-r` - Remove reaction instead of add

## Multi-Workspace Support

Add workspaces to `~/.claude/skills/slack-skill/config.json`:

```json
{
  "default": {
    "token": "xoxb-default-token",
    "workspace": "main-workspace"
  },
  "work": {
    "token": "xoxb-work-token",
    "workspace": "company-workspace"
  }
}
```

Use `--workspace work` to specify which workspace.

## Examples

### Check recent messages in #general
```bash
python3 ~/.claude/skills/slack-skill/slack_skill.py read "#general" --limit 10
```

### Send a message to a channel
```bash
python3 ~/.claude/skills/slack-skill/slack_skill.py send "#engineering" -m "Build completed successfully!"
```

### Reply in a thread
```bash
python3 ~/.claude/skills/slack-skill/slack_skill.py send "#general" -m "Thanks!" -t "1234567890.123456"
```

### DM someone
```bash
python3 ~/.claude/skills/slack-skill/slack_skill.py send "@john" -m "Hey, quick question..."
```

### Search for messages
```bash
python3 ~/.claude/skills/slack-skill/slack_skill.py search "deployment issue" --limit 20
```

## Output

All commands output JSON for easy parsing.

## Requirements

```bash
pip install slack_sdk
```

## Bridge Mode (Real-time Auto-Respond)

The bridge listens for incoming messages and auto-responds using Claude Code:

```bash
python3 ~/.claude/skills/slack-skill/slack_bridge.py --auto
```

### Emoji Status Feedback

When processing messages, the bridge shows status via emoji reactions:
- ⏳ `hourglass_flowing_sand` - Working on response
- ✅ `white_check_mark` - Response sent
- 👀 `eyes` - Acknowledged (read but not responding)
- 🚫 `no_entry` - User not in whitelist

### Thread Reply Handling

The bridge tracks threads it has posted to. When someone replies to a tracked thread:
1. Evaluates if a response is needed (questions, confirmations, substantial messages)
2. If responding: shows working → responds in thread → shows done
3. If not responding: adds 👀 to acknowledge the message was seen

### Bridge Setup

Requires Socket Mode. In your Slack app settings:
1. Enable **Socket Mode** under Settings
2. Create an **App-Level Token** with `connections:write` scope
3. Add the token to config as `app_token`:

```json
{
  "default": {
    "token": "xoxb-bot-token",
    "app_token": "xapp-app-level-token",
    "workspace": "your-workspace"
  }
}
```

## Security Notes

- Bot tokens don't expire but can be revoked from Slack app settings
- Token stored locally in `~/.claude/skills/slack-skill/config.json`
- Revoke access: [Your Apps](https://api.slack.com/apps) → Select app → **Revoke All Tokens**

## Sources

- [Slack Python SDK](https://github.com/slackapi/python-slack-sdk)
- [Sending Messages](https://api.slack.com/messaging/sending)
- [OAuth & Permissions](https://docs.slack.dev/authentication/installing-with-oauth/)
- [Token Types](https://api.slack.com/authentication/token-types)
