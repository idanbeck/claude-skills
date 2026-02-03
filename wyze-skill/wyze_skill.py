#!/usr/bin/env python3
"""Wyze Camera Skill - Control and monitor Wyze cameras and devices."""

import argparse
import json
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta

try:
    from wyze_sdk import Client
    from wyze_sdk.errors import WyzeApiError
except ImportError:
    print(json.dumps({"error": "wyze-sdk not installed. Run: pip3 install wyze-sdk"}))
    sys.exit(1)

CONFIG_DIR = Path(__file__).parent
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
SNAPSHOTS_DIR = CONFIG_DIR / "snapshots"


def output(data):
    """Output JSON response."""
    print(json.dumps(data, indent=2, default=str))


def load_credentials():
    """Load saved credentials."""
    if CREDENTIALS_FILE.exists():
        with open(CREDENTIALS_FILE) as f:
            return json.load(f)
    return None


def save_credentials(creds):
    """Save credentials to file."""
    with open(CREDENTIALS_FILE, 'w') as f:
        json.dump(creds, f, indent=2)


def get_client():
    """Get authenticated Wyze client."""
    creds = load_credentials()
    if not creds:
        return None, "Not authenticated. Run: python3 wyze_skill.py setup EMAIL PASSWORD"

    try:
        # Try using saved tokens first
        if creds.get('access_token') and creds.get('refresh_token'):
            client = Client(token=creds['access_token'], refresh_token=creds['refresh_token'])
        else:
            # Fall back to email/password
            client = Client(email=creds['email'], password=creds['password'])
            # Save tokens for next time
            creds['access_token'] = client._token
            creds['refresh_token'] = client._refresh_token
            save_credentials(creds)

        return client, None
    except WyzeApiError as e:
        # Token expired, try re-auth
        if creds.get('email') and creds.get('password'):
            try:
                client = Client(email=creds['email'], password=creds['password'])
                creds['access_token'] = client._token
                creds['refresh_token'] = client._refresh_token
                save_credentials(creds)
                return client, None
            except WyzeApiError as e2:
                return None, f"Authentication failed: {str(e2)}"
        return None, f"Authentication failed: {str(e)}"


def cmd_setup(args):
    """Set up Wyze authentication."""
    if not args.email or not args.password:
        output({"error": "Email and password required", "usage": "python3 wyze_skill.py setup EMAIL PASSWORD"})
        return

    try:
        # If key_id and api_key provided, use those
        if args.key_id and args.api_key:
            client = Client(token=args.api_key)
            creds = {
                'email': args.email,
                'key_id': args.key_id,
                'api_key': args.api_key
            }
        else:
            client = Client(email=args.email, password=args.password)
            creds = {
                'email': args.email,
                'password': args.password,
                'access_token': client._token,
                'refresh_token': client._refresh_token
            }

        save_credentials(creds)
        output({"status": "success", "message": "Wyze authenticated successfully"})

    except WyzeApiError as e:
        if "TwoFactorAuthenticationRequired" in str(e) or "verification code" in str(e).lower():
            # Save partial creds for 2FA flow
            save_credentials({'email': args.email, 'password': args.password, 'needs_2fa': True})
            output({
                "status": "2fa_required",
                "message": "Check your email/phone for a verification code and run: python3 wyze_skill.py verify CODE"
            })
        else:
            output({"error": f"Setup failed: {str(e)}"})


def cmd_verify(args):
    """Verify 2FA code."""
    if not args.code:
        output({"error": "Verification code required", "usage": "python3 wyze_skill.py verify CODE"})
        return

    creds = load_credentials()
    if not creds or not creds.get('email') or not creds.get('password'):
        output({"error": "Run setup first before verify"})
        return

    try:
        client = Client(
            email=creds['email'],
            password=creds['password'],
            totp_key=args.code
        )
        creds['access_token'] = client._token
        creds['refresh_token'] = client._refresh_token
        creds.pop('needs_2fa', None)
        save_credentials(creds)
        output({"status": "success", "message": "2FA verified successfully"})

    except WyzeApiError as e:
        output({"error": f"Verification failed: {str(e)}"})


def cmd_cameras(args):
    """List all cameras."""
    client, error = get_client()
    if error:
        output({"error": error})
        return

    try:
        cameras = client.cameras.list()
        camera_list = []
        for cam in cameras:
            camera_list.append({
                "name": cam.nickname,
                "mac": cam.mac,
                "model": cam.product.model,
                "is_online": cam.is_online,
                "firmware": cam.firmware_ver if hasattr(cam, 'firmware_ver') else None
            })

        output({"cameras": camera_list, "count": len(camera_list)})

    except WyzeApiError as e:
        output({"error": f"Failed to list cameras: {str(e)}"})


def cmd_devices(args):
    """List all Wyze devices."""
    client, error = get_client()
    if error:
        output({"error": error})
        return

    try:
        devices = client.devices_list()
        device_list = []
        for dev in devices:
            device_list.append({
                "name": dev.nickname,
                "mac": dev.mac,
                "type": dev.type,
                "model": dev.product.model if hasattr(dev, 'product') else None,
                "is_online": dev.is_online if hasattr(dev, 'is_online') else None
            })

        output({"devices": device_list, "count": len(device_list)})

    except WyzeApiError as e:
        output({"error": f"Failed to list devices: {str(e)}"})


def cmd_snapshot(args):
    """Get a snapshot from a camera (if supported)."""
    client, error = get_client()
    if error:
        output({"error": error})
        return

    camera_name = args.camera.lower()

    try:
        cameras = client.cameras.list()
        camera = None
        matched_name = None

        for cam in cameras:
            if camera_name in cam.nickname.lower():
                camera = cam
                matched_name = cam.nickname
                break

        if not camera:
            output({"error": f"Camera '{args.camera}' not found", "available": [c.nickname for c in cameras]})
            return

        # Try to get thumbnail/snapshot
        # Note: Wyze API snapshot support varies by camera model
        SNAPSHOTS_DIR.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{matched_name.replace(' ', '_')}_{timestamp}.jpg"
        filepath = SNAPSHOTS_DIR / filename

        # Get camera info which may include thumbnail
        cam_info = client.cameras.info(device_mac=camera.mac)

        if hasattr(cam_info, 'thumbnail') and cam_info.thumbnail:
            import urllib.request
            urllib.request.urlretrieve(cam_info.thumbnail, str(filepath))
            output({
                "status": "success",
                "camera": matched_name,
                "snapshot": str(filepath),
                "timestamp": timestamp,
                "note": "Thumbnail from last motion event (live snapshot not available via API)"
            })
        else:
            output({
                "status": "partial",
                "camera": matched_name,
                "message": "Live snapshots not available via Wyze API. Consider enabling RTSP firmware for direct streaming.",
                "is_online": camera.is_online
            })

    except WyzeApiError as e:
        output({"error": f"Snapshot failed: {str(e)}"})


def cmd_events(args):
    """Get recent events from cameras."""
    client, error = get_client()
    if error:
        output({"error": error})
        return

    try:
        # Calculate time range
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=args.hours or 24)

        events = client.events.list(
            begin=start_time,
            end=end_time,
            limit=args.limit or 20
        )

        event_list = []
        for event in events:
            if args.camera and args.camera.lower() not in event.device_name.lower():
                continue

            event_list.append({
                "camera": event.device_name if hasattr(event, 'device_name') else "Unknown",
                "type": event.event_category if hasattr(event, 'event_category') else event.event_type,
                "timestamp": event.event_ts if hasattr(event, 'event_ts') else None,
                "file_url": event.file_url if hasattr(event, 'file_url') else None,
                "thumbnail": event.thumbnail if hasattr(event, 'thumbnail') else None
            })

        output({"events": event_list, "count": len(event_list)})

    except WyzeApiError as e:
        output({"error": f"Failed to get events: {str(e)}"})


def cmd_status(args):
    """Get camera status."""
    client, error = get_client()
    if error:
        output({"error": error})
        return

    try:
        cameras = client.cameras.list()

        if args.camera:
            camera_name = args.camera.lower()
            for cam in cameras:
                if camera_name in cam.nickname.lower():
                    cam_info = client.cameras.info(device_mac=cam.mac)
                    output({
                        "camera": cam.nickname,
                        "mac": cam.mac,
                        "model": cam.product.model,
                        "is_online": cam.is_online,
                        "firmware": cam.firmware_ver if hasattr(cam, 'firmware_ver') else None,
                        "motion_detection": cam_info.motion_detection if hasattr(cam_info, 'motion_detection') else None,
                        "sound_detection": cam_info.sound_detection if hasattr(cam_info, 'sound_detection') else None,
                        "night_vision": cam_info.night_vision if hasattr(cam_info, 'night_vision') else None
                    })
                    return
            output({"error": f"Camera '{args.camera}' not found", "available": [c.nickname for c in cameras]})
        else:
            # All cameras summary
            statuses = []
            for cam in cameras:
                statuses.append({
                    "name": cam.nickname,
                    "is_online": cam.is_online,
                    "model": cam.product.model
                })
            output({"cameras": statuses})

    except WyzeApiError as e:
        output({"error": f"Status check failed: {str(e)}"})


def cmd_turn_on(args):
    """Turn on a camera."""
    client, error = get_client()
    if error:
        output({"error": error})
        return

    try:
        cameras = client.cameras.list()
        camera_name = args.camera.lower()

        for cam in cameras:
            if camera_name in cam.nickname.lower():
                client.cameras.turn_on(device_mac=cam.mac, device_model=cam.product.model)
                output({"status": "success", "camera": cam.nickname, "power": "on"})
                return

        output({"error": f"Camera '{args.camera}' not found", "available": [c.nickname for c in cameras]})

    except WyzeApiError as e:
        output({"error": f"Turn on failed: {str(e)}"})


def cmd_turn_off(args):
    """Turn off a camera."""
    client, error = get_client()
    if error:
        output({"error": error})
        return

    try:
        cameras = client.cameras.list()
        camera_name = args.camera.lower()

        for cam in cameras:
            if camera_name in cam.nickname.lower():
                client.cameras.turn_off(device_mac=cam.mac, device_model=cam.product.model)
                output({"status": "success", "camera": cam.nickname, "power": "off"})
                return

        output({"error": f"Camera '{args.camera}' not found", "available": [c.nickname for c in cameras]})

    except WyzeApiError as e:
        output({"error": f"Turn off failed: {str(e)}"})


def cmd_download_event(args):
    """Download video from an event."""
    client, error = get_client()
    if error:
        output({"error": error})
        return

    try:
        # Get recent events
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=24)

        events = client.events.list(begin=start_time, end=end_time, limit=50)

        # Find matching event
        target_event = None
        for event in events:
            if args.camera:
                device_name = event.device_name if hasattr(event, 'device_name') else ""
                if args.camera.lower() not in device_name.lower():
                    continue
            target_event = event
            break  # Get most recent matching event

        if not target_event:
            output({"error": "No matching events found"})
            return

        if not hasattr(target_event, 'file_url') or not target_event.file_url:
            output({"error": "Event has no video file", "event": str(target_event)})
            return

        # Download video
        SNAPSHOTS_DIR.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        device_name = target_event.device_name if hasattr(target_event, 'device_name') else "camera"
        filename = f"{device_name.replace(' ', '_')}_{timestamp}.mp4"
        filepath = SNAPSHOTS_DIR / filename

        import urllib.request
        urllib.request.urlretrieve(target_event.file_url, str(filepath))

        output({
            "status": "success",
            "video": str(filepath),
            "event_type": target_event.event_type if hasattr(target_event, 'event_type') else "unknown",
            "camera": device_name
        })

    except WyzeApiError as e:
        output({"error": f"Download failed: {str(e)}"})


def main():
    parser = argparse.ArgumentParser(description="Wyze Camera Control")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Setup
    setup_parser = subparsers.add_parser("setup", help="Authenticate with Wyze")
    setup_parser.add_argument("email", nargs="?", help="Wyze account email")
    setup_parser.add_argument("password", nargs="?", help="Wyze account password")
    setup_parser.add_argument("--key-id", help="API Key ID (optional)")
    setup_parser.add_argument("--api-key", help="API Key (optional)")

    # Verify 2FA
    verify_parser = subparsers.add_parser("verify", help="Verify 2FA code")
    verify_parser.add_argument("code", nargs="?", help="2FA code from email/SMS/TOTP")

    # List cameras
    subparsers.add_parser("cameras", help="List all cameras")

    # List all devices
    subparsers.add_parser("devices", help="List all Wyze devices")

    # Snapshot
    snapshot_parser = subparsers.add_parser("snapshot", help="Get camera snapshot/thumbnail")
    snapshot_parser.add_argument("camera", help="Camera name (partial match)")

    # Events
    events_parser = subparsers.add_parser("events", help="Get recent events")
    events_parser.add_argument("--camera", "-c", help="Filter by camera name")
    events_parser.add_argument("--hours", "-H", type=int, default=24, help="Hours of history (default 24)")
    events_parser.add_argument("--limit", "-l", type=int, default=20, help="Max events to return")

    # Status
    status_parser = subparsers.add_parser("status", help="Get camera status")
    status_parser.add_argument("camera", nargs="?", help="Camera name (optional)")

    # Turn on
    on_parser = subparsers.add_parser("on", help="Turn on camera")
    on_parser.add_argument("camera", help="Camera name")

    # Turn off
    off_parser = subparsers.add_parser("off", help="Turn off camera")
    off_parser.add_argument("camera", help="Camera name")

    # Download event video
    download_parser = subparsers.add_parser("download", help="Download most recent event video")
    download_parser.add_argument("--camera", "-c", help="Filter by camera name")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    commands = {
        "setup": cmd_setup,
        "verify": cmd_verify,
        "cameras": cmd_cameras,
        "devices": cmd_devices,
        "snapshot": cmd_snapshot,
        "events": cmd_events,
        "status": cmd_status,
        "on": cmd_turn_on,
        "off": cmd_turn_off,
        "download": cmd_download_event,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
