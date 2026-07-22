#!/usr/bin/env python3
"""Blink Camera Skill - Control and monitor Blink cameras (blinkpy >= 0.25.3).

All commands emit a single JSON document on stdout. Interactive prompts and
human-facing warnings (setup 2FA flow only) are written to stderr so stdout
stays machine-parseable.
"""

import argparse
import asyncio
import json
import math
import os
import sys
from pathlib import Path
from datetime import datetime

try:
    import aiohttp
    from blinkpy.blinkpy import Blink
    from blinkpy.auth import Auth, BlinkTwoFARequiredError
    from blinkpy.helpers.util import json_load, json_save
except ImportError as exc:  # pragma: no cover - import guard
    print(json.dumps({
        "error": f"blinkpy/aiohttp not installed ({exc}). Run: "
                 "pip3 install -r requirements.txt"
    }))
    sys.exit(1)

CONFIG_DIR = Path(__file__).parent
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
SNAPSHOTS_DIR = CONFIG_DIR / "snapshots"

# Wired camera_type values (mains-powered; no battery to burn on captures/live).
WIRED_CAMERA_TYPES = {"mini", "doorbell"}
WIRED_PRODUCT_TYPES = {"owl", "lotus"}

# Hard ceiling for a single liveview session (seconds).
MAX_LIVEVIEW_SECONDS = 300
# Blink battery cams have a rough ~98-minute lifetime cumulative live-view budget.
BATTERY_LIVE_BUDGET_MIN = 98


def output(data):
    """Emit the single JSON result document on stdout."""
    print(json.dumps(data, indent=2, default=str))


def eprint(*msg):
    """Human-facing text to stderr (keeps stdout JSON-clean)."""
    print(*msg, file=sys.stderr, flush=True)


def is_wired(camera):
    """Return True for mains-powered cams (Mini/Doorbell), False for battery cams."""
    ctype = (getattr(camera, "camera_type", "") or "").lower()
    ptype = (getattr(camera, "product_type", "") or "").lower()
    return ctype in WIRED_CAMERA_TYPES or ptype in WIRED_PRODUCT_TYPES


def volts(raw):
    """Convert battery_voltage (100ths of a volt) to volts, or None."""
    if raw is None:
        return None
    try:
        return round(float(raw) / 100.0, 2)
    except (TypeError, ValueError):
        return None


def find_camera(blink, query):
    """Case-insensitive partial match; returns (name, camera) or (None, None)."""
    q = (query or "").lower()
    for name, cam in blink.cameras.items():
        if q in name.lower():
            return name, cam
    return None, None


def camera_arm_state(camera):
    """Arm state comes from the SYNC MODULE (network), not the camera."""
    sync = getattr(camera, "sync", None)
    if sync is None:
        return None
    try:
        return sync.arm
    except Exception:
        return None


def camera_snapshot(camera, name):
    """Full status dict for a camera."""
    return {
        "name": name,
        "camera_type": getattr(camera, "camera_type", None),
        "product_type": getattr(camera, "product_type", None),
        "wired": is_wired(camera),
        "armed": camera_arm_state(camera),
        "motion_enabled": getattr(camera, "motion_enabled", None),
        "motion_detected": getattr(camera, "motion_detected", None),
        "battery": getattr(camera, "battery", None),          # "ok" / "low" string
        "battery_voltage": volts(getattr(camera, "battery_voltage", None)),
        "temperature_f": getattr(camera, "temperature", None),
        "temperature_c": getattr(camera, "temperature_c", None),
        "wifi_strength": getattr(camera, "wifi_strength", None),
        "sync_signal_strength": getattr(camera, "sync_signal_strength", None),
        "serial": getattr(camera, "serial", None),
        "version": getattr(camera, "version", None),
        "last_record": getattr(camera, "last_record", None),
        "network": camera.sync.name if getattr(camera, "sync", None) else None,
    }


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #
async def get_blink():
    """Load saved credentials and start Blink using the refresh token.

    Returns (blink, error). Caller must close blink.auth.session when done.
    Normal runs never prompt: the persisted refresh_token + hardware_id drive
    a silent OAuth token refresh inside blink.start().
    """
    if not CREDENTIALS_FILE.exists():
        return None, ("Not authenticated. Run: python3 blink_skill.py setup "
                      "EMAIL PASSWORD")

    session = aiohttp.ClientSession()
    creds = await json_load(CREDENTIALS_FILE)
    if not creds:
        await session.close()
        return None, "credentials.json is missing or corrupt. Re-run setup."

    blink = Blink(session=session)
    blink.auth = Auth(creds, no_prompt=True, session=session)

    try:
        ok = await blink.start()
    except BlinkTwoFARequiredError:
        await session.close()
        return None, ("Saved refresh token expired and 2FA is required again. "
                      "Re-run: python3 blink_skill.py setup EMAIL PASSWORD")
    except Exception as exc:
        await session.close()
        return None, f"Login failed: {exc}"

    if not ok:
        await session.close()
        return None, "Login failed (check credentials / network)."

    # Persist any refreshed token back to disk.
    try:
        await json_save(blink.auth.login_attributes, CREDENTIALS_FILE)
        os.chmod(CREDENTIALS_FILE, 0o600)
    except Exception:
        pass

    return blink, None


async def run_with_blink(fn, args):
    """Get an authenticated Blink, run fn(blink, args), always close the session."""
    blink, error = await get_blink()
    if error:
        output({"error": error})
        return
    try:
        await fn(blink, args)
    finally:
        try:
            await blink.auth.session.close()
        except Exception:
            pass


async def cmd_setup(args):
    """Interactive login. Completes 2FA IN THIS PROCESS (csrf/verifier are
    instance-local, so a separate 'verify' run cannot resume the flow)."""
    if not args.email or not args.password:
        output({"error": "Email and password required",
                "usage": "python3 blink_skill.py setup EMAIL PASSWORD"})
        return

    session = aiohttp.ClientSession()
    blink = Blink(session=session)
    blink.auth = Auth(
        {"username": args.email, "password": args.password},
        no_prompt=True,
        session=session,
    )

    try:
        two_fa = False
        try:
            ok = await blink.start()
        except BlinkTwoFARequiredError:
            two_fa = True
            ok = False

        if two_fa:
            eprint("PIN sent -- enter it: ")
            try:
                pin = input().strip()
            except EOFError:
                output({"error": "No PIN provided on stdin. Run setup "
                                 "interactively so the PIN can be entered."})
                return
            if not pin:
                output({"error": "Empty PIN."})
                return
            # blink.send_2fa_code() completes complete_2fa_login() AND runs the
            # remaining setup (setup_post_verify) internally.
            ok = await blink.send_2fa_code(pin)
            if not ok:
                output({"error": "2FA verification failed (bad/expired PIN?)."})
                return

        if not ok:
            output({"error": "Login failed (bad credentials or network)."})
            return

        await json_save(blink.auth.login_attributes, CREDENTIALS_FILE)
        os.chmod(CREDENTIALS_FILE, 0o600)
        output({
            "status": "success",
            "message": "Blink authenticated. Refresh token saved; future "
                       "runs will not prompt.",
            "credentials_file": str(CREDENTIALS_FILE),
            "cameras": list(blink.cameras.keys()),
        })
    finally:
        try:
            await session.close()
        except Exception:
            pass


async def cmd_verify(args):
    """FALLBACK ONLY -- flaky by design.

    The OAuth CSRF token and PKCE verifier produced during login are stored on
    the in-memory Auth instance (_oauth_csrf_token / _oauth_code_verifier). A
    fresh 'verify' process cannot resume a PIN from a previous 'setup' run: it
    must trigger a NEW login (and a NEW PIN). This command therefore re-drives
    the interactive flow using the username/password saved in credentials.json.
    Prefer `setup`, which does everything in one process.
    """
    if not CREDENTIALS_FILE.exists():
        output({"error": "No credentials.json. Run setup first."})
        return

    creds = await json_load(CREDENTIALS_FILE)
    if not creds or not creds.get("username") or not creds.get("password"):
        output({"error": "credentials.json lacks username/password; a stand-"
                         "alone verify cannot re-drive login. Run: "
                         "python3 blink_skill.py setup EMAIL PASSWORD"})
        return

    session = aiohttp.ClientSession()
    blink = Blink(session=session)
    blink.auth = Auth(creds, no_prompt=True, session=session)

    try:
        two_fa = False
        try:
            ok = await blink.start()
        except BlinkTwoFARequiredError:
            two_fa = True
            ok = False

        if two_fa:
            pin = args.pin
            if not pin:
                eprint("PIN sent -- enter it: ")
                try:
                    pin = input().strip()
                except EOFError:
                    pin = None
            if not pin:
                output({"error": "2FA required but no PIN available. NOTE: a "
                                 "PIN passed on the command line is usually "
                                 "stale -- verify triggers a fresh code. Prefer "
                                 "`setup`."})
                return
            ok = await blink.send_2fa_code(pin)
            if not ok:
                output({"error": "2FA verification failed. The PIN was likely "
                                 "stale; run `setup` for an in-process flow."})
                return

        if not ok:
            output({"error": "Login failed."})
            return

        await json_save(blink.auth.login_attributes, CREDENTIALS_FILE)
        os.chmod(CREDENTIALS_FILE, 0o600)
        output({"status": "success", "message": "Verified; credentials saved."})
    finally:
        try:
            await session.close()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Inventory
# --------------------------------------------------------------------------- #
async def cmd_cameras(blink, args):
    await blink.refresh(force=True)
    cameras = [camera_snapshot(cam, name) for name, cam in blink.cameras.items()]
    output({"cameras": cameras, "count": len(cameras)})


async def cmd_networks(blink, args):
    networks = []
    for name, sync in blink.sync.items():
        networks.append({
            "name": name,
            "id": getattr(sync, "sync_id", None),
            "armed": sync.arm,
            "status": getattr(sync, "status", None),
            "camera_count": len(getattr(sync, "cameras", {}) or {}),
        })
    output({"networks": networks, "count": len(networks)})


async def cmd_status(blink, args):
    await blink.refresh(force=True)
    if args.camera:
        name, camera = find_camera(blink, args.camera)
        if not camera:
            output({"error": f"Camera '{args.camera}' not found",
                    "available": list(blink.cameras.keys())})
            return
        result = camera_snapshot(camera, name)
        result["thumbnail"] = getattr(camera, "thumbnail", None)
        output(result)
        return
    output({"cameras": [camera_snapshot(cam, name)
                        for name, cam in blink.cameras.items()]})


# --------------------------------------------------------------------------- #
# Snapshot
# --------------------------------------------------------------------------- #
async def cmd_snapshot(blink, args):
    name, camera = find_camera(blink, args.camera)
    if not camera:
        output({"error": f"Camera '{args.camera}' not found",
                "available": list(blink.cameras.keys())})
        return

    SNAPSHOTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = SNAPSHOTS_DIR / f"{name.replace(' ', '_')}_{timestamp}.jpg"

    result = {"camera": name, "timestamp": timestamp,
              "wired": is_wired(camera)}

    if args.refresh:
        # Fresh capture: costs a real capture (and battery on battery cams).
        result["mode"] = "fresh"
        if not is_wired(camera):
            result["warn"] = "fresh capture uses battery"
        await camera.snap_picture()
        await asyncio.sleep(5)
        await blink.refresh(force=True)
    else:
        # Cheap: just re-read the already-cached thumbnail. No capture.
        result["mode"] = "cached"
        await blink.refresh(force=True)

    await camera.image_to_file(str(filepath))
    result["status"] = "success"
    result["snapshot"] = str(filepath)
    output(result)


# --------------------------------------------------------------------------- #
# Arm / Disarm  (per SYNC MODULE / network)
# --------------------------------------------------------------------------- #
async def _set_arm(blink, network, value):
    label = "armed" if value else "disarmed"
    if network:
        q = network.lower()
        for name, sync in blink.sync.items():
            if q in name.lower():
                await sync.async_arm(value)
                output({"status": "success", "network": name, "armed": value})
                return
        output({"error": f"Network '{network}' not found",
                "available": list(blink.sync.keys())})
        return
    touched = []
    for name, sync in blink.sync.items():
        await sync.async_arm(value)
        touched.append(name)
    output({"status": "success", "message": f"All networks {label}",
            "networks": touched})


async def cmd_arm(blink, args):
    await _set_arm(blink, args.network, True)


async def cmd_disarm(blink, args):
    await _set_arm(blink, args.network, False)


# --------------------------------------------------------------------------- #
# Cloud clips (motion events) + last-clip download
# --------------------------------------------------------------------------- #
def _normalize_clip(item):
    """Trim a video-metadata dict to the useful fields (robust to schema drift)."""
    if not isinstance(item, dict):
        return {"raw": item}
    return {
        "id": item.get("id"),
        "created_at": item.get("created_at"),
        "camera": item.get("device_name") or item.get("camera_name")
                  or item.get("name"),
        "network": item.get("network_name"),
        "type": item.get("type") or item.get("source"),
        "media": item.get("media"),
        "thumbnail": item.get("thumbnail"),
        "watched": item.get("watched"),
        "deleted": item.get("deleted"),
    }


async def _list_clips(blink, since, camera_filter, limit):
    """Shared cloud-clip lister via blink.get_videos_metadata()."""
    # get_videos_metadata stop = page cap (~25 items/page). Derive pages from limit.
    pages = max(2, math.ceil((limit or 25) / 25) + 1)
    raw = await blink.get_videos_metadata(since=since, camera="all", stop=pages)
    clips = [_normalize_clip(x) for x in (raw or [])]
    if camera_filter:
        cf = camera_filter.lower()
        clips = [c for c in clips
                 if c.get("camera") and cf in str(c["camera"]).lower()]
    # Newest first.
    clips.sort(key=lambda c: c.get("created_at") or "", reverse=True)
    if limit:
        clips = clips[:limit]
    return clips


async def cmd_clips(blink, args):
    """List cloud motion clips from the Blink servers."""
    clips = await _list_clips(blink, args.since, args.camera, args.limit)
    output({"clips": clips, "count": len(clips),
            "since": args.since or "last_refresh"})


async def cmd_events(blink, args):
    """Recent motion: real cloud clip list plus live per-camera motion flags."""
    await blink.refresh(force=True)
    clips = await _list_clips(blink, args.since, args.camera, args.limit)

    live = []
    for name, cam in blink.cameras.items():
        if args.camera and args.camera.lower() not in name.lower():
            continue
        live.append({
            "camera": name,
            "motion_detected": getattr(cam, "motion_detected", None),
            "last_record": getattr(cam, "last_record", None),
            "thumbnail": getattr(cam, "thumbnail", None),
        })
    output({"clips": clips, "clip_count": len(clips), "live_motion": live})


async def cmd_video(blink, args):
    """Download the last cached video clip for one camera."""
    name, camera = find_camera(blink, args.camera)
    if not camera:
        output({"error": f"Camera '{args.camera}' not found",
                "available": list(blink.cameras.keys())})
        return

    await blink.refresh(force=True)
    SNAPSHOTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = SNAPSHOTS_DIR / f"{name.replace(' ', '_')}_{timestamp}.mp4"

    await camera.video_to_file(str(filepath))

    if not filepath.exists() or filepath.stat().st_size == 0:
        # video_to_file logs and returns when no cached clip exists.
        try:
            filepath.unlink()
        except OSError:
            pass
        output({"status": "no_clip", "camera": name,
                "message": "No cached video clip available for this camera. "
                           "Use `clips` to list cloud clips."})
        return

    output({"status": "success", "camera": name, "video": str(filepath),
            "timestamp": timestamp})


# --------------------------------------------------------------------------- #
# Live view
# --------------------------------------------------------------------------- #
async def cmd_liveview(blink, args):
    name, camera = find_camera(blink, args.camera)
    if not camera:
        output({"error": f"Camera '{args.camera}' not found",
                "available": list(blink.cameras.keys())})
        return

    wired = is_wired(camera)
    if not wired and not args.force:
        output({
            "error": "Refusing live view on a BATTERY camera without --force.",
            "camera": name,
            "warn": (f"Battery cams share a rough ~{BATTERY_LIVE_BUDGET_MIN}-"
                     "minute lifetime live-view budget and live view drains "
                     "the battery fast. Re-run with --force to override."),
            "wired": False,
        })
        return

    seconds = max(1, min(int(args.seconds), MAX_LIVEVIEW_SECONDS))

    try:
        server = await camera.get_liveview()
    except Exception as exc:
        output({"error": f"Could not obtain live view URL: {exc}",
                "camera": name})
        return

    if not server:
        output({"error": "No live view server returned.", "camera": name})
        return

    result = {"camera": name, "wired": wired, "seconds": seconds,
              "raw_server": server}
    if not wired:
        result["warn"] = (f"BATTERY CAM: live view drains battery; ~"
                          f"{BATTERY_LIVE_BUDGET_MIN}-min lifetime budget.")

    if server.startswith("rtsps://"):
        # Directly playable; hand back the URL. It is short-lived server-side.
        result["kind"] = "rtsps"
        result["url"] = server
        result["ffplay_hint"] = f"ffplay -rtsp_transport tcp -i '{server}'"
        result["note"] = ("rtsps URL is playable directly with ffplay/ffmpeg "
                          "for a short window; this command does not proxy it.")
        output(result)
        return

    if server.startswith("immis://"):
        # Proprietary immis stream: spin a local TCP relay for `seconds`.
        result["kind"] = "immis"
        result["fragile"] = True
        try:
            stream = await camera.init_livestream()
            await stream.start(host="127.0.0.1")
            local_url = stream.url
            result["local_relay"] = local_url
            result["ffplay_hint"] = f"ffplay -i '{local_url}'"
            eprint(f"immis relay live at {local_url} for {seconds}s "
                   f"(experimental). Connect a player now.")
            try:
                await asyncio.sleep(seconds)
            finally:
                stream.stop()
            result["status"] = "relay_closed"
            result["note"] = ("immis relay is experimental/fragile; it only "
                              "served while this process was alive.")
            output(result)
        except NotImplementedError as exc:
            output({"error": f"immis livestream not supported: {exc}",
                    "camera": name, "raw_server": server})
        except Exception as exc:
            output({"error": f"immis relay failed: {exc}", "camera": name,
                    "raw_server": server})
        return

    result["kind"] = "unknown"
    result["note"] = "Unrecognized live view scheme; returning raw server only."
    output(result)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser():
    parser = argparse.ArgumentParser(description="Blink Camera Control "
                                                 "(blinkpy >= 0.25.3)")
    sub = parser.add_subparsers(dest="command", help="Command to run")

    s = sub.add_parser("setup", help="Interactive login (handles 2FA in-process)")
    s.add_argument("email", nargs="?", help="Blink account email")
    s.add_argument("password", nargs="?", help="Blink account password")

    v = sub.add_parser("verify", help="Fallback 2FA verify (flaky; prefer setup)")
    v.add_argument("pin", nargs="?", help="2FA PIN (usually stale; see help)")

    sub.add_parser("cameras", help="List all cameras with full status")
    sub.add_parser("networks", help="List sync modules / networks + arm state")

    snap = sub.add_parser("snapshot", help="Save a camera snapshot")
    snap.add_argument("camera", help="Camera name (partial, case-insensitive)")
    snap.add_argument("--refresh", action="store_true",
                      help="Force a FRESH capture (uses battery on battery "
                           "cams). Default is a cheap cached image.")

    arm = sub.add_parser("arm", help="Arm network(s)")
    arm.add_argument("--network", "-n", help="Network name (arms all if omitted)")

    disarm = sub.add_parser("disarm", help="Disarm network(s)")
    disarm.add_argument("--network", "-n",
                        help="Network name (disarms all if omitted)")

    ev = sub.add_parser("events", help="Recent motion: cloud clips + live flags")
    ev.add_argument("--camera", "-c", help="Filter by camera name")
    ev.add_argument("--since", help='Start time "YYYY/MM/DD HH:MM:SS"')
    ev.add_argument("--limit", "-l", type=int, default=25, help="Max clips")

    cl = sub.add_parser("clips", help="List cloud motion clips")
    cl.add_argument("--camera", "-c", help="Filter by camera name")
    cl.add_argument("--since", help='Start time "YYYY/MM/DD HH:MM:SS"')
    cl.add_argument("--limit", "-l", type=int, default=25, help="Max clips")

    vid = sub.add_parser("video", help="Download last cached clip for a camera")
    vid.add_argument("camera", help="Camera name (partial)")

    st = sub.add_parser("status", help="Detailed camera status")
    st.add_argument("camera", nargs="?", help="Camera name (all if omitted)")

    lv = sub.add_parser("liveview", help="Get a live view stream/URL")
    lv.add_argument("camera", help="Camera name (partial)")
    lv.add_argument("--seconds", type=int, default=30,
                    help=f"Live window seconds (hard cap {MAX_LIVEVIEW_SECONDS})")
    lv.add_argument("--force", action="store_true",
                    help="Allow live view on BATTERY cams (drains battery)")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # setup/verify manage their own session; the rest go through run_with_blink.
    auth_free = {"setup": cmd_setup, "verify": cmd_verify}
    with_blink = {
        "cameras": cmd_cameras,
        "networks": cmd_networks,
        "status": cmd_status,
        "snapshot": cmd_snapshot,
        "arm": cmd_arm,
        "disarm": cmd_disarm,
        "events": cmd_events,
        "clips": cmd_clips,
        "video": cmd_video,
        "liveview": cmd_liveview,
    }

    try:
        if args.command in auth_free:
            asyncio.run(auth_free[args.command](args))
        else:
            asyncio.run(run_with_blink(with_blink[args.command], args))
    except KeyboardInterrupt:  # pragma: no cover
        output({"error": "Interrupted"})
    except Exception as exc:
        output({"error": f"Unhandled failure: {exc}"})


if __name__ == "__main__":
    main()
