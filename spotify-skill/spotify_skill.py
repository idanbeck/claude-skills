#!/usr/bin/env python3
"""
Spotify Skill - read liked songs, playlists, and top tracks; export a DJ crate.

Standard library only (urllib + http.server). No pip installs.

Usage:
    python3 spotify_skill.py setup --client-id ID [--port 8899]
    python3 spotify_skill.py login
    python3 spotify_skill.py me
    python3 spotify_skill.py liked [--limit N] [--all]
    python3 spotify_skill.py playlists [--all]
    python3 spotify_skill.py playlist PLAYLIST_ID_OR_URL [--limit N] [--all]
    python3 spotify_skill.py top-tracks [--range short|medium|long] [--limit N]
    python3 spotify_skill.py recently-played [--limit N]
    python3 spotify_skill.py search "query" [--limit N]
    python3 spotify_skill.py export-crate --name NAME (--liked | --playlist ID | --top) [--all] [--out PATH]
    python3 spotify_skill.py logout
"""

import argparse
import base64
import csv
import hashlib
import http.server
import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

SKILL_DIR = Path(__file__).parent
CONFIG_FILE = SKILL_DIR / "config.json"
TOKEN_FILE = SKILL_DIR / "tokens" / "spotify.json"
CRATE_DIR = Path.home() / ".claude" / "skills" / "beatport-skill" / "crates"

API = "https://api.spotify.com/v1"
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"

# Read-only scopes. No playlist-modify / no streaming control.
SCOPES = " ".join([
    "user-read-private",
    "user-library-read",
    "playlist-read-private",
    "playlist-read-collaborative",
    "user-top-read",
    "user-read-recently-played",
])


def die(msg, code=1):
    print(json.dumps({"error": msg}, indent=2))
    sys.exit(code)


def load_config():
    if not CONFIG_FILE.exists():
        die("Not configured. Run: spotify_skill.py setup --client-id YOUR_CLIENT_ID "
            "(create an app at https://developer.spotify.com/dashboard with redirect URI "
            "http://127.0.0.1:8899/callback)")
    return json.loads(CONFIG_FILE.read_text())


def save_tokens(tok):
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tok = dict(tok)
    if "expires_in" in tok:
        tok["expires_at"] = int(time.time()) + int(tok["expires_in"]) - 60
    TOKEN_FILE.write_text(json.dumps(tok, indent=2))
    os.chmod(TOKEN_FILE, 0o600)
    return tok


def http_json(url, data=None, headers=None, method=None):
    """Return (status, parsed_json_or_text)."""
    body = None
    hdrs = {"Accept": "application/json", "User-Agent": "claude-spotify-skill/1.0"}
    if headers:
        hdrs.update(headers)
    if data is not None:
        if isinstance(data, dict):
            body = urllib.parse.urlencode(data).encode()
            hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
        else:
            body = data
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:500]}


# ---------------------------------------------------------------- auth (PKCE)

class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    result = {}

    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _CallbackHandler.result = {k: v[0] for k, v in q.items()}
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        ok = "code" in _CallbackHandler.result
        self.wfile.write(
            b"<h2>Spotify authorized. You can close this tab.</h2>" if ok
            else b"<h2>Authorization failed. Check the terminal.</h2>")

    def log_message(self, *a):
        pass


def do_login():
    cfg = load_config()
    port = int(cfg.get("port", 8899))
    redirect = f"http://127.0.0.1:{port}/callback"

    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(16)

    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": cfg["client_id"],
        "response_type": "code",
        "redirect_uri": redirect,
        "scope": SCOPES,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
        "state": state,
    })

    srv = http.server.HTTPServer(("127.0.0.1", port), _CallbackHandler)
    threading.Thread(target=srv.handle_request, daemon=True).start()

    print(json.dumps({"open_this_url": url}, indent=2), file=sys.stderr)
    try:
        webbrowser.open(url)
    except Exception:
        pass

    deadline = time.time() + 180
    while not _CallbackHandler.result and time.time() < deadline:
        time.sleep(0.3)
    srv.server_close()

    res = _CallbackHandler.result
    if "code" not in res:
        die(f"No authorization code received: {res or 'timed out after 180s'}")
    if res.get("state") != state:
        die("State mismatch - aborting (possible CSRF).")

    status, tok = http_json(TOKEN_URL, data={
        "grant_type": "authorization_code",
        "code": res["code"],
        "redirect_uri": redirect,
        "client_id": cfg["client_id"],
        "code_verifier": verifier,
    })
    if status != 200 or "access_token" not in tok:
        die(f"Token exchange failed ({status}): {tok}")
    save_tokens(tok)
    return tok


def get_token():
    tok = json.loads(TOKEN_FILE.read_text()) if TOKEN_FILE.exists() else {}
    cfg = json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}

    # Live token from a completed PKCE login.
    if tok.get("access_token") and tok.get("expires_at", 0) > time.time():
        return tok["access_token"]

    # Expired but refreshable (PKCE mode).
    if tok.get("refresh_token") and cfg.get("client_id"):
        status, new = http_json(TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": tok["refresh_token"],
            "client_id": cfg["client_id"],
        })
        if status == 200 and "access_token" in new:
            new.setdefault("refresh_token", tok["refresh_token"])
            return save_tokens(new)["access_token"]
        die(f"Token refresh failed ({status}): {new}. Run: spotify_skill.py login")

    # Pasted web-player token: no expiry known, use until it 401s.
    if tok.get("access_token"):
        return tok["access_token"]

    die("No Spotify token. Either:\n"
        "  (a) paste one from your logged-in web player (no app needed):\n"
        "      open open.spotify.com > DevTools > Network > filter 'api.spotify.com'\n"
        "      > click a request > copy the Authorization header after 'Bearer '\n"
        "      spotify_skill.py setup --token 'BQ...'\n"
        "  (b) register an app and use PKCE:\n"
        "      spotify_skill.py setup --client-id YOUR_CLIENT_ID && spotify_skill.py login")


def api_get(path, **params):
    url = path if path.startswith("http") else API + path
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None})
    status, body = http_json(url, headers={"Authorization": f"Bearer {get_token()}"})
    if status == 401:
        die("401 from Spotify - the token expired. Web-player tokens last about an hour: "
            "re-copy it from open.spotify.com (DevTools > Network > any api.spotify.com "
            "request > Authorization header) and run "
            "`spotify_skill.py setup --token '<token>'` again.")
    if status == 403:
        die("403 from Spotify. Note: audio-features / audio-analysis / recommendations are "
            "permanently disabled for apps created after 2024-11-27 - get BPM and key from "
            f"Beatport instead. Response: {body}")
    if status == 429:
        die(f"Rate limited by Spotify. Wait and retry. Response: {body}")
    if status >= 400:
        die(f"Spotify API {status} on {url}: {body}")
    return body


def paged(path, limit, fetch_all, item_key="items", page_size=50, **params):
    """Walk Spotify's next-cursor pagination. Returns a flat list of items."""
    out, url = [], path
    params = dict(params)
    params["limit"] = min(page_size, limit if limit else page_size)
    first = True
    while url:
        body = api_get(url, **(params if first else {}))
        first = False
        out.extend(body.get(item_key) or [])
        url = body.get("next")
        if not fetch_all and limit and len(out) >= limit:
            break
        if not fetch_all and not limit:
            break
    return out[:limit] if (limit and not fetch_all) else out


# ------------------------------------------------------------- normalization

_MIX_RE = re.compile(r"[\(\[]([^)\]]*(?:mix|remix|edit|dub|version|vip|bootleg)[^)\]]*)[)\]]", re.I)


def norm_track(item):
    """Flatten a Spotify track object into the shared crate track shape."""
    t = item.get("track") or item
    if not t or t.get("type") == "episode" or not t.get("id"):
        return None
    artists = [a["name"] for a in (t.get("artists") or [])]
    title = t.get("name") or ""
    m = _MIX_RE.search(title)
    return {
        "source": "spotify",
        "source_id": t["id"],
        "url": (t.get("external_urls") or {}).get("spotify"),
        "artist": ", ".join(artists),
        "artists": artists,
        "title": title,
        "mix": (m.group(1).strip() if m else ""),
        "album": (t.get("album") or {}).get("name"),
        "release_date": (t.get("album") or {}).get("release_date"),
        "label": None,          # Spotify does not expose label on the track object
        "isrc": (t.get("external_ids") or {}).get("isrc"),
        "duration_ms": t.get("duration_ms"),
        "explicit": t.get("explicit"),
        "added_at": item.get("added_at") or item.get("played_at"),
        # BPM / key deliberately absent: Spotify killed audio-features for new apps.
        "bpm": None,
        "key": None,
    }


def norm_list(items):
    return [x for x in (norm_track(i) for i in items) if x]


def parse_playlist_id(s):
    s = s.strip()
    if "spotify.com" in s:
        m = re.search(r"/playlist/([A-Za-z0-9]+)", s)
        if m:
            return m.group(1)
    if s.startswith("spotify:playlist:"):
        return s.split(":")[-1]
    return s


# ------------------------------------------------------------------ commands

def cmd_setup(args):
    if not args.client_id and not args.token:
        die("Pass either --token (paste from the web player, no app needed) "
            "or --client-id (registered app, enables auto-refresh).")

    if args.token:
        save_tokens({"access_token": args.token.strip().replace("Bearer ", ""),
                     "source": "pasted-from-web-player"})

    cfg = json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
    if args.client_id:
        cfg["client_id"] = args.client_id
        cfg["port"] = args.port
        cfg["mode"] = "pkce"
    else:
        cfg.setdefault("mode", "pasted-token")
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    os.chmod(CONFIG_FILE, 0o600)

    result = {"saved": str(CONFIG_FILE), "mode": cfg.get("mode")}
    if args.client_id:
        result["redirect_uri_to_register"] = f"http://127.0.0.1:{args.port}/callback"
        result["reminder"] = ("Spotify rejects 'localhost' - the redirect URI must use the "
                              "literal 127.0.0.1.")
        result["next"] = "spotify_skill.py login"
    else:
        result["note"] = ("Web-player tokens expire after roughly an hour. Re-run setup "
                          "--token with a fresh one when you get a 401.")
        result["next"] = "spotify_skill.py me"
    print(json.dumps(result, indent=2))


def cmd_login(args):
    do_login()
    me = api_get("/me")
    print(json.dumps({"success": True, "user": me.get("display_name"),
                      "id": me.get("id"), "product": me.get("product")}, indent=2))


def cmd_logout(args):
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
    print(json.dumps({"success": True}, indent=2))


def cmd_me(args):
    me = api_get("/me")
    print(json.dumps({"id": me.get("id"), "display_name": me.get("display_name"),
                      "email": me.get("email"), "product": me.get("product"),
                      "country": me.get("country")}, indent=2))


def cmd_liked(args):
    items = paged("/me/tracks", args.limit, args.all)
    tracks = norm_list(items)
    print(json.dumps({"count": len(tracks), "tracks": tracks}, indent=2))


def cmd_playlists(args):
    items = paged("/me/playlists", args.limit, args.all)
    print(json.dumps({"count": len(items), "playlists": [{
        "id": p["id"],
        "name": p.get("name"),
        "tracks": (p.get("tracks") or {}).get("total"),
        "owner": (p.get("owner") or {}).get("display_name"),
        "public": p.get("public"),
        "url": (p.get("external_urls") or {}).get("spotify"),
    } for p in items if p]}, indent=2))


def cmd_playlist(args):
    pid = parse_playlist_id(args.playlist_id)
    meta = api_get(f"/playlists/{pid}", fields="name,description,tracks(total)")
    items = paged(f"/playlists/{pid}/tracks", args.limit, args.all, page_size=100)
    tracks = norm_list(items)
    print(json.dumps({"playlist_id": pid, "name": meta.get("name"),
                      "total": (meta.get("tracks") or {}).get("total"),
                      "count": len(tracks), "tracks": tracks}, indent=2))


def cmd_top_tracks(args):
    rng = {"short": "short_term", "medium": "medium_term", "long": "long_term"}[args.range]
    body = api_get("/me/top/tracks", time_range=rng, limit=min(args.limit or 50, 50))
    tracks = norm_list(body.get("items") or [])
    print(json.dumps({"range": rng, "count": len(tracks), "tracks": tracks}, indent=2))


def cmd_recently_played(args):
    body = api_get("/me/player/recently-played", limit=min(args.limit or 50, 50))
    tracks = norm_list(body.get("items") or [])
    print(json.dumps({"count": len(tracks), "tracks": tracks}, indent=2))


def cmd_search(args):
    body = api_get("/search", q=args.query, type="track", limit=min(args.limit or 20, 50))
    tracks = norm_list((body.get("tracks") or {}).get("items") or [])
    print(json.dumps({"query": args.query, "count": len(tracks), "tracks": tracks}, indent=2))


def cmd_export_crate(args):
    if args.playlist:
        pid = parse_playlist_id(args.playlist)
        meta = api_get(f"/playlists/{pid}", fields="name")
        items = paged(f"/playlists/{pid}/tracks", args.limit, args.all, page_size=100)
        origin = f"spotify:playlist:{pid} ({meta.get('name')})"
    elif args.top:
        items = (api_get("/me/top/tracks", time_range="short_term",
                         limit=min(args.limit or 50, 50))).get("items") or []
        origin = "spotify:top-tracks:short_term"
    else:
        items = paged("/me/tracks", args.limit, args.all)
        origin = "spotify:liked-songs"

    tracks = norm_list(items)
    crate = {
        "crate_version": 1,
        "name": args.name,
        "origin": origin,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "note": "bpm/key are null by design - Spotify's audio-features endpoint is disabled "
                "for apps created after 2024-11-27. Fill them via beatport_skill.py match.",
        "tracks": tracks,
    }
    out = Path(args.out) if args.out else (CRATE_DIR / f"{args.name}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(crate, indent=2))
    print(json.dumps({"written": str(out), "count": len(tracks),
                      "with_isrc": sum(1 for t in tracks if t.get("isrc")),
                      "origin": origin,
                      "next": f"python3 ~/.claude/skills/beatport-skill/beatport_skill.py "
                              f"match {out}"}, indent=2))


# ------------------------------------------------------- CSV import (no API)

# Spotify has had new developer-app creation frozen since Dec 2025, so the OAuth path
# is unavailable to new apps. A CSV from an existing exporter (Exportify and friends
# authorize against their own long-registered app) gets the same data, ISRC included.

_COLS = {
    "title":    ["track name", "name", "title", "song", "song name", "track"],
    "artist":   ["artist name(s)", "artist name", "artist", "artists", "artist(s)",
                 "artist names"],
    "isrc":     ["isrc"],
    "album":    ["album name", "album"],
    "duration": ["track duration (ms)", "duration (ms)", "duration_ms", "duration ms",
                 "duration"],
    "url":      ["track uri", "track url", "spotify uri", "spotify url", "uri", "url"],
    "added":    ["added at", "added_at", "date added"],
    "release":  ["album release date", "release date", "released"],
    "label":    ["record label", "label"],
    "genres":   ["genres", "genre", "artist genres"],
    "bpm":      ["tempo", "bpm"],
    "key":      ["key"],
    "mode":     ["mode"],
    "popularity": ["popularity"],
}

# Spotify encodes key as a pitch class 0-11 and mode as 1=major / 0=minor. Flat-preferring
# names so they feed straight into beatport-skill's Camelot table.
_PITCH = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


def _key_name(key_val, mode_val):
    """'7' + '1' -> 'G Major'. Passes through a name that is already spelled out."""
    if key_val is None or str(key_val).strip() == "":
        return None
    raw = str(key_val).strip()
    if re.fullmatch(r"-?\d+", raw):
        k = int(raw)
        if not 0 <= k <= 11:
            return None
        mode = str(mode_val).strip()
        if mode in ("0", "1"):
            return f"{_PITCH[k]} {'Major' if mode == '1' else 'Minor'}"
        return None
    return raw   # already something like "A Minor"


def _pick(headers, keys):
    """Map our field names onto whatever the CSV actually calls its columns."""
    norm = {h.strip().lower(): h for h in headers if h}
    found = {}
    for field, names in keys.items():
        for n in names:
            if n in norm:
                found[field] = norm[n]
                break
    return found


def _num(v):
    try:
        return round(float(str(v).strip()), 2)
    except (TypeError, ValueError):
        return None


def _dur_to_ms(v):
    if not v:
        return None
    v = str(v).strip()
    if re.fullmatch(r"\d+", v):
        n = int(v)
        # Heuristic: a bare number under ~10000 is seconds, above is milliseconds.
        return n * 1000 if n < 10000 else n
    m = re.fullmatch(r"(\d+):(\d{1,2})(?:\.\d+)?", v)
    if m:
        return (int(m.group(1)) * 60 + int(m.group(2))) * 1000
    return None


def cmd_import_csv(args):
    src = Path(args.csv).expanduser()
    if not src.exists():
        die(f"CSV not found: {src}")

    with src.open(newline="", encoding="utf-8-sig") as f:
        sample = f.read(8192)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        rows = list(csv.DictReader(f, dialect=dialect))

    if not rows:
        die(f"{src} has no data rows.")

    cols = _pick(rows[0].keys(), _COLS)
    if "title" not in cols or "artist" not in cols:
        die(f"Could not find artist and title columns in {src}. "
            f"Saw: {sorted(k for k in rows[0].keys() if k)}. "
            f"Rename the columns to 'Artist Name(s)' and 'Track Name', or pass a "
            f"different export.")

    tracks, skipped = [], 0
    for r in rows:
        title = (r.get(cols["title"]) or "").strip()
        artist = (r.get(cols["artist"]) or "").strip()
        if not title or not artist:
            skipped += 1
            continue
        uri = (r.get(cols.get("url", "")) or "").strip()
        sid = None
        m = re.search(r"(?:track[:/])([A-Za-z0-9]{22})", uri)
        if m:
            sid = m.group(1)
        mix = _MIX_RE.search(title)
        isrc = (r.get(cols.get("isrc", "")) or "").strip().upper() or None
        tracks.append({
            "source": "spotify-csv",
            "source_id": sid,
            "url": (f"https://open.spotify.com/track/{sid}" if sid else (uri or None)),
            "artist": artist,
            "artists": [a.strip() for a in re.split(r"\s*[;,]\s*", artist) if a.strip()],
            "title": title,
            "mix": (mix.group(1).strip() if mix else ""),
            "album": (r.get(cols.get("album", "")) or "").strip() or None,
            "release_date": (r.get(cols.get("release", "")) or "").strip() or None,
            "label": (r.get(cols.get("label", "")) or "").strip() or None,
            "genres": [g.strip() for g in
                       re.split(r"\s*[;,]\s*", (r.get(cols.get("genres", "")) or ""))
                       if g.strip()] or None,
            "popularity": (r.get(cols.get("popularity", "")) or "").strip() or None,
            "isrc": isrc,
            "duration_ms": _dur_to_ms(r.get(cols.get("duration", ""))),
            "added_at": (r.get(cols.get("added", "")) or "").strip() or None,
            # Provisional: some exporters still carry Spotify's audio-features. Treat as a
            # hint for filtering/ordering; Beatport's values are authoritative.
            "bpm": _num(r.get(cols.get("bpm", ""))),
            "key": _key_name(r.get(cols.get("key", "")), r.get(cols.get("mode", ""))),
        })

    crate = {
        "crate_version": 1,
        "name": args.name,
        "origin": f"csv:{src.name}",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "note": "Imported from a CSV export. bpm/key are filled in by beatport match.",
        "tracks": tracks,
    }
    out_path = Path(args.out) if args.out else (CRATE_DIR / f"{args.name}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(crate, indent=2, ensure_ascii=False))

    with_isrc = sum(1 for t in tracks if t["isrc"])
    print(json.dumps({
        "written": str(out_path),
        "count": len(tracks),
        "skipped_rows_missing_artist_or_title": skipped,
        "with_isrc": with_isrc,
        "isrc_coverage": f"{round(100 * with_isrc / len(tracks))}%" if tracks else "0%",
        "with_bpm": sum(1 for t in tracks if t.get("bpm")),
        "with_key": sum(1 for t in tracks if t.get("key")),
        "with_label": sum(1 for t in tracks if t.get("label")),
        "columns_used": cols,
        "next": f"python3 ~/.claude/skills/beatport-skill/beatport_skill.py match {out_path}",
    }, indent=2, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(description="Spotify Skill (read-only)")
    subs = p.add_subparsers(dest="command")

    s = subs.add_parser("setup")
    s.add_argument("--client-id")
    s.add_argument("--token", help="bearer token pasted from the Spotify web player")
    s.add_argument("--port", type=int, default=8899); s.set_defaults(func=cmd_setup)

    subs.add_parser("login").set_defaults(func=cmd_login)
    subs.add_parser("logout").set_defaults(func=cmd_logout)
    subs.add_parser("me").set_defaults(func=cmd_me)

    for name, fn in (("liked", cmd_liked), ("playlists", cmd_playlists)):
        s = subs.add_parser(name)
        s.add_argument("--limit", type=int, default=50)
        s.add_argument("--all", action="store_true")
        s.set_defaults(func=fn)

    s = subs.add_parser("playlist"); s.add_argument("playlist_id")
    s.add_argument("--limit", type=int, default=100)
    s.add_argument("--all", action="store_true"); s.set_defaults(func=cmd_playlist)

    s = subs.add_parser("top-tracks")
    s.add_argument("--range", choices=["short", "medium", "long"], default="short")
    s.add_argument("--limit", type=int, default=50); s.set_defaults(func=cmd_top_tracks)

    s = subs.add_parser("recently-played")
    s.add_argument("--limit", type=int, default=50); s.set_defaults(func=cmd_recently_played)

    s = subs.add_parser("search"); s.add_argument("query")
    s.add_argument("--limit", type=int, default=20); s.set_defaults(func=cmd_search)

    s = subs.add_parser("export-crate"); s.add_argument("--name", required=True)
    g = s.add_mutually_exclusive_group()
    g.add_argument("--liked", action="store_true")
    g.add_argument("--playlist")
    g.add_argument("--top", action="store_true")
    s.add_argument("--limit", type=int, default=None)
    s.add_argument("--all", action="store_true")
    s.add_argument("--out"); s.set_defaults(func=cmd_export_crate)

    s = subs.add_parser("import-csv")
    s.add_argument("csv")
    s.add_argument("--name", required=True)
    s.add_argument("--out")
    s.set_defaults(func=cmd_import_csv)

    args = p.parse_args()
    if not args.command:
        p.print_help(); sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
