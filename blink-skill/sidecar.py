#!/usr/bin/env python3
"""
Blink sidecar — one warm blinkpy session behind a tiny loopback HTTP API.

WHY THIS EXISTS
    Blink's cloud rate-limits / temporarily locks out accounts that re-auth or
    over-poll. A polling dashboard must therefore NOT create a fresh blinkpy
    session per request and must NOT hammer blink.refresh(). This process holds
    ONE authenticated Blink() for its whole lifetime and hands every reader a
    cached, single-flight-throttled view.

RUN
    python3 sidecar.py
        -> binds 127.0.0.1:8787 (loopback ONLY; the Nuxt/Nitro layer is the
           only thing exposed on the LAN).

    First-time credential setup (2FA prompt) is done OUT OF BAND by the skill's
    CLI:  `blink_skill.py setup`. That writes credentials.json (chmod 600) with
    hardware_id + refresh_token so this sidecar can start() non-interactively
    forever after. If credentials.json is missing/invalid the server STILL
    starts, but every endpoint (except /health) returns 503 with a clear
    "not authenticated — run: blink_skill.py setup" message so the dashboard
    shows a message instead of crashing.

BATTERY SAFETY (load-bearing)
    - GET  /cameras and GET /snapshot.jpg are CACHE-ONLY. They read blinkpy's
      in-memory cache and, at most, trigger ONE throttled blink.refresh() per
      MIN_REFRESH seconds (single asyncio.Lock + 20s gate). They NEVER trigger
      a camera capture.
    - Only POST /snap (snap_picture -> sleep(5) -> refresh -> image_to_file) and
      POST /liveview actually spend battery; both warn for battery cameras and
      liveview is hard-capped + single-session.

TESTED AGAINST blinkpy 0.25.3. Notable version facts baked in here:
    - blinkpy.helpers.util.json_load / json_save are ASYNC (aiofiles).
    - blink.start() raises BlinkTwoFARequiredError on first (un-verified) login;
      returns False on other auth failures; returns truthy on success.
    - blink.refresh() is @Throttle(2s); force=True bypasses that inner throttle
      (we do our own 20s single-flight gate on top).
    - Wired cams are BlinkCameraMini / BlinkDoorbell; base BlinkCamera
      (Outdoor/Indoor) is battery.

Endpoints:  GET /health · GET /cameras[?refresh=1] · GET /networks ·
    GET /cameras/{name} · GET /cameras/{name}/snapshot.jpg ·
    POST /cameras/{name}/snap · POST /cameras/{name}/liveview ·
    GET /cameras/{name}/clips[?since,?limit] · POST /cameras/{name}/clip ·
    POST /arm · POST /disarm · GET /media/{file}
"""

from __future__ import annotations

import asyncio
import datetime
import mimetypes
import re
import time
from pathlib import Path

import aiohttp
from aiohttp import web

from blinkpy.blinkpy import (
    Blink,
    BlinkSetupError,
    BlinkTwoFARequiredError,
    LoginError,
    TokenRefreshFailed,
)
from blinkpy.auth import Auth
from blinkpy.camera import BlinkCameraMini, BlinkDoorbell
from blinkpy.helpers.util import BlinkException, json_load

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
SKILL_DIR = Path(__file__).resolve().parent
CREDS_FILE = SKILL_DIR / "credentials.json"
SNAP_DIR = SKILL_DIR / "snapshots"

HOST = "127.0.0.1"          # loopback ONLY
PORT = 8787

MIN_REFRESH = 20            # seconds — single-flight refresh gate (mandatory)
SNAP_SETTLE = 5            # seconds to wait after snap_picture() for the capture
LIVEVIEW_DEFAULT = 20      # seconds
LIVEVIEW_CAP = 30          # hard cap; a liveview session may never exceed this
CLIP_SINCE_DEFAULT_DAYS = 1

_MEDIA_EXT = {".jpg", ".jpeg", ".png", ".mp4"}


# --------------------------------------------------------------------------- #
# Shared, process-wide state (one warm session)
# --------------------------------------------------------------------------- #
class State:
    def __init__(self):
        self.session: aiohttp.ClientSession | None = None
        self.blink: Blink | None = None
        self.authenticated: bool = False
        self.last_refresh: float = 0.0            # time.monotonic() of last refresh
        self.refresh_lock = asyncio.Lock()        # single-flight refresh
        self.liveview_lock = asyncio.Lock()       # guards the single-session flag
        self.liveview_active: bool = False
        self.liveview_task: asyncio.Task | None = None


STATE = State()


# --------------------------------------------------------------------------- #
# Typed errors -> clean JSON responses (via middleware)
# --------------------------------------------------------------------------- #
class NotAuthed(Exception):
    """No usable Blink session."""


class CloudError(Exception):
    """A Blink cloud / auth call failed even after one reconnect."""


class Conflict(Exception):
    """Single-session resource already in use."""


class CamNotFound(Exception):
    def __init__(self, available):
        super().__init__("camera not found")
        self.available = available


# --------------------------------------------------------------------------- #
# Auth + refresh plumbing
# --------------------------------------------------------------------------- #
async def _authenticate() -> None:
    """Load creds and warm up ONE Blink session. Never raises — on any failure
    leaves STATE.authenticated False so endpoints report 503 cleanly."""
    STATE.session = aiohttp.ClientSession()
    STATE.blink = Blink(session=STATE.session)

    creds = await json_load(str(CREDS_FILE))     # async; None if missing/bad json
    if not creds:
        STATE.authenticated = False
        return

    STATE.blink.auth = Auth(creds, no_prompt=True, session=STATE.session)
    try:
        ok = await STATE.blink.start()            # uses saved refresh token
        STATE.authenticated = bool(ok)
    except BlinkTwoFARequiredError:
        # Saved creds are not verified — needs `blink_skill.py setup` (2FA).
        STATE.authenticated = False
    except Exception:
        STATE.authenticated = False

    if STATE.authenticated:
        # Prime the in-memory cache once so first reads are instant.
        try:
            await ensure_fresh(force=True)
        except Exception:
            pass


async def _reconnect() -> bool:
    """Attempt a single blink.start() re-auth. Returns success."""
    if STATE.blink is None:
        return False
    try:
        ok = await STATE.blink.start()
    except Exception:
        ok = False
    STATE.authenticated = bool(ok)
    return STATE.authenticated


async def with_reconnect(make_coro):
    """Run an awaitable factory; on an auth/session/cloud error, reconnect once
    and retry. Raises CloudError if it still fails."""
    try:
        return await make_coro()
    except (
        LoginError,
        TokenRefreshFailed,
        BlinkSetupError,
        BlinkTwoFARequiredError,
        BlinkException,
        aiohttp.ClientError,
        asyncio.TimeoutError,
    ) as first:
        if not await _reconnect():
            raise CloudError(f"cloud/auth failure: {first}")
        try:
            return await make_coro()
        except Exception as second:
            raise CloudError(f"cloud failure after reconnect: {second}")


async def ensure_fresh(force: bool = False) -> None:
    """Single-flight, throttled blink.refresh().

    N concurrent pollers collapse to <=1 network refresh per MIN_REFRESH
    seconds: the first caller through the lock refreshes; everyone queued behind
    it sees a fresh window and returns without another network call. `force`
    bypasses the 20s gate (used right after a capture) but still holds the lock
    so it can never race a concurrent refresh."""
    require_auth()
    async with STATE.refresh_lock:
        now = time.monotonic()
        if not force and (now - STATE.last_refresh) < MIN_REFRESH:
            return
        await with_reconnect(lambda: STATE.blink.refresh(force=True))
        STATE.last_refresh = time.monotonic()


def require_auth() -> None:
    if STATE.blink is None or not STATE.authenticated:
        raise NotAuthed()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_") or "cam"


def get_camera(name: str):
    """Case-insensitive camera lookup or CamNotFound(available=[...])."""
    require_auth()
    cam = STATE.blink.cameras.get(name)          # CaseInsensitiveDict
    if cam is None:
        raise CamNotFound(sorted(STATE.blink.cameras.keys()))
    return cam


def is_wired(cam) -> bool:
    """Mini + Doorbell are wired; base BlinkCamera (Outdoor/Indoor) is battery."""
    if isinstance(cam, (BlinkCameraMini, BlinkDoorbell)):
        return True
    ptype = str(getattr(cam, "product_type", "") or "").lower()
    return ptype in {"mini", "owl", "doorbell", "lotus"}


def _thumbnail_age_s(thumbnail) -> int | None:
    """Age (seconds) of the cached thumbnail, parsed from its `?ts=` epoch."""
    if not thumbnail:
        return None
    m = re.search(r"[?&]ts=(\d+)", str(thumbnail))
    if not m:
        return None
    try:
        return max(0, int(time.time()) - int(m.group(1)))
    except (ValueError, TypeError):
        return None


def _battery_voltage_v(cam):
    raw = getattr(cam, "battery_voltage", None)
    if raw in (None, ""):
        return None
    try:
        return round(int(raw) / 100.0, 2)         # blinkpy reports 100ths of a volt
    except (ValueError, TypeError):
        return None


def cam_summary(cam) -> dict:
    return {
        "name": cam.name,
        "type": cam.product_type or type(cam).__name__,
        "wired": is_wired(cam),
        "armed": bool(cam.motion_enabled),
        "battery": cam.battery,                    # "ok" / "low" / None (string)
        "battery_voltage_v": _battery_voltage_v(cam),
        "temperature_f": cam.temperature,
        "wifi_strength": cam.wifi_strength,
        "sync_signal_strength": cam.sync_signal_strength,
        "last_record": cam.last_record,
        "thumbnail_age_s": _thumbnail_age_s(cam.thumbnail),
    }


def cam_full(cam) -> dict:
    """Full status dict: blinkpy's own attributes plus our derived fields."""
    data = dict(cam.attributes)                    # includes temperature_c, recent_clips, ...
    data.update(
        {
            "wired": is_wired(cam),
            "battery_voltage_v": _battery_voltage_v(cam),
            "thumbnail_age_s": _thumbnail_age_s(cam.thumbnail),
            "recent_clips_count": len(getattr(cam, "recent_clips", []) or []),
        }
    )
    return data


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #
async def h_health(request: web.Request) -> web.Response:
    cams = len(STATE.blink.cameras) if STATE.blink else 0
    return web.json_response(
        {"ok": True, "session": STATE.authenticated, "cameras_count": cams}
    )


async def h_cameras(request: web.Request) -> web.Response:
    require_auth()
    # Cache-only by default; ?refresh=1 forces a throttled refresh first.
    if request.query.get("refresh") in ("1", "true", "yes"):
        await ensure_fresh(force=True)
    else:
        await ensure_fresh()                       # throttled; usually a no-op
    return web.json_response(
        [cam_summary(c) for c in STATE.blink.cameras.values()]
    )


async def h_networks(request: web.Request) -> web.Response:
    require_auth()
    await ensure_fresh()
    out = []
    for sync in STATE.blink.sync.values():
        out.append(
            {"name": sync.name, "armed": sync.arm, "online": sync.online}
        )
    return web.json_response(out)


async def h_camera(request: web.Request) -> web.Response:
    cam = get_camera(request.match_info["name"])
    await ensure_fresh()
    return web.json_response(cam_full(cam))


async def h_snapshot(request: web.Request) -> web.Response:
    """Serve the CACHED thumbnail bytes. Cheap, poll-safe, NEVER a capture."""
    cam = get_camera(request.match_info["name"])
    await ensure_fresh()                           # throttled; refreshes thumb, not capture
    data = cam.image_from_cache
    if not data:
        # Cache cold (e.g. just started) — force one refresh to populate it.
        await ensure_fresh(force=True)
        data = cam.image_from_cache
    if not data:
        raise CloudError("no cached thumbnail available for this camera")
    return web.Response(
        body=data,
        content_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


async def h_snap(request: web.Request) -> web.Response:
    """FRESH capture: snap_picture -> sleep(5) -> refresh(force) -> image_to_file."""
    cam = get_camera(request.match_info["name"])
    warn = None if is_wired(cam) else "battery camera — a fresh capture spends battery"

    async def _do():
        await cam.snap_picture()
        await asyncio.sleep(SNAP_SETTLE)
        await ensure_fresh(force=True)
        fname = f"{_safe_name(cam.name)}_{int(time.time())}.jpg"
        await cam.image_to_file(str(SNAP_DIR / fname))
        return fname

    fname = await with_reconnect(_do)
    path = SNAP_DIR / fname
    if not path.exists() or path.stat().st_size == 0:
        raise CloudError("capture completed but no image was written")
    body = {"captured": True, "file": f"/media/{fname}"}
    if warn:
        body["warn"] = warn
    return web.json_response(body)


async def h_liveview(request: web.Request) -> web.Response:
    """Hard-capped, single-session liveview.

    rtsps  -> return the ffmpeg-playable url directly.
    immis  -> spin up blinkpy's local TCP relay on 127.0.0.1 and return its
              address; a reaper stops it after `seconds`.
    else   -> fall back to a one-shot "snapburst" (fresh capture image)."""
    cam = get_camera(request.match_info["name"])
    try:
        payload = await request.json() if request.can_read_body else {}
    except Exception:
        payload = {}
    try:
        seconds = int(payload.get("seconds", LIVEVIEW_DEFAULT))
    except (TypeError, ValueError):
        seconds = LIVEVIEW_DEFAULT
    seconds = max(1, min(seconds, LIVEVIEW_CAP))   # hard cap
    warn = None if is_wired(cam) else "battery camera — liveview drains battery fast"

    # Enforce a single concurrent liveview session.
    async with STATE.liveview_lock:
        if STATE.liveview_active:
            raise Conflict("a liveview session is already active")
        STATE.liveview_active = True

    try:
        url = await with_reconnect(lambda: cam.get_liveview())
    except Exception:
        STATE.liveview_active = False
        raise

    try:
        if url.startswith("rtsps"):
            _schedule_liveview_reaper(None, seconds)
            body = {"mode": "rtsps", "url": url}
            if warn:
                body["warn"] = warn
            return web.json_response(body)

        if url.startswith("immis"):
            try:
                stream = await cam.init_livestream()
                server = await stream.start(host="127.0.0.1")
                port = server.sockets[0].getsockname()[1]
                _schedule_liveview_reaper(stream, seconds)
                body = {"mode": "immis", "url": f"tcp://127.0.0.1:{port}"}
                if warn:
                    body["warn"] = warn
                return web.json_response(body)
            except NotImplementedError:
                pass  # fall through to snapburst

        # Unknown/proprietary transport we can't relay -> snapburst fallback.
        fname = await _snapburst(cam)
        STATE.liveview_active = False
        body = {"mode": "snapburst", "url": f"/media/{fname}"}
        body["warn"] = warn or "liveview transport unsupported; returned a single fresh frame"
        return web.json_response(body)
    except Exception:
        STATE.liveview_active = False
        raise


async def _snapburst(cam) -> str:
    async def _do():
        await cam.snap_picture()
        await asyncio.sleep(SNAP_SETTLE)
        await ensure_fresh(force=True)
        fname = f"{_safe_name(cam.name)}_{int(time.time())}.jpg"
        await cam.image_to_file(str(SNAP_DIR / fname))
        return fname

    return await with_reconnect(_do)


def _schedule_liveview_reaper(stream, seconds: int) -> None:
    async def _reap():
        try:
            await asyncio.sleep(seconds)
        finally:
            if stream is not None:
                try:
                    await stream.stop()
                except Exception:
                    pass
            STATE.liveview_active = False
            STATE.liveview_task = None

    STATE.liveview_task = asyncio.create_task(_reap())


async def h_clips(request: web.Request) -> web.Response:
    cam = get_camera(request.match_info["name"])
    since = request.query.get("since")
    if not since:
        since_dt = datetime.datetime.now() - datetime.timedelta(days=CLIP_SINCE_DEFAULT_DAYS)
        since = since_dt.strftime("%Y/%m/%d %H:%M:%S")
    try:
        limit = int(request.query.get("limit", 25))
    except (TypeError, ValueError):
        limit = 25
    limit = max(1, min(limit, 200))

    meta = await with_reconnect(
        lambda: STATE.blink.get_videos_metadata(since=since, camera="all", stop=2)
    )
    base = ""
    try:
        base = STATE.blink.urls.base_url
    except Exception:
        base = ""

    target = str(cam.name).lower()
    out = []
    for item in meta or []:
        dev = item.get("device_name") or item.get("camera_name") or item.get("camera")
        if dev is not None and str(dev).lower() != target:
            continue
        media = item.get("media")
        if media and base and str(media).startswith("/"):
            media = f"{base}{media}"
        out.append(
            {
                "created_at": item.get("created_at") or item.get("created_at_iso"),
                "camera": dev,
                "media": media,
            }
        )
        if len(out) >= limit:
            break
    return web.json_response(out)


async def h_clip(request: web.Request) -> web.Response:
    """Download the last clip for this camera to snapshots/ and return its path."""
    cam = get_camera(request.match_info["name"])
    await ensure_fresh()                           # make sure cam.clip is populated
    fname = f"{_safe_name(cam.name)}_{int(time.time())}.mp4"
    path = SNAP_DIR / fname
    await with_reconnect(lambda: cam.video_to_file(str(path)))
    if not path.exists() or path.stat().st_size == 0:
        raise CloudError("no clip available to download for this camera")
    return web.json_response({"file": f"/media/{fname}"})


async def _arm_disarm(request: web.Request, value: bool) -> web.Response:
    require_auth()
    try:
        payload = await request.json() if request.can_read_body else {}
    except Exception:
        payload = {}
    network = payload.get("network")

    syncs = list(STATE.blink.sync.values())
    if network:
        target = str(network).lower()
        syncs = [s for s in syncs if str(s.name).lower() == target]
        if not syncs:
            return web.json_response(
                {
                    "error": f"network not found: {network}",
                    "available": [s.name for s in STATE.blink.sync.values()],
                },
                status=404,
            )

    async def _do():
        for sync in syncs:
            await sync.async_arm(value)

    await with_reconnect(_do)
    await ensure_fresh(force=True)                 # reflect new armed state
    return web.json_response({"armed": value})


async def h_arm(request: web.Request) -> web.Response:
    return await _arm_disarm(request, True)


async def h_disarm(request: web.Request) -> web.Response:
    return await _arm_disarm(request, False)


async def h_media(request: web.Request) -> web.StreamResponse:
    fname = Path(request.match_info["file"]).name   # strip any path traversal
    if Path(fname).suffix.lower() not in _MEDIA_EXT:
        return web.json_response({"error": "unsupported media type"}, status=404)
    path = (SNAP_DIR / fname).resolve()
    # Confine strictly to SNAP_DIR.
    try:
        path.relative_to(SNAP_DIR.resolve())
    except ValueError:
        return web.json_response({"error": "invalid path"}, status=404)
    if not path.exists():
        return web.json_response({"error": "not found"}, status=404)
    ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    return web.FileResponse(path, headers={"Content-Type": ctype})


# --------------------------------------------------------------------------- #
# Middleware: typed errors -> JSON + correct status codes
# --------------------------------------------------------------------------- #
@web.middleware
async def error_middleware(request: web.Request, handler):
    try:
        return await handler(request)
    except NotAuthed:
        return web.json_response(
            {"error": "not authenticated — run: blink_skill.py setup"}, status=503
        )
    except CamNotFound as e:
        return web.json_response(
            {"error": "camera not found", "available": e.available}, status=404
        )
    except Conflict as e:
        return web.json_response({"error": str(e)}, status=409)
    except CloudError as e:
        return web.json_response({"error": str(e)}, status=502)
    except web.HTTPException:
        raise
    except Exception as e:  # last-resort: never leak a stack to the dashboard
        return web.json_response({"error": f"internal error: {e}"}, status=500)


# --------------------------------------------------------------------------- #
# App wiring
# --------------------------------------------------------------------------- #
async def on_startup(app: web.Application) -> None:
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    await _authenticate()


async def on_cleanup(app: web.Application) -> None:
    if STATE.liveview_task and not STATE.liveview_task.done():
        STATE.liveview_task.cancel()
    if STATE.session and not STATE.session.closed:
        await STATE.session.close()


def build_app() -> web.Application:
    app = web.Application(middlewares=[error_middleware])
    app.add_routes(
        [
            web.get("/health", h_health),
            web.get("/cameras", h_cameras),
            web.get("/networks", h_networks),
            web.get("/cameras/{name}", h_camera),
            web.get("/cameras/{name}/snapshot.jpg", h_snapshot),
            web.post("/cameras/{name}/snap", h_snap),
            web.post("/cameras/{name}/liveview", h_liveview),
            web.get("/cameras/{name}/clips", h_clips),
            web.post("/cameras/{name}/clip", h_clip),
            web.post("/arm", h_arm),
            web.post("/disarm", h_disarm),
            web.get("/media/{file}", h_media),
        ]
    )
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app


def main() -> None:
    web.run_app(build_app(), host=HOST, port=PORT)


if __name__ == "__main__":
    main()
