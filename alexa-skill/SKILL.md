# Alexa Skill - Control Amazon Echo Devices

Control your Amazon Echo devices, smart home, and routines. Send announcements, notifications, and more.

## CRITICAL: Announcement Confirmation Required

**Before sending ANY announcement or notification, you MUST get explicit user confirmation.**

When the user asks to send an announcement:
1. Show them the complete message details (message, target device)
2. Ask: "Do you want me to send this announcement?"
3. ONLY run the command AFTER the user explicitly confirms

## First-Time Setup (~3 minutes)

### 1. Install Dependencies

```bash
# Python dependencies
pip3.11 install alexapy aiohttp

# Node.js dependencies (for setup)
cd ~/.claude/skills/alexa-skill && npm install
```

### 2. Run Setup

```bash
node ~/.claude/skills/alexa-skill/setup.js YOUR_EMAIL@example.com
```

This will:
1. Start a local proxy server
2. Open a browser window for Amazon login
3. Save authentication cookies locally (no password stored)

### 3. Verify Setup

```bash
python3.11 ~/.claude/skills/alexa-skill/alexa_skill.py devices
```

Should return a list of your Echo devices.

## Commands

### Send Voice Command (Most Flexible)

```bash
python3.11 ~/.claude/skills/alexa-skill/alexa_skill.py say "turn off the living room lamp"
python3.11 ~/.claude/skills/alexa-skill/alexa_skill.py say "turn on the TV and dim the lights to 50 percent"
python3.11 ~/.claude/skills/alexa-skill/alexa_skill.py say "play jazz music in the kitchen"
```

This sends any command as if you said "Alexa, ..." - supports complex multi-device commands.

### List Echo Devices

```bash
python3.11 ~/.claude/skills/alexa-skill/alexa_skill.py devices
```

### Discover Smart Home Devices

```bash
python3.11 ~/.claude/skills/alexa-skill/alexa_skill.py discover
```

### Make Announcement (with chime)

```bash
python3 ~/.claude/skills/alexa-skill/alexa_skill.py announce "Dinner is ready"
python3 ~/.claude/skills/alexa-skill/alexa_skill.py announce "Meeting in 5 minutes" --device "Office"
python3 ~/.claude/skills/alexa-skill/alexa_skill.py announce "Fire drill" --all
```

**Note:** Avoid exclamation marks (`!`) in messages - they get escaped and Alexa will say "backs" instead.

**Arguments:**
- `message` - The message to announce (required)
- `--device` / `-d` - Target device name (optional, uses first online device)
- `--all` / `-a` - Announce on all devices

### Text-to-Speech (no chime)

```bash
python3 ~/.claude/skills/alexa-skill/alexa_skill.py speak "Hello world"
python3 ~/.claude/skills/alexa-skill/alexa_skill.py speak "Welcome home" --device "Living Room"
```

### List Smart Home Devices

```bash
python3 ~/.claude/skills/alexa-skill/alexa_skill.py smart-home
```

### List Smart Home Entities (for Silent Control)

```bash
python3.11 ~/.claude/skills/alexa-skill/alexa_skill.py smart-entities
```

Returns devices with their `entity_id` needed for silent control. Use this for the two-call workflow:
1. Call `smart-entities` to get device list with IDs
2. Match the user's request to the right entity_id
3. Call `silent-control` with that entity_id

### Silent Control (No "OK" Response)

Control devices silently without Alexa saying "OK" - perfect for nighttime or when kids are sleeping.

```bash
python3.11 ~/.claude/skills/alexa-skill/alexa_skill.py silent-control ENTITY_ID --action on
python3.11 ~/.claude/skills/alexa-skill/alexa_skill.py silent-control ENTITY_ID --action off
python3.11 ~/.claude/skills/alexa-skill/alexa_skill.py silent-control ENTITY_ID --action on --brightness 50
python3.11 ~/.claude/skills/alexa-skill/alexa_skill.py silent-control ENTITY_ID --action on --color blue
```

**Arguments:**
- `ENTITY_ID` - The entity ID from `smart-entities` command (required)
- `--action` / `-a` - `on` or `off` (required)
- `--brightness` / `-b` - Brightness level 0-100 (optional)
- `--color` / `-c` - Color name like `red`, `blue`, `warm_white` (optional)

### Control Smart Home Device

```bash
python3 ~/.claude/skills/alexa-skill/alexa_skill.py control "Living Room Lights" --action on
python3 ~/.claude/skills/alexa-skill/alexa_skill.py control "Bedroom Lights" --action off
python3 ~/.claude/skills/alexa-skill/alexa_skill.py control "Desk Lamp" --action setBrightness --value 50
```

**Actions:**
- `on` - Turn on
- `off` - Turn off
- `toggle` - Toggle state
- `setBrightness` - Set brightness (use `--value 0-100`)
- `setColor` - Set color (use `--value` with color name)

### Set Volume

```bash
python3 ~/.claude/skills/alexa-skill/alexa_skill.py volume 50
python3 ~/.claude/skills/alexa-skill/alexa_skill.py volume 30 --device "Bedroom"
```

### List Routines

```bash
python3 ~/.claude/skills/alexa-skill/alexa_skill.py routines
```

### Trigger Routine

```bash
python3 ~/.claude/skills/alexa-skill/alexa_skill.py routine "Good Morning"
python3 ~/.claude/skills/alexa-skill/alexa_skill.py routine "Movie Time"
```

### Send Notification

```bash
python3 ~/.claude/skills/alexa-skill/alexa_skill.py notify "Task completed"
python3 ~/.claude/skills/alexa-skill/alexa_skill.py notify "Reminder: Call mom" --title "Reminder"
```

## Regional Support

Setup supports multiple Amazon regions:

```bash
python3 ~/.claude/skills/alexa-skill/alexa_skill.py setup --region us   # Default
python3 ~/.claude/skills/alexa-skill/alexa_skill.py setup --region uk   # amazon.co.uk
python3 ~/.claude/skills/alexa-skill/alexa_skill.py setup --region de   # amazon.de
python3 ~/.claude/skills/alexa-skill/alexa_skill.py setup --region jp   # amazon.co.jp
```

Available regions: us, uk, de, jp, ca, au, fr, it, es, br, mx, in

## Output

All commands output JSON for easy parsing:

```json
{
  "devices": [
    {
      "name": "Kitchen Echo",
      "type": "ECHO_DOT_V3",
      "online": true
    }
  ],
  "count": 1
}
```

## Troubleshooting

### "Not authenticated" Error

Run setup again:
```bash
python3 ~/.claude/skills/alexa-skill/alexa_skill.py setup
```

### 2FA Issues

If you use 2FA, make sure it's set to **authenticator app** (not SMS or email).
Go to Amazon > Account > Login & Security > Two-Step Verification and update if needed.

### Device Not Found

- Device names are case-insensitive partial matches
- Run `devices` command to see exact names
- Make sure the device is online

### Smart Home Device Not Responding

- Check if the device is reachable in the Alexa app
- Try toggling it manually first
- Some devices may not support all actions

## Requirements

```
alexapy>=1.29.0
aiohttp
```

## Security Notes

- No passwords are stored - only OAuth tokens
- Credentials are saved locally in `~/.claude/skills/alexa-skill/config.json`
- Tokens auto-refresh when expired
- To revoke access: Remove config.json and re-run setup

## Important Disclaimer

Amazon does not provide an official API for this functionality. This skill uses the same endpoints as the Alexa web app. It may stop working if Amazon changes their API.

#alexa #smart-home #echo
