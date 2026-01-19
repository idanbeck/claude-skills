#!/opt/homebrew/bin/python3.11
"""
Alexa Skill - Control Amazon Echo devices and smart home.

Send announcements, control smart home devices, send notifications,
and trigger routines on your Alexa-enabled devices.

Usage:
    python3 alexa_skill.py setup              # First-time authentication
    python3 alexa_skill.py devices            # List Echo devices
    python3 alexa_skill.py announce MESSAGE   # Make announcement
    python3 alexa_skill.py speak MESSAGE      # Text-to-speech (no chime)
    python3 alexa_skill.py smart-home         # List smart home devices
    python3 alexa_skill.py control DEVICE     # Control smart home device
    python3 alexa_skill.py volume LEVEL       # Set volume (0-100)
    python3 alexa_skill.py routines           # List routines
    python3 alexa_skill.py routine NAME       # Trigger routine
    python3 alexa_skill.py notify MESSAGE     # Send notification
"""

import argparse
import asyncio
import json
import sys
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional

# Check for required dependencies
try:
    from alexapy import AlexaAPI, AlexaLogin, WebsocketEchoClient
    from alexapy.errors import AlexapyLoginError
except ImportError:
    print(json.dumps({
        "error": "AlexaPy not installed",
        "instructions": [
            "Install with: pip install alexapy aiohttp",
            "Or: pip install -r ~/.claude/skills/alexa-skill/requirements.txt"
        ]
    }, indent=2))
    sys.exit(1)

# Paths
SKILL_DIR = Path(__file__).parent
CONFIG_FILE = SKILL_DIR / "config.json"


class DeviceWrapper:
    """Wrapper to convert device dict to object with required AlexaAPI attributes."""

    def __init__(self, device_dict: Dict[str, Any]):
        self._device_type = device_dict.get("deviceType", "")
        self._device_family = device_dict.get("deviceFamily", "")
        self.device_serial_number = device_dict.get("serialNumber", "")
        self._locale = device_dict.get("locale", "en-US")
        self._cluster_members = device_dict.get("clusterMembers", [])
        self._raw = device_dict

    def get(self, key: str, default: Any = None) -> Any:
        """Allow dict-like access for backwards compatibility."""
        return self._raw.get(key, default)

# Amazon URLs by region
AMAZON_URLS = {
    "us": "amazon.com",
    "uk": "amazon.co.uk",
    "de": "amazon.de",
    "jp": "amazon.co.jp",
    "ca": "amazon.ca",
    "au": "amazon.com.au",
    "fr": "amazon.fr",
    "it": "amazon.it",
    "es": "amazon.es",
    "br": "amazon.com.br",
    "mx": "amazon.com.mx",
    "in": "amazon.in"
}


def load_config() -> Dict[str, Any]:
    """Load configuration from file."""
    if not CONFIG_FILE.exists():
        return {}
    with open(CONFIG_FILE) as f:
        return json.load(f)


def save_config(config: Dict[str, Any]) -> None:
    """Save configuration to file."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def output(data: Any) -> None:
    """Output JSON response."""
    print(json.dumps(data, indent=2, default=str))


def error(message: str, **kwargs) -> None:
    """Output error response and exit."""
    output({"error": message, **kwargs})
    sys.exit(1)


def get_outputpath(filename: str) -> str:
    """Return full path for a filename in the skill directory."""
    return str(SKILL_DIR / filename)


def parse_cookie_string(cookie_string: str) -> Dict[str, str]:
    """Parse a cookie string like 'name=value; name2=value2' into a dict."""
    cookies = {}
    if not cookie_string:
        return cookies
    for part in cookie_string.split(';'):
        part = part.strip()
        if '=' in part:
            name, value = part.split('=', 1)
            cookies[name.strip()] = value.strip()
    return cookies


async def get_login() -> AlexaLogin:
    """Get authenticated AlexaLogin instance."""
    config = load_config()

    if not config:
        error("Not authenticated. Run 'node setup.js <email>' first.", setup_required=True)

    # Check for cookies from alexa-cookie2 format
    cookie_string = config.get("localCookie") or config.get("cookies", "")
    if isinstance(cookie_string, str):
        cookies = parse_cookie_string(cookie_string)
    elif isinstance(cookie_string, dict):
        cookies = cookie_string
    else:
        cookies = {}

    if not cookies:
        error("No cookies found in config. Please run setup again.")

    login = AlexaLogin(
        url=config.get("url", "amazon.com"),
        email=config.get("email", ""),
        password="",
        outputpath=get_outputpath,
        debug=False
    )

    # Set tokens from config
    login.refresh_token = config.get("refreshToken") or config.get("refresh_token")
    login.customer_email = config.get("email")

    # Try to login with cookies
    try:
        await login.login(cookies=cookies)
    except Exception as e:
        # If login fails, try to use cookies directly
        pass

    return login


async def setup_auth(email: str, region: str = "us") -> None:
    """Setup Amazon authentication using proxy-based OAuth flow."""
    from yarl import URL
    from authcaptureproxy import AuthCaptureProxy
    import re

    url = AMAZON_URLS.get(region, "amazon.com")

    print(f"\n=== Alexa Skill Setup ===")
    print(f"Email: {email}")
    print(f"Region: {region} ({url})")
    print()

    login = AlexaLogin(
        url=url,
        email=email,
        password="",
        outputpath=get_outputpath,
        debug=False
    )

    # Set up proxy to capture OAuth response
    proxy_url = URL("http://127.0.0.1:8765")
    host_url = login.start_url

    proxy = AuthCaptureProxy(proxy_url, host_url)

    # Track if we've captured the OAuth code
    captured_data = {"code": None, "url": None}

    def check_for_code(resp, data, query):
        """Check if OAuth code is in the response URL."""
        url_str = str(resp.url) if hasattr(resp, 'url') else ""
        if "code=" in url_str or "code=" in str(query):
            match = re.search(r"code=([^&]+)", url_str + str(query))
            if match:
                captured_data["code"] = match.group(1)
                captured_data["url"] = url_str
                return True
        # Also check for maplanding (successful login redirect)
        if "maplanding" in url_str:
            captured_data["url"] = url_str
            return True
        return False

    proxy.tests["oauth_complete"] = check_for_code

    try:
        await proxy.start_proxy()

        print(f"Proxy server started on port {proxy.port}")
        print()
        print("=" * 50)
        print("OPEN THIS URL IN YOUR BROWSER:")
        print(f"  http://127.0.0.1:{proxy.port}/")
        print("=" * 50)
        print()
        print("Complete the Amazon login in your browser.")
        print("Waiting for authentication...")
        print()

        # Open browser automatically
        webbrowser.open(f"http://127.0.0.1:{proxy.port}/")

        # Wait for OAuth code to be captured (timeout after 5 minutes)
        timeout = 300
        poll_interval = 1
        elapsed = 0

        while elapsed < timeout:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            # Check if we captured the OAuth code or redirect
            if captured_data["code"] or captured_data["url"]:
                print("Login redirect captured!")
                break

            # Also check if login has status
            if hasattr(login, 'status') and login.status:
                if login.status.get("login_successful"):
                    break

            if elapsed % 30 == 0:
                print(f"  Still waiting... ({elapsed}s)")

        # Get captured data from proxy before stopping
        proxy_data = dict(proxy.data) if hasattr(proxy, 'data') else {}
        proxy_cookies = {}

        # Try to get cookies from proxy session
        if hasattr(proxy, '_session') and proxy._session:
            for cookie in proxy._session.cookies.jar:
                proxy_cookies[cookie.name] = cookie.value

        await proxy.stop_proxy()

        print(f"Captured data keys: {list(proxy_data.keys())}")
        print(f"Captured cookies: {list(proxy_cookies.keys())}")
        print(f"Captured URL: {captured_data.get('url', 'none')}")
        print(f"Captured code: {captured_data.get('code', 'none')}")

        # Try to login with captured cookies
        if proxy_cookies:
            await login.login(cookies=proxy_cookies)
        else:
            await login.login()

        if login.status and login.status.get("login_successful"):
            config = {
                "email": email,
                "url": url,
                "region": region,
                "access_token": login.access_token,
                "refresh_token": login.refresh_token,
                "expires_in": login.expires_in,
                "customer_id": login.customer_id,
            }
            save_config(config)

            output({
                "success": True,
                "message": "Authentication successful!",
                "email": email,
                "region": region
            })
        else:
            # Even if status doesn't show success, check if we have tokens
            if login.access_token:
                config = {
                    "email": email,
                    "url": url,
                    "region": region,
                    "access_token": login.access_token,
                    "refresh_token": login.refresh_token,
                    "expires_in": login.expires_in,
                    "customer_id": login.customer_id,
                }
                save_config(config)
                output({
                    "success": True,
                    "message": "Authentication successful!",
                    "email": email,
                    "region": region
                })
            else:
                # Print debug info
                print(f"Login status: {getattr(login, 'status', {})}")
                print(f"Access token: {getattr(login, 'access_token', None)}")
                error("Login failed or timed out. Please try again.")

    except AlexapyLoginError as e:
        error(f"Login error: {str(e)}")
    except Exception as e:
        error(f"Setup failed: {str(e)}")
    finally:
        if proxy.active:
            await proxy.stop_proxy()
        await login.close()


async def list_devices() -> None:
    """List all Alexa/Echo devices."""
    login = await get_login()

    try:
        # get_devices is a static method
        devices = await AlexaAPI.get_devices(login)

        device_list = []
        if devices:
            for device in devices:
                device_list.append({
                    "name": device.get("accountName"),
                    "type": device.get("deviceType"),
                    "family": device.get("deviceFamily"),
                    "serial": device.get("serialNumber"),
                    "online": device.get("online", False),
                    "capabilities": device.get("capabilities", [])
                })

        output({
            "devices": device_list,
            "count": len(device_list)
        })

    except Exception as e:
        error(f"Failed to list devices: {str(e)}")


async def send_announcement(message: str, device: Optional[str] = None, all_devices: bool = False) -> None:
    """Send announcement to Alexa device(s)."""
    login = await get_login()

    try:
        devices = await AlexaAPI.get_devices(login)

        # Find target device(s)
        targets = []
        if all_devices:
            targets = [d for d in devices if d.get("online")]
        elif device:
            for d in devices:
                if device.lower() in d.get("accountName", "").lower():
                    targets.append(d)
                    break
            if not targets:
                error(f"Device '{device}' not found")
        else:
            # Use first online device as default
            for d in devices:
                if d.get("online"):
                    targets.append(d)
                    break

        if not targets:
            error("No online devices found")

        # Send announcement using the first target device for the API instance
        alexa = AlexaAPI(DeviceWrapper(targets[0]), login)
        await alexa.send_announcement(
            message,
            method="announce"
        )

        output({
            "success": True,
            "message": message,
            "devices": [t.get("accountName") for t in targets]
        })

    except Exception as e:
        error(f"Failed to send announcement: {str(e)}")


async def send_tts(message: str, device: Optional[str] = None) -> None:
    """Send text-to-speech to Alexa device (no announcement chime)."""
    login = await get_login()

    try:
        devices = await AlexaAPI.get_devices(login)

        # Find target device
        target = None
        if device:
            for d in devices:
                if device.lower() in d.get("accountName", "").lower():
                    target = d
                    break
            if not target:
                error(f"Device '{device}' not found")
        else:
            # Use first online device as default
            for d in devices:
                if d.get("online"):
                    target = d
                    break

        if not target:
            error("No online devices found")

        # Send TTS
        alexa = AlexaAPI(DeviceWrapper(target), login)
        await alexa.send_tts(message)

        output({
            "success": True,
            "message": message,
            "device": target.get("accountName")
        })

    except Exception as e:
        error(f"Failed to send TTS: {str(e)}")


async def list_smart_home() -> None:
    """List smart home devices with basic info."""
    login = await get_login()

    try:
        # Use GraphQL to get all smart home devices
        devices = await AlexaAPI.get_network_details(login)

        if not devices:
            output({
                "smart_home_devices": [],
                "count": 0
            })
            return

        device_list = []
        for device in devices:
            device_list.append({
                "name": device.get("friendlyName"),
                "description": device.get("friendlyDescription"),
                "type": device.get("applianceTypes", []),
                "manufacturer": device.get("manufacturerName")
            })

        output({
            "smart_home_devices": device_list,
            "count": len(device_list)
        })

    except Exception as e:
        error(f"Failed to list smart home devices: {str(e)}")
    finally:
        await login.close()


async def list_smart_entities() -> None:
    """List smart home devices with entity IDs for silent control."""
    login = await get_login()

    try:
        # Use GraphQL to get all smart home devices with their entity IDs
        devices = await AlexaAPI.get_network_details(login)

        if not devices:
            output({
                "entities": [],
                "count": 0
            })
            return

        entity_list = []
        for device in devices:
            # Extract supported capabilities
            caps = device.get("capabilities", [])
            actions = []
            for cap in caps:
                interface = cap.get("interfaceName", "")
                if "PowerController" in interface:
                    actions.append("power")
                elif "BrightnessController" in interface:
                    actions.append("brightness")
                elif "ColorController" in interface:
                    actions.append("color")
                elif "ColorTemperatureController" in interface:
                    actions.append("color_temperature")

            entity_list.append({
                "entity_id": device.get("entityId"),
                "name": device.get("friendlyName"),
                "description": device.get("friendlyDescription"),
                "type": device.get("applianceTypes", []),
                "manufacturer": device.get("manufacturerName"),
                "actions": actions
            })

        output({
            "entities": entity_list,
            "count": len(entity_list)
        })

    except Exception as e:
        error(f"Failed to list smart entities: {str(e)}")
    finally:
        await login.close()


async def silent_control(entity_id: str, power_on: bool, brightness: Optional[int] = None,
                         color: Optional[str] = None) -> None:
    """Control a smart home device silently (no Alexa voice response)."""
    login = await get_login()

    try:
        # Use the static set_light_state method for silent control
        result = await AlexaAPI.set_light_state(
            login,
            entity_id=entity_id,
            power_on=power_on,
            brightness=brightness,
            color_name=color
        )

        output({
            "success": True,
            "entity_id": entity_id,
            "power": "on" if power_on else "off",
            "brightness": brightness,
            "color": color,
            "response": result
        })

    except Exception as e:
        error(f"Failed to control device: {str(e)}")
    finally:
        await login.close()


async def control_device(device_name: str, action: str, value: Optional[str] = None) -> None:
    """Control a smart home device using voice commands."""
    login = await get_login()

    try:
        # Get an online Alexa device for API calls
        devices = await AlexaAPI.get_devices(login)
        alexa_device = None
        for d in devices:
            if d.get("online"):
                alexa_device = d
                break

        if not alexa_device:
            error("No online Alexa devices found")

        alexa = AlexaAPI(DeviceWrapper(alexa_device), login)

        # Build voice command based on action
        if action.lower() == "on":
            command = f"turn on {device_name}"
        elif action.lower() == "off":
            command = f"turn off {device_name}"
        elif action.lower() == "setbrightness" and value:
            command = f"set {device_name} brightness to {value} percent"
        elif action.lower() == "setcolor" and value:
            command = f"set {device_name} to {value}"
        elif action.lower() == "toggle":
            command = f"toggle {device_name}"
        else:
            command = f"{action} {device_name}"
            if value:
                command += f" {value}"

        await alexa.run_custom(command)

        output({
            "success": True,
            "device": device_name,
            "action": action,
            "value": value,
            "command": command
        })

    except Exception as e:
        error(f"Failed to control device: {str(e)}")


async def set_volume(level: int, device: Optional[str] = None) -> None:
    """Set volume on Alexa device."""
    if not 0 <= level <= 100:
        error("Volume must be between 0 and 100")

    login = await get_login()

    try:
        devices = await AlexaAPI.get_devices(login)

        # Find target device
        target = None
        if device:
            for d in devices:
                if device.lower() in d.get("accountName", "").lower():
                    target = d
                    break
            if not target:
                error(f"Device '{device}' not found")
        else:
            for d in devices:
                if d.get("online"):
                    target = d
                    break

        if not target:
            error("No online devices found")

        alexa = AlexaAPI(DeviceWrapper(target), login)
        await alexa.set_volume(level)

        output({
            "success": True,
            "device": target.get("accountName"),
            "volume": level
        })

    except Exception as e:
        error(f"Failed to set volume: {str(e)}")


async def list_routines() -> None:
    """List available Alexa routines."""
    login = await get_login()

    try:
        devices = await AlexaAPI.get_devices(login)
        target = None
        for d in devices:
            if d.get("online"):
                target = d
                break

        if not target:
            error("No online devices found")

        alexa = AlexaAPI(DeviceWrapper(target), login)
        routines = await alexa.get_automations()

        routine_list = []
        if routines:
            for routine in routines:
                routine_list.append({
                    "name": routine.get("name"),
                    "id": routine.get("automationId"),
                    "status": routine.get("status"),
                    "triggers": routine.get("triggers", [])
                })

        output({
            "routines": routine_list,
            "count": len(routine_list)
        })

    except Exception as e:
        error(f"Failed to list routines: {str(e)}")


async def trigger_routine(name: str) -> None:
    """Trigger an Alexa routine by name."""
    login = await get_login()

    try:
        devices = await AlexaAPI.get_devices(login)
        alexa_device = None
        for d in devices:
            if d.get("online"):
                alexa_device = d
                break

        if not alexa_device:
            error("No online devices found")

        alexa = AlexaAPI(DeviceWrapper(alexa_device), login)
        routines = await alexa.get_automations()

        # Find routine
        target = None
        if routines:
            for r in routines:
                if name.lower() in r.get("name", "").lower():
                    target = r
                    break

        if not target:
            error(f"Routine '{name}' not found")

        await alexa.run_routine(target.get("automationId"))

        output({
            "success": True,
            "routine": target.get("name")
        })

    except Exception as e:
        error(f"Failed to trigger routine: {str(e)}")


async def send_notification(message: str, title: Optional[str] = None) -> None:
    """Send notification to Alexa app."""
    login = await get_login()

    try:
        devices = await AlexaAPI.get_devices(login)
        target = None
        for d in devices:
            if d.get("online"):
                target = d
                break

        if not target:
            error("No online devices found")

        alexa = AlexaAPI(DeviceWrapper(target), login)
        await alexa.send_mobilepush(message, title=title or "Notification")

        output({
            "success": True,
            "message": message,
            "title": title or "Notification"
        })

    except Exception as e:
        error(f"Failed to send notification: {str(e)}")


async def send_voice_command(command: str) -> None:
    """Send a voice command to Alexa (like saying 'Alexa, ...')."""
    login = await get_login()

    try:
        devices = await AlexaAPI.get_devices(login)
        target = None
        # Prefer Echo devices for voice commands
        for d in devices:
            if d.get("online") and "ECHO" in d.get("deviceFamily", "").upper():
                target = d
                break
        if not target:
            for d in devices:
                if d.get("online"):
                    target = d
                    break

        if not target:
            error("No online devices found")

        alexa = AlexaAPI(DeviceWrapper(target), login)
        await alexa.run_custom(command)

        output({
            "success": True,
            "command": command,
            "device": target.get("accountName")
        })

    except Exception as e:
        error(f"Failed to send command: {str(e)}")
    finally:
        await login.close()


async def discover_smart_home() -> None:
    """Discover and cache smart home devices."""
    login = await get_login()
    config = load_config()

    try:
        devices = await AlexaAPI.get_devices(login)
        target = None
        for d in devices:
            if d.get("online"):
                target = d
                break

        if not target:
            error("No online devices found")

        alexa = AlexaAPI(DeviceWrapper(target), login)

        # Try to get smart home entities
        smart_devices = []
        try:
            # Use run_custom to ask Alexa to list devices
            # This triggers device discovery on Amazon's side
            await alexa.run_custom("discover my devices")
            await asyncio.sleep(2)  # Give it time to discover
        except:
            pass

        # Cache the Echo devices info for quick access
        echo_devices = []
        for d in devices:
            echo_devices.append({
                "name": d.get("accountName"),
                "serial": d.get("serialNumber"),
                "type": d.get("deviceType"),
                "family": d.get("deviceFamily"),
                "online": d.get("online", False)
            })

        # Update config with discovered devices
        config["echo_devices"] = echo_devices
        config["last_discovery"] = str(asyncio.get_event_loop().time())
        save_config(config)

        output({
            "success": True,
            "echo_devices": echo_devices,
            "message": "Device discovery triggered. Smart home devices will be available shortly."
        })

    except Exception as e:
        error(f"Failed to discover devices: {str(e)}")
    finally:
        await login.close()


def main():
    parser = argparse.ArgumentParser(
        description="Control Amazon Alexa/Echo devices",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Setup command
    setup_parser = subparsers.add_parser("setup", help="First-time authentication")
    setup_parser.add_argument("--email", "-e", required=True,
                              help="Amazon account email address")
    setup_parser.add_argument("--region", "-r", default="us",
                              choices=list(AMAZON_URLS.keys()),
                              help="Amazon region (default: us)")

    # Devices command
    subparsers.add_parser("devices", help="List Echo devices")

    # Say command - natural voice commands
    say_parser = subparsers.add_parser("say", help="Send voice command (e.g., 'turn off the lights')")
    say_parser.add_argument("voice_command", help="Voice command to send")

    # Discover command
    subparsers.add_parser("discover", help="Discover and cache smart home devices")

    # Announce command
    announce_parser = subparsers.add_parser("announce", help="Make announcement")
    announce_parser.add_argument("message", help="Message to announce")
    announce_parser.add_argument("--device", "-d", help="Target device name")
    announce_parser.add_argument("--all", "-a", action="store_true",
                                  help="Announce on all devices")

    # Speak command (TTS without chime)
    speak_parser = subparsers.add_parser("speak", help="Text-to-speech (no chime)")
    speak_parser.add_argument("message", help="Message to speak")
    speak_parser.add_argument("--device", "-d", help="Target device name")

    # Smart home command
    subparsers.add_parser("smart-home", help="List smart home devices")

    # Smart entities command (for silent control - shows entity IDs)
    subparsers.add_parser("smart-entities", help="List smart home devices with entity IDs for silent control")

    # Silent control command (no Alexa voice response)
    silent_parser = subparsers.add_parser("silent-control", help="Control device silently (no 'OK' response)")
    silent_parser.add_argument("entity_id", help="Entity ID of the device (from smart-entities)")
    silent_parser.add_argument("--action", "-a", required=True, choices=["on", "off"],
                                help="Turn device on or off")
    silent_parser.add_argument("--brightness", "-b", type=int, help="Brightness level (0-100)")
    silent_parser.add_argument("--color", "-c", help="Color name (e.g., red, blue, warm_white)")

    # Control command
    control_parser = subparsers.add_parser("control", help="Control smart home device")
    control_parser.add_argument("device", help="Device name")
    control_parser.add_argument("--action", "-a", required=True,
                                 choices=["on", "off", "toggle", "setBrightness", "setColor"],
                                 help="Action to perform")
    control_parser.add_argument("--value", "-v", help="Value for action (e.g., brightness level)")

    # Volume command
    volume_parser = subparsers.add_parser("volume", help="Set device volume")
    volume_parser.add_argument("level", type=int, help="Volume level (0-100)")
    volume_parser.add_argument("--device", "-d", help="Target device name")

    # Routines command
    subparsers.add_parser("routines", help="List routines")

    # Routine command (trigger)
    routine_parser = subparsers.add_parser("routine", help="Trigger routine")
    routine_parser.add_argument("name", help="Routine name")

    # Notify command
    notify_parser = subparsers.add_parser("notify", help="Send notification to Alexa app")
    notify_parser.add_argument("message", help="Notification message")
    notify_parser.add_argument("--title", "-t", help="Notification title")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Run appropriate command
    if args.command == "setup":
        asyncio.run(setup_auth(args.email, args.region))
    elif args.command == "devices":
        asyncio.run(list_devices())
    elif args.command == "say":
        asyncio.run(send_voice_command(args.voice_command))
    elif args.command == "discover":
        asyncio.run(discover_smart_home())
    elif args.command == "announce":
        asyncio.run(send_announcement(args.message, args.device, args.all))
    elif args.command == "speak":
        asyncio.run(send_tts(args.message, args.device))
    elif args.command == "smart-home":
        asyncio.run(list_smart_home())
    elif args.command == "smart-entities":
        asyncio.run(list_smart_entities())
    elif args.command == "silent-control":
        power_on = args.action == "on"
        asyncio.run(silent_control(args.entity_id, power_on, args.brightness, args.color))
    elif args.command == "control":
        asyncio.run(control_device(args.device, args.action, args.value))
    elif args.command == "volume":
        asyncio.run(set_volume(args.level, args.device))
    elif args.command == "routines":
        asyncio.run(list_routines())
    elif args.command == "routine":
        asyncio.run(trigger_routine(args.name))
    elif args.command == "notify":
        asyncio.run(send_notification(args.message, args.title))


if __name__ == "__main__":
    main()
