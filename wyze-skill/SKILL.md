# Wyze Camera Skill

Control and monitor Wyze cameras. View events, check status, turn cameras on/off, and download event clips.

## Setup

### 1. Install Dependencies

```bash
pip3 install wyze-sdk
```

### 2. Authenticate

```bash
python3 ~/.claude/skills/wyze-skill/wyze_skill.py setup YOUR_EMAIL YOUR_PASSWORD
```

If you have 2FA enabled:

```bash
python3 ~/.claude/skills/wyze-skill/wyze_skill.py verify YOUR_CODE
```

### 3. Verify Setup

```bash
python3 ~/.claude/skills/wyze-skill/wyze_skill.py cameras
```

## Commands

### List Cameras

```bash
python3 ~/.claude/skills/wyze-skill/wyze_skill.py cameras
```

### List All Devices

```bash
python3 ~/.claude/skills/wyze-skill/wyze_skill.py devices
```

### Get Camera Status

```bash
python3 ~/.claude/skills/wyze-skill/wyze_skill.py status "Garage"
python3 ~/.claude/skills/wyze-skill/wyze_skill.py status  # All cameras
```

### Get Snapshot/Thumbnail

```bash
python3 ~/.claude/skills/wyze-skill/wyze_skill.py snapshot "Garage"
```

**Note:** Wyze API provides thumbnails from the last motion event rather than live snapshots. For live streaming, consider enabling RTSP on your camera.

### Check Recent Events

```bash
python3 ~/.claude/skills/wyze-skill/wyze_skill.py events
python3 ~/.claude/skills/wyze-skill/wyze_skill.py events --camera "Garage" --hours 12 --limit 10
```

### Download Event Video

```bash
python3 ~/.claude/skills/wyze-skill/wyze_skill.py download
python3 ~/.claude/skills/wyze-skill/wyze_skill.py download --camera "Garage"
```

Saves video to `~/.claude/skills/wyze-skill/snapshots/`

### Turn Camera On/Off

```bash
python3 ~/.claude/skills/wyze-skill/wyze_skill.py on "Garage"
python3 ~/.claude/skills/wyze-skill/wyze_skill.py off "Garage"
```

## Output

All commands return JSON:

```json
{
  "cameras": [
    {
      "name": "Garage Cam",
      "mac": "AABBCCDD1122",
      "model": "WYZE_CAKP2JFUS",
      "is_online": true
    }
  ],
  "count": 1
}
```

## Limitations

- **Live Snapshots:** Wyze API doesn't support on-demand live snapshots. Use RTSP firmware for live streaming.
- **Event Storage:** Event video clips require Cam Plus subscription for cloud storage.
- **Rate Limits:** Wyze API has rate limits; avoid excessive polling.

## RTSP for Live Streaming

Some Wyze cameras support RTSP firmware for direct video streaming:

1. Flash RTSP firmware via Wyze app (if available for your model)
2. Get RTSP URL from camera settings
3. Use VLC or ffmpeg to capture frames:

```bash
ffmpeg -i "rtsp://USER:PASS@CAMERA_IP/live" -vframes 1 snapshot.jpg
```

## Security Notes

- Credentials stored locally in `~/.claude/skills/wyze-skill/credentials.json`
- Tokens auto-refresh when possible
- Password stored only if token refresh fails repeatedly

## Troubleshooting

### "Not authenticated" Error
Run setup again with your credentials.

### 2FA Required
Complete the verify step with your 2FA code.

### Rate Limited
Wait a few minutes and try again. Avoid rapid repeated calls.

### Camera Not Found
Camera names are partial matches (case-insensitive). Run `cameras` to see exact names.

#wyze #cameras #security #smart-home
