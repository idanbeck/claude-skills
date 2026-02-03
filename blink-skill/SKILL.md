# Blink Camera Skill

Control and monitor Blink cameras. View snapshots, check motion events, arm/disarm systems, and download video clips.

## Setup

### 1. Install Dependencies

```bash
pip3 install blinkpy
```

### 2. Authenticate

```bash
python3 ~/.claude/skills/blink-skill/blink_skill.py setup YOUR_EMAIL YOUR_PASSWORD
```

If you have 2FA enabled, you'll receive a PIN via email/SMS:

```bash
python3 ~/.claude/skills/blink-skill/blink_skill.py verify YOUR_PIN
```

### 3. Verify Setup

```bash
python3 ~/.claude/skills/blink-skill/blink_skill.py cameras
```

## Commands

### List Cameras

```bash
python3 ~/.claude/skills/blink-skill/blink_skill.py cameras
```

### List Networks/Sync Modules

```bash
python3 ~/.claude/skills/blink-skill/blink_skill.py networks
```

### Get Camera Snapshot

```bash
python3 ~/.claude/skills/blink-skill/blink_skill.py snapshot "Playground"
python3 ~/.claude/skills/blink-skill/blink_skill.py snapshot "Front Door"
```

Saves snapshot to `~/.claude/skills/blink-skill/snapshots/`

### Get Camera Status

```bash
python3 ~/.claude/skills/blink-skill/blink_skill.py status "Playground"
python3 ~/.claude/skills/blink-skill/blink_skill.py status  # All cameras
```

### Check Recent Events

```bash
python3 ~/.claude/skills/blink-skill/blink_skill.py events
python3 ~/.claude/skills/blink-skill/blink_skill.py events --camera "Playground" --limit 5
```

### Download Last Video Clip

```bash
python3 ~/.claude/skills/blink-skill/blink_skill.py video "Playground"
```

Saves video to `~/.claude/skills/blink-skill/snapshots/`

### Arm System

```bash
python3 ~/.claude/skills/blink-skill/blink_skill.py arm                    # Arm all networks
python3 ~/.claude/skills/blink-skill/blink_skill.py arm --network "Home"   # Arm specific network
```

### Disarm System

```bash
python3 ~/.claude/skills/blink-skill/blink_skill.py disarm                    # Disarm all networks
python3 ~/.claude/skills/blink-skill/blink_skill.py disarm --network "Home"   # Disarm specific network
```

## Output

All commands return JSON:

```json
{
  "cameras": [
    {
      "name": "Playground Slide",
      "type": "mini",
      "armed": true,
      "battery": "ok",
      "temperature": 72,
      "last_motion": "2026-02-02T15:30:00"
    }
  ],
  "count": 1
}
```

## Viewing Snapshots

After getting a snapshot, you can view it:

```bash
# macOS
open ~/.claude/skills/blink-skill/snapshots/Playground_Slide_20260202_153000.jpg

# Or ask Claude to read/display it
```

## Security Notes

- Credentials stored locally in `~/.claude/skills/blink-skill/credentials.json`
- No passwords stored after initial auth - only OAuth tokens
- Tokens auto-refresh when expired

## Troubleshooting

### "Not authenticated" Error
Run setup again with your credentials.

### 2FA Issues
Make sure to complete the verify step with the PIN sent to your email/phone.

### Camera Not Found
Camera names are partial matches (case-insensitive). Run `cameras` to see exact names.

#blink #cameras #security #smart-home
