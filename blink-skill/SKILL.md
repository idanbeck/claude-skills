---
name: blink-skill
description: Blink Camera Skill
---

# Blink Camera Skill

Control and monitor Blink cameras via `blinkpy` (>= 0.25.3): status, snapshots,
cloud motion clips, arm/disarm, and live view. Every command prints a single
JSON document to stdout.

## Setup

### 1. Install dependencies

```bash
pip3 install -r ~/.claude/skills/blink-skill/requirements.txt
```

### 2. Authenticate (interactive — handles 2FA in one process)

```bash
python3 ~/.claude/skills/blink-skill/blink_skill.py setup YOUR_EMAIL YOUR_PASSWORD
```

If 2FA is enabled, the tool prints `PIN sent -- enter it:` **to stderr** and
waits for you to type the PIN on stdin **in the same process**, then finishes
login and saves the refresh token. It must be one process: the OAuth CSRF token
and PKCE verifier are held in memory on the login instance, so a separate step
cannot resume the flow.

Run it in a real terminal (so `input()` can read the PIN). After success,
`credentials.json` holds the `hardware_id` + `refresh_token`; **all later runs
reuse the refresh token and never prompt.**

### `verify` (fallback only — flaky)

```bash
python3 ~/.claude/skills/blink-skill/blink_skill.py verify [PIN]
```

Prefer `setup`. `verify` re-drives login using the username/password saved in
`credentials.json`; because it triggers a **fresh** login it also triggers a
**new** PIN, so a PIN passed on the command line is usually stale. Let it prompt
interactively, or just use `setup`.

## Commands

### Inventory & status

```bash
blink_skill.py cameras            # every camera, full status
blink_skill.py networks           # sync modules + arm state
blink_skill.py status "Front"     # one camera (partial match)
blink_skill.py status             # all cameras, summary
```

Status fields (honest — no fabricated percentages):
- `battery` — string `"ok"` / `"low"` (Blink does **not** expose a %).
- `battery_voltage` — volts (raw 100ths-of-a-volt converted).
- `temperature_f`, `temperature_c`, `wifi_strength`, `sync_signal_strength`.
- `product_type`, `camera_type`, `wired` (bool), `serial`, `version`,
  `motion_enabled`, `last_record`.
- `armed` — read from the **sync module (network)**, not the camera.

### Snapshot

```bash
blink_skill.py snapshot "Front"              # CHEAP: cached image, no capture
blink_skill.py snapshot "Front" --refresh    # FRESH capture (battery cost)
```

- Default = cached: `refresh(force=True)` then writes the already-cached
  thumbnail. No new capture, no battery hit.
- `--refresh` = fresh capture: `snap_picture()` -> wait 5s -> `refresh(force=True)`
  -> save. On **battery** cams the result JSON includes
  `"warn": "fresh capture uses battery"`.
- Saved to `~/.claude/skills/blink-skill/snapshots/`.

### Cloud motion clips & video

```bash
blink_skill.py clips                                   # cloud motion clips
blink_skill.py clips --camera "Front" --limit 10
blink_skill.py clips --since "2026/07/01 00:00:00"
blink_skill.py events                                  # clips + live motion flags
blink_skill.py video "Front"                           # download last cached clip
```

- `clips` / `events` use `get_videos_metadata(since, camera="all", stop=pages)`
  for a real server-side clip list (`stop` is a page cap ~25 items/page; `--limit`
  is derived into pages and then slices the newest N).
- `--since` accepts `"YYYY/MM/DD HH:MM:SS"`; default is the last refresh time.
- `video` writes the last **cached** clip via `camera.video_to_file`; if none is
  cached it returns `{"status": "no_clip"}` (use `clips` for cloud clips).

### Arm / disarm (per network / sync module)

```bash
blink_skill.py arm                     # arm all networks
blink_skill.py arm --network "Home"    # arm one network
blink_skill.py disarm
blink_skill.py disarm --network "Home"
```

Arming is a **sync-module** operation (`sync.async_arm`), not per-camera.

### Live view

```bash
blink_skill.py liveview "Front Door"                 # wired cam, ~30s
blink_skill.py liveview "Front Door" --seconds 60
blink_skill.py liveview "Backyard" --force           # battery cam override
```

- `--seconds` default 30, **hard-capped at 300**.
- `rtsps://` result: returns the URL + an `ffplay_hint`. Playable directly for a
  short server-side window; this command does **not** proxy it.
- `immis://` result (proprietary): spins a local TCP relay
  (`init_livestream` -> `start` -> hold `--seconds` -> `stop`) and returns a
  `local_relay` `tcp://127.0.0.1:PORT`. Marked `"fragile": true` — it only
  serves while the process is alive; connect a player during the window.
- **Battery cams are refused without `--force`.** Live view drains the battery
  fast and battery cams share a rough **~98-minute lifetime** live-view budget.
  With `--force` the output still carries a loud `warn`.

## Battery safety, in one line

Default snapshots are cached (free). Only `snapshot --refresh` and `liveview`
touch the radio/capture path; on battery cams both warn, and `liveview` refuses
without `--force`.

## Output & files

- All stdout is a single JSON object. Interactive setup prompts and live-view
  relay notices go to **stderr**.
- Snapshots/videos: `~/.claude/skills/blink-skill/snapshots/`.
- Credentials: `~/.claude/skills/blink-skill/credentials.json` (chmod 600).
  It contains the OAuth `refresh_token` + `hardware_id` **and** the account
  username/password saved by blinkpy's `login_attributes` round-trip — treat the
  file as a secret.

## Troubleshooting

- **"Not authenticated"** — run `setup`.
- **"refresh token expired and 2FA is required again"** — re-run `setup`.
- **2FA didn't work** — you must complete `setup` in an interactive terminal so
  the PIN is entered in the same process. `verify` with a stale PIN will fail.
- **Camera not found** — names are partial, case-insensitive; run `cameras`.
- **immis live view failed** — expected; that path is experimental/fragile.

#blink #cameras #security #smart-home
