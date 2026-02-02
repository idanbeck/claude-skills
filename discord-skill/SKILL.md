---
name: discord-skill
description: Send messages, read channels, and manage Discord servers. Use when the user asks to send Discord messages, check Discord channels, read server messages, or manage their Discord presence. Supports bot and user authentication.
allowed-tools: Bash, Read
---

# Discord Skill - Server Messaging & Management

Send messages, read channels, and interact with Discord servers.

## CRITICAL: Message Confirmation Required

**Before sending ANY Discord message, you MUST get explicit user confirmation.**

When the user asks to send a message:
1. First, show them the complete message details:
   - Account/bot being used
   - Channel or user (for DMs)
   - Full message text
2. Ask: "Do you want me to send this Discord message?"
3. ONLY run the send command AFTER the user explicitly confirms
4. NEVER send without confirmation

## First-Time Setup

### Option 1: Bot Token (Recommended)

Best for server automation:

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click "New Application" → Name it
3. Go to "Bot" section:
   - Click "Reset Token" and copy the token
   - Enable "Message Content Intent" under Privileged Gateway Intents
4. Create `credentials.json`:
   ```json
   {
     "client_id": "YOUR_APP_CLIENT_ID",
     "client_secret": "YOUR_APP_CLIENT_SECRET",
     "bot_token": "YOUR_BOT_TOKEN"
   }
   ```
   Save to: `~/.claude/skills/discord-skill/credentials.json`

5. Invite bot to your server:
   - OAuth2 → URL Generator
   - Select scopes: `bot`
   - Select permissions: Send Messages, Read Message History, Add Reactions
   - Copy URL and open in browser to invite

6. Authenticate:
   ```bash
   python3 ~/.claude/skills/discord-skill/discord_skill.py login --bot
   ```

### Option 2: User OAuth2

For user account access (limited by Discord ToS):

1. Same app setup as above
2. Add redirect URL: `http://localhost:9997`
3. Run:
   ```bash
   python3 ~/.claude/skills/discord-skill/discord_skill.py login
   ```
4. Authorize in browser

## Commands

### Account Management

```bash
# List accounts
python3 ~/.claude/skills/discord-skill/discord_skill.py accounts

# Login with bot token
python3 ~/.claude/skills/discord-skill/discord_skill.py login --bot [--account NAME]

# Login with OAuth (user)
python3 ~/.claude/skills/discord-skill/discord_skill.py login [--account NAME]

# Logout
python3 ~/.claude/skills/discord-skill/discord_skill.py logout [--account NAME]
```

### User & Server Info

```bash
# Get current user/bot info
python3 ~/.claude/skills/discord-skill/discord_skill.py me [--account NAME]

# List servers
python3 ~/.claude/skills/discord-skill/discord_skill.py guilds [--account NAME]

# List channels in a server
python3 ~/.claude/skills/discord-skill/discord_skill.py channels GUILD_ID [--account NAME]

# List server members
python3 ~/.claude/skills/discord-skill/discord_skill.py members GUILD_ID [--limit N] [--account NAME]
```

### Messages (Requires Confirmation)

```bash
# Send message to channel
python3 ~/.claude/skills/discord-skill/discord_skill.py send CHANNEL_ID "message" [--account NAME]

# Read messages from channel
python3 ~/.claude/skills/discord-skill/discord_skill.py messages CHANNEL_ID [--limit N] [--account NAME]

# Reply to a message
python3 ~/.claude/skills/discord-skill/discord_skill.py reply CHANNEL_ID MESSAGE_ID "reply text" [--account NAME]

# Send direct message
python3 ~/.claude/skills/discord-skill/discord_skill.py dm USER_ID "message" [--account NAME]

# Search messages in server
python3 ~/.claude/skills/discord-skill/discord_skill.py search GUILD_ID "query" [--account NAME]
```

### Reactions

```bash
# Add reaction to message
python3 ~/.claude/skills/discord-skill/discord_skill.py react CHANNEL_ID MESSAGE_ID "👍" [--account NAME]
```

## Finding IDs

Discord uses snowflake IDs. Enable Developer Mode to copy them:

1. User Settings → Advanced → Developer Mode: ON
2. Right-click any server/channel/message/user → "Copy ID"

Or use the skill commands:
- `guilds` → lists server IDs
- `channels GUILD_ID` → lists channel IDs
- `messages CHANNEL_ID` → lists message IDs

## Examples

### Send a Message

```bash
# Get server list
python3 ~/.claude/skills/discord-skill/discord_skill.py guilds

# Get channels in server
python3 ~/.claude/skills/discord-skill/discord_skill.py channels 123456789012345678

# Send message
python3 ~/.claude/skills/discord-skill/discord_skill.py send 987654321098765432 "Hello from Claude!"
```

### Read Recent Messages

```bash
python3 ~/.claude/skills/discord-skill/discord_skill.py messages 987654321098765432 --limit 10
```

### Reply to Someone

```bash
python3 ~/.claude/skills/discord-skill/discord_skill.py reply 987654321098765432 111222333444555666 "Thanks for the info!"
```

### React to a Message

```bash
python3 ~/.claude/skills/discord-skill/discord_skill.py react 987654321098765432 111222333444555666 "🎉"
```

## Bot vs User Authentication

| Feature | Bot | User (OAuth) |
|---------|-----|--------------|
| Send messages | ✅ | ✅ |
| Read messages | ✅ | Limited |
| Server management | ✅ | ❌ |
| Multiple servers | ✅ | ✅ |
| Rate limits | Higher | Lower |
| ToS compliance | ✅ | Gray area |

**Recommendation**: Use bot tokens for automation.

## Output

All commands output JSON for easy parsing.

## Requirements

- Python 3.9+
- `pip install requests`

## Bot Permissions

When inviting your bot, select these permissions:
- **Send Messages** - Post in channels
- **Read Message History** - Read past messages
- **Add Reactions** - React to messages
- **View Channels** - See channel list

For more features:
- **Manage Messages** - Delete/pin messages
- **Embed Links** - Rich embeds
- **Attach Files** - Upload files

## Security Notes

- **Message confirmation required** - Claude must confirm before sending
- Bot tokens grant full bot access - keep `credentials.json` secure
- Tokens stored in `~/.claude/skills/discord-skill/tokens/`
- Revoke bot tokens in Developer Portal if compromised

## Rate Limits

Discord has strict rate limits:
- ~5 messages per 5 seconds per channel
- ~10 reactions per 10 seconds
- Bots get higher limits than users

The skill doesn't auto-retry on rate limits - space out bulk operations.
