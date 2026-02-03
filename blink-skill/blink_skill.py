#!/usr/bin/env python3
"""Blink Camera Skill - Control and monitor Blink cameras."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime

try:
    from blinkpy.blinkpy import Blink
    from blinkpy.auth import Auth
    from blinkpy.helpers.util import json_load, json_save
except ImportError:
    print(json.dumps({"error": "blinkpy not installed. Run: pip3 install blinkpy"}))
    sys.exit(1)

CONFIG_DIR = Path(__file__).parent
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
SNAPSHOTS_DIR = CONFIG_DIR / "snapshots"


def output(data):
    """Output JSON response."""
    print(json.dumps(data, indent=2, default=str))


async def get_blink():
    """Initialize and authenticate Blink connection."""
    if not CREDENTIALS_FILE.exists():
        return None, "Not authenticated. Run: python3 blink_skill.py setup EMAIL PASSWORD"

    blink = Blink()
    auth = Auth(await json_load(CREDENTIALS_FILE), no_prompt=True)
    blink.auth = auth

    await blink.start()
    await json_save(blink.auth.login_attributes, CREDENTIALS_FILE)

    return blink, None


async def cmd_setup(args):
    """Set up Blink authentication."""
    if not args.email or not args.password:
        output({"error": "Email and password required", "usage": "python3 blink_skill.py setup EMAIL PASSWORD"})
        return

    blink = Blink()
    auth = Auth({"username": args.email, "password": args.password}, no_prompt=True)
    blink.auth = auth

    await blink.start()

    # Check if 2FA is needed
    if blink.auth.check_key_required():
        output({
            "status": "2fa_required",
            "message": "Check your email/phone for a PIN and run: python3 blink_skill.py verify PIN"
        })
        # Save partial auth state
        await json_save(blink.auth.login_attributes, CREDENTIALS_FILE)
        return

    await json_save(blink.auth.login_attributes, CREDENTIALS_FILE)
    output({"status": "success", "message": "Blink authenticated successfully"})


async def cmd_verify(args):
    """Verify 2FA PIN."""
    if not args.pin:
        output({"error": "PIN required", "usage": "python3 blink_skill.py verify PIN"})
        return

    blink = Blink()
    auth = Auth(await json_load(CREDENTIALS_FILE), no_prompt=True)
    blink.auth = auth

    await blink.auth.send_auth_key(blink, args.pin)
    await blink.start()
    await json_save(blink.auth.login_attributes, CREDENTIALS_FILE)

    output({"status": "success", "message": "2FA verified successfully"})


async def cmd_cameras(args):
    """List all cameras."""
    blink, error = await get_blink()
    if error:
        output({"error": error})
        return

    cameras = []
    for name, camera in blink.cameras.items():
        cameras.append({
            "name": name,
            "type": camera.camera_type,
            "armed": camera.arm,
            "motion_enabled": camera.motion_enabled,
            "battery": camera.battery,
            "temperature": camera.temperature,
            "wifi_strength": camera.wifi_strength,
            "last_motion": camera.last_motion,
            "network": camera.sync.name if camera.sync else None
        })

    output({"cameras": cameras, "count": len(cameras)})


async def cmd_networks(args):
    """List all sync modules/networks."""
    blink, error = await get_blink()
    if error:
        output({"error": error})
        return

    networks = []
    for name, sync in blink.sync.items():
        networks.append({
            "name": name,
            "id": sync.sync_id,
            "armed": sync.arm,
            "status": sync.status,
            "camera_count": len(sync.cameras)
        })

    output({"networks": networks, "count": len(networks)})


async def cmd_snapshot(args):
    """Get a snapshot from a camera."""
    blink, error = await get_blink()
    if error:
        output({"error": error})
        return

    # Find camera
    camera_name = args.camera.lower()
    camera = None
    matched_name = None

    for name, cam in blink.cameras.items():
        if camera_name in name.lower():
            camera = cam
            matched_name = name
            break

    if not camera:
        output({"error": f"Camera '{args.camera}' not found", "available": list(blink.cameras.keys())})
        return

    # Request new snapshot
    await camera.snap_picture()
    await blink.refresh()

    # Save snapshot
    SNAPSHOTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{matched_name.replace(' ', '_')}_{timestamp}.jpg"
    filepath = SNAPSHOTS_DIR / filename

    await camera.image_to_file(str(filepath))

    output({
        "status": "success",
        "camera": matched_name,
        "snapshot": str(filepath),
        "timestamp": timestamp
    })


async def cmd_arm(args):
    """Arm a network/sync module."""
    blink, error = await get_blink()
    if error:
        output({"error": error})
        return

    if args.network:
        network_name = args.network.lower()
        for name, sync in blink.sync.items():
            if network_name in name.lower():
                await sync.async_arm(True)
                output({"status": "success", "network": name, "armed": True})
                return
        output({"error": f"Network '{args.network}' not found", "available": list(blink.sync.keys())})
    else:
        # Arm all networks
        for name, sync in blink.sync.items():
            await sync.async_arm(True)
        output({"status": "success", "message": "All networks armed"})


async def cmd_disarm(args):
    """Disarm a network/sync module."""
    blink, error = await get_blink()
    if error:
        output({"error": error})
        return

    if args.network:
        network_name = args.network.lower()
        for name, sync in blink.sync.items():
            if network_name in name.lower():
                await sync.async_arm(False)
                output({"status": "success", "network": name, "armed": False})
                return
        output({"error": f"Network '{args.network}' not found", "available": list(blink.sync.keys())})
    else:
        # Disarm all networks
        for name, sync in blink.sync.items():
            await sync.async_arm(False)
        output({"status": "success", "message": "All networks disarmed"})


async def cmd_events(args):
    """Get recent motion events."""
    blink, error = await get_blink()
    if error:
        output({"error": error})
        return

    await blink.refresh()

    events = []
    for name, camera in blink.cameras.items():
        if args.camera and args.camera.lower() not in name.lower():
            continue

        if camera.last_motion:
            events.append({
                "camera": name,
                "type": "motion",
                "timestamp": camera.last_motion,
                "thumbnail": camera.thumbnail
            })

    # Sort by timestamp descending
    events.sort(key=lambda x: x["timestamp"] if x["timestamp"] else "", reverse=True)

    # Limit results
    limit = args.limit or 10
    events = events[:limit]

    output({"events": events, "count": len(events)})


async def cmd_video(args):
    """Download the last video clip from a camera."""
    blink, error = await get_blink()
    if error:
        output({"error": error})
        return

    # Find camera
    camera_name = args.camera.lower()
    camera = None
    matched_name = None

    for name, cam in blink.cameras.items():
        if camera_name in name.lower():
            camera = cam
            matched_name = name
            break

    if not camera:
        output({"error": f"Camera '{args.camera}' not found", "available": list(blink.cameras.keys())})
        return

    # Get video list
    await blink.refresh()

    SNAPSHOTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{matched_name.replace(' ', '_')}_{timestamp}.mp4"
    filepath = SNAPSHOTS_DIR / filename

    await camera.video_to_file(str(filepath))

    output({
        "status": "success",
        "camera": matched_name,
        "video": str(filepath),
        "timestamp": timestamp
    })


async def cmd_status(args):
    """Get detailed status of a camera."""
    blink, error = await get_blink()
    if error:
        output({"error": error})
        return

    if args.camera:
        camera_name = args.camera.lower()
        for name, camera in blink.cameras.items():
            if camera_name in name.lower():
                output({
                    "camera": name,
                    "type": camera.camera_type,
                    "armed": camera.arm,
                    "motion_enabled": camera.motion_enabled,
                    "battery": camera.battery,
                    "temperature": camera.temperature,
                    "temperature_c": camera.temperature_c,
                    "wifi_strength": camera.wifi_strength,
                    "last_motion": camera.last_motion,
                    "thumbnail": camera.thumbnail,
                    "network": camera.sync.name if camera.sync else None,
                    "serial": camera.serial
                })
                return
        output({"error": f"Camera '{args.camera}' not found", "available": list(blink.cameras.keys())})
    else:
        # All cameras status summary
        statuses = []
        for name, camera in blink.cameras.items():
            statuses.append({
                "name": name,
                "armed": camera.arm,
                "battery": camera.battery,
                "last_motion": camera.last_motion
            })
        output({"cameras": statuses})


def main():
    parser = argparse.ArgumentParser(description="Blink Camera Control")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Setup
    setup_parser = subparsers.add_parser("setup", help="Authenticate with Blink")
    setup_parser.add_argument("email", nargs="?", help="Blink account email")
    setup_parser.add_argument("password", nargs="?", help="Blink account password")

    # Verify 2FA
    verify_parser = subparsers.add_parser("verify", help="Verify 2FA PIN")
    verify_parser.add_argument("pin", nargs="?", help="2FA PIN from email/SMS")

    # List cameras
    subparsers.add_parser("cameras", help="List all cameras")

    # List networks
    subparsers.add_parser("networks", help="List all sync modules/networks")

    # Snapshot
    snapshot_parser = subparsers.add_parser("snapshot", help="Get camera snapshot")
    snapshot_parser.add_argument("camera", help="Camera name (partial match)")

    # Arm
    arm_parser = subparsers.add_parser("arm", help="Arm network(s)")
    arm_parser.add_argument("--network", "-n", help="Network name (optional, arms all if omitted)")

    # Disarm
    disarm_parser = subparsers.add_parser("disarm", help="Disarm network(s)")
    disarm_parser.add_argument("--network", "-n", help="Network name (optional, disarms all if omitted)")

    # Events
    events_parser = subparsers.add_parser("events", help="Get recent motion events")
    events_parser.add_argument("--camera", "-c", help="Filter by camera name")
    events_parser.add_argument("--limit", "-l", type=int, default=10, help="Max events to return")

    # Video
    video_parser = subparsers.add_parser("video", help="Download last video clip")
    video_parser.add_argument("camera", help="Camera name (partial match)")

    # Status
    status_parser = subparsers.add_parser("status", help="Get camera status")
    status_parser.add_argument("camera", nargs="?", help="Camera name (optional)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        "setup": cmd_setup,
        "verify": cmd_verify,
        "cameras": cmd_cameras,
        "networks": cmd_networks,
        "snapshot": cmd_snapshot,
        "arm": cmd_arm,
        "disarm": cmd_disarm,
        "events": cmd_events,
        "video": cmd_video,
        "status": cmd_status,
    }

    asyncio.run(commands[args.command](args))


if __name__ == "__main__":
    main()
