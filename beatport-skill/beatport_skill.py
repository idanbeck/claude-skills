#!/usr/bin/env python3
"""
Beatport Skill - search the catalog, read your library/purchases/downloads, match a
Spotify/YouTube crate to buyable Beatport tracks, and prep a harmonically-ordered DJ set.

Standard library only (urllib + http.server). No pip installs.

This skill NEVER buys anything. It builds a costed purchase plan and hands you a URL;
checkout happens in your browser, by you.

Usage:
    python3 beatport_skill.py setup --token BEARER_TOKEN
    python3 beatport_skill.py setup --client-id ID [--port 8898]   # if you have an API client
    python3 beatport_skill.py login                                # PKCE, needs --client-id setup
    python3 beatport_skill.py auth-status
    python3 beatport_skill.py probe                                # discover which /my/ endpoints work
    python3 beatport_skill.py spec [--grep TEXT]                   # dump the real OpenAPI paths
    python3 beatport_skill.py get PATH [--param k=v ...]           # raw authenticated GET

    python3 beatport_skill.py search "query" [--limit N] [--type tracks|releases|artists]
    python3 beatport_skill.py track TRACK_ID
    python3 beatport_skill.py library [--limit N] [--all]
    python3 beatport_skill.py purchases [--limit N] [--all]
    python3 beatport_skill.py downloads [--limit N] [--all]

    python3 beatport_skill.py match CRATE.json [--out CRATE.json] [--min-score 0.72]
    python3 beatport_skill.py plan CRATE.json                      # what to buy + cost, no purchase
    python3 beatport_skill.py report CRATE.json [--target-bpm N]   # harmonic set order
    python3 beatport_skill.py organize CRATE.json --dir PATH       # match downloads to crate, m3u8
    python3 beatport_skill.py camelot "A Minor"
"""

import argparse
import base64
import difflib
import hashlib
import http.server
import json
import os
import re
import secrets
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

SKILL_DIR = Path(__file__).parent
CONFIG_FILE = SKILL_DIR / "config.json"
TOKEN_FILE = SKILL_DIR / "tokens" / "beatport.json"
CACHE_FILE = SKILL_DIR / "cache.json"
CRATE_DIR = SKILL_DIR / "crates"

API = "https://api.beatport.com/v4"
AUTH_URL = f"{API}/auth/o/authorize/"
TOKEN_URL = f"{API}/auth/o/token/"
SPEC_URL = f"{API}/swagger-ui/json/"
WEB = "https://www.beatport.com"

# Verified live 2026-08-27: api.beatport.com/v4 answers JSON 401 unauthenticated (no
# Cloudflare challenge), while www.beatport.com returns a Cloudflare interstitial to
# scripts. So: data over the API, anything on www.* through a real browser.
MY_ENDPOINT_CANDIDATES = [
    "/my/account/",
    "/my/beatport/tracks/",
    "/my/beatport/",
    "/my/downloads/",
    "/my/purchases/",
    "/my/orders/",
    "/my/carts/",
    "/my/cart/",
    "/my/playlists/",
    "/my/collection/tracks/",
    "/my/library/",
    "/my/wishlist/",
    "/my/subscription/",
]


def die(msg, code=1):
    print(json.dumps({"error": msg}, indent=2))
    sys.exit(code)


def out(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


# --------------------------------------------------------------------- config

def load_config():
    if not CONFIG_FILE.exists():
        die("Not configured. Either:\n"
            "  (a) paste a bearer token from your logged-in Beatport session:\n"
            "      beatport_skill.py setup --token 'eyJ...'\n"
            "  (b) if you have a registered Beatport API client:\n"
            "      beatport_skill.py setup --client-id YOUR_CLIENT_ID")
    return json.loads(CONFIG_FILE.read_text())


def save_config(cfg):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    os.chmod(CONFIG_FILE, 0o600)


def save_tokens(tok):
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tok = dict(tok)
    if "expires_in" in tok:
        tok["expires_at"] = int(time.time()) + int(tok["expires_in"]) - 60
    TOKEN_FILE.write_text(json.dumps(tok, indent=2))
    os.chmod(TOKEN_FILE, 0o600)
    return tok


# ----------------------------------------------------------------------- http

def http_json(url, data=None, headers=None, method=None, timeout=45):
    hdrs = {"Accept": "application/json", "User-Agent": "claude-beatport-skill/1.0"}
    if headers:
        hdrs.update(headers)
    body = None
    if data is not None:
        if isinstance(data, dict):
            body = urllib.parse.urlencode(data).encode()
            hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
        else:
            body = data
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:500]}
    except Exception as e:
        return 0, {"error": str(e)}


# ----------------------------------------------------------------- auth: PKCE

class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    result = {}

    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _CallbackHandler.result = {k: v[0] for k, v in q.items()}
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<h2>Beatport authorized. You can close this tab.</h2>")

    def log_message(self, *a):
        pass


def do_login():
    cfg = load_config()
    if not cfg.get("client_id"):
        die("No client_id configured. Beatport's /auth/o/token/ rejects unknown clients with "
            "{'error':'invalid_client'}, so PKCE needs a registered client. Use "
            "`setup --token` with a bearer token from your browser session instead.")
    port = int(cfg.get("port", 8898))
    redirect = cfg.get("redirect_uri") or f"http://127.0.0.1:{port}/callback"

    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(16)

    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": cfg["client_id"], "response_type": "code",
        "redirect_uri": redirect, "scope": cfg.get("scope", "library"),
        "code_challenge_method": "S256", "code_challenge": challenge, "state": state,
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
        die(f"No authorization code received: {res or 'timed out'}. Note that "
            "/auth/o/authorize/ redirects to Beatport's login page if your browser has no "
            "Beatport session - log in there first, then retry.")
    if res.get("state") != state:
        die("State mismatch - aborting.")

    status, tok = http_json(TOKEN_URL, data={
        "grant_type": "authorization_code", "code": res["code"],
        "redirect_uri": redirect, "client_id": cfg["client_id"],
        "code_verifier": verifier,
    })
    if status != 200 or "access_token" not in tok:
        die(f"Token exchange failed ({status}): {tok}")
    return save_tokens(tok)


def get_token():
    cfg = load_config()
    tok = json.loads(TOKEN_FILE.read_text()) if TOKEN_FILE.exists() else {}

    if tok.get("access_token") and tok.get("expires_at", 0) > time.time():
        return tok["access_token"]

    if tok.get("refresh_token") and cfg.get("client_id"):
        status, new = http_json(TOKEN_URL, data={
            "grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
            "client_id": cfg["client_id"]})
        if status == 200 and "access_token" in new:
            new.setdefault("refresh_token", tok["refresh_token"])
            return save_tokens(new)["access_token"]

    # Pasted-token mode: no expiry known, use until it 401s.
    if tok.get("access_token"):
        return tok["access_token"]
    if cfg.get("access_token"):
        return cfg["access_token"]

    die("No usable Beatport token. Run `setup --token` (paste from browser DevTools) "
        "or `login` if you have a client_id.")


def api_get(path, params=None, quiet=False):
    url = path if path.startswith("http") else API + ("" if path.startswith("/") else "/") + path
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None})
    status, body = http_json(url, headers={"Authorization": f"Bearer {get_token()}"})
    if quiet:
        return status, body
    if status == 401:
        die("401 from Beatport - your token expired. Grab a fresh one: open beatport.com "
            "logged in, DevTools > Network > any api.beatport.com request > copy the "
            "Authorization header value after 'Bearer ', then "
            "`beatport_skill.py setup --token '<token>'`.")
    if status == 403:
        die(f"403 from Beatport on {url}. Your token may lack the scope for this endpoint: {body}")
    if status >= 400:
        die(f"Beatport API {status} on {url}: {body}")
    return body


def api_paged(path, limit=None, fetch_all=False, params=None, per_page=100):
    params = dict(params or {})
    params["per_page"] = min(per_page, 100)
    params["page"] = 1
    items = []
    while True:
        body = api_get(path, params)
        got = body.get("results") if isinstance(body, dict) else None
        if got is None:
            got = body if isinstance(body, list) else []
        items.extend(got)
        if not fetch_all and limit and len(items) >= limit:
            break
        has_next = isinstance(body, dict) and body.get("next")
        if not has_next:
            break
        params["page"] += 1
        if params["page"] > 200:
            break
    return items[:limit] if (limit and not fetch_all) else items


# -------------------------------------------------------------- camelot / key

_CAMELOT = {
    ("a", "minor"): "8A", ("e", "minor"): "9A", ("b", "minor"): "10A",
    ("f#", "minor"): "11A", ("db", "minor"): "12A", ("ab", "minor"): "1A",
    ("eb", "minor"): "2A", ("bb", "minor"): "3A", ("f", "minor"): "4A",
    ("c", "minor"): "5A", ("g", "minor"): "6A", ("d", "minor"): "7A",
    ("c", "major"): "8B", ("g", "major"): "9B", ("d", "major"): "10B",
    ("a", "major"): "11B", ("e", "major"): "12B", ("b", "major"): "1B",
    ("f#", "major"): "2B", ("db", "major"): "3B", ("ab", "major"): "4B",
    ("eb", "major"): "5B", ("bb", "major"): "6B", ("f", "major"): "7B",
}
_ENHARMONIC = {"c#": "db", "d#": "eb", "g#": "ab", "a#": "bb", "gb": "f#",
               "cb": "b", "e#": "f", "fb": "e"}


def to_camelot(key_name):
    """'A Minor' / 'F# min' / 'Db Major' -> '8A'. None if unparseable."""
    if not key_name:
        return None
    s = str(key_name).strip().lower().replace("♯", "#").replace("♭", "b")
    # Beatport spells some keys with both enharmonics, e.g. "C#/Db Minor" -> take the first.
    s = re.sub(r"^([a-g][#b]?)\s*/\s*[a-g][#b]?", r"\1", s)
    m = re.match(r"^([a-g])\s*([#b]?)\s*(?:-|\s)*\s*(maj|min|major|minor)", s)
    if not m:
        return None
    root = m.group(1) + m.group(2)
    root = _ENHARMONIC.get(root, root)
    mode = "minor" if m.group(3).startswith("min") else "major"
    return _CAMELOT.get((root, mode))


def camelot_neighbors(code):
    """Harmonically compatible codes: same, +/-1 on the wheel, and the relative swap."""
    if not code:
        return []
    m = re.match(r"^(\d{1,2})([AB])$", code.upper())
    if not m:
        return []
    n, letter = int(m.group(1)), m.group(2)
    other = "B" if letter == "A" else "A"
    return [f"{n}{letter}", f"{(n % 12) + 1}{letter}",
            f"{((n - 2) % 12) + 1}{letter}", f"{n}{other}"]


# ---------------------------------------------------------- track normalizing

def norm_bp_track(t):
    if not isinstance(t, dict):
        return None
    key = t.get("key") or {}
    key_name = key.get("name") if isinstance(key, dict) else key
    camelot = None
    if isinstance(key, dict) and key.get("camelot_number"):
        camelot = f"{key['camelot_number']}{key.get('camelot_letter', '')}".strip()
    camelot = camelot or to_camelot(key_name)
    release = t.get("release") or {}
    price = t.get("price") or {}
    slug = t.get("slug") or ""
    tid = t.get("id")
    return {
        "beatport_id": tid,
        "artist": ", ".join(a.get("name", "") for a in (t.get("artists") or [])),
        "remixers": [a.get("name", "") for a in (t.get("remixers") or [])],
        "title": t.get("name"),
        "mix": t.get("mix_name"),
        "release": release.get("name"),
        "label": ((release.get("label") or {}) or {}).get("name"),
        "genre": (t.get("genre") or {}).get("name") if isinstance(t.get("genre"), dict) else t.get("genre"),
        "bpm": t.get("bpm"),
        "key": key_name,
        "camelot": camelot,
        "isrc": t.get("isrc"),
        "length_ms": t.get("length_ms"),
        "publish_date": t.get("publish_date") or t.get("new_release_date"),
        "exclusive": t.get("exclusive"),
        "pre_order": t.get("pre_order"),
        "price": price.get("display") or price.get("value"),
        "price_value": price.get("value"),
        "url": f"{WEB}/track/{slug}/{tid}" if (slug and tid) else (
            f"{WEB}/track/-/{tid}" if tid else None),
    }


def _fold(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(feat|ft|featuring|with|pres|presents)\b.*", " ", s)
    s = re.sub(r"[\(\[].*?[\)\]]", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _fold_keep(s):
    """Like _fold but keeps bracketed text - remix credits live in parentheses."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


_STOP = {"the", "of", "and", "in", "a", "an", "feat", "ft", "vs", "x", "on", "to", "my"}


def _sig_tokens(s):
    return {t for t in _fold_keep(s).split() if len(t) > 2 and t not in _STOP}


def _mixfold(s):
    s = _fold(s)
    return re.sub(r"\b(original|extended|radio|club|edit|mix|version)\b", "", s).strip()


def score_match(crate_track, bp):
    """0..1 similarity between a crate track and a Beatport candidate."""
    ct, ca = _fold(crate_track.get("title")), _fold(crate_track.get("artist"))
    bt, ba = _fold(bp.get("title")), _fold(bp.get("artist"))
    if not ct or not bt:
        return 0.0
    bt_full = _fold(f"{bp.get('title')} {bp.get('mix') or ''}")
    t = max(difflib.SequenceMatcher(None, ct, bt).ratio(),
            difflib.SequenceMatcher(None, ct, bt_full).ratio())
    a = difflib.SequenceMatcher(None, ca, ba).ratio()
    # Artist tokens overlapping is a stronger signal than raw string ratio.
    ca_set, ba_set = set(ca.split()), set(ba.split())
    if ca_set and ba_set:
        a = max(a, len(ca_set & ba_set) / len(ca_set | ba_set))
    s = 0.62 * t + 0.38 * a
    # Mix/remix handling. A wrong remix is a wrong track for a DJ, so this is a real
    # penalty, not a tiebreak: "Glue (Original Mix)" must not silently match
    # "Glue (Chaos In The CBD Remix)".
    cm, bm = _mixfold(crate_track.get("mix")), _mixfold(bp.get("mix"))
    if cm and bm:
        s += 0.06 if difflib.SequenceMatcher(None, cm, bm).ratio() > 0.7 else -0.06

    remixer_toks = _sig_tokens(" ".join(bp.get("remixers") or []))
    bp_mix_raw = _fold_keep(bp.get("mix"))
    bp_is_remix = bool(remixer_toks) or bool(
        re.search(r"\b(remix|vip|bootleg|rework|refix|flip)\b", bp_mix_raw))
    if bp_is_remix:
        # Did the crate side actually ask for this remix? Spotify folds the remixer into
        # the track title ("Grey (Tale Of Us Remix)"), so look at title + mix, brackets
        # included, and require every significant remixer token to be present.
        crate_toks = _sig_tokens(f"{crate_track.get('title')} {crate_track.get('mix')}")
        if remixer_toks:
            named = remixer_toks <= crate_toks
        else:
            named = bool(_sig_tokens(bp.get("mix")) & crate_toks)
        # Asymmetric on purpose: buying the wrong remix is the expensive mistake, so an
        # unrequested remix drops out of auto-match and into the review pile.
        s += 0.05 if named else -0.35
    dur_c, dur_b = crate_track.get("duration_ms"), bp.get("length_ms")
    if dur_c and dur_b:
        if abs(dur_c - dur_b) <= 5000:
            s += 0.04
        elif abs(dur_c - dur_b) > 45000:
            s -= 0.08
    return max(0.0, min(1.0, s))


def bp_search_tracks(q, limit=20):
    body = api_get("/catalog/search/", {"q": q, "type": "tracks", "per_page": min(limit, 100)})
    raw = body.get("tracks")
    if raw is None:
        raw = body.get("results") or []
    return [x for x in (norm_bp_track(t) for t in raw) if x]


# ------------------------------------------------------------------- commands

def cmd_setup(args):
    cfg = json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
    if args.token:
        save_tokens({"access_token": args.token.strip().replace("Bearer ", ""),
                     "source": "pasted-from-browser"})
        cfg.setdefault("mode", "pasted-token")
    if args.client_id:
        cfg["client_id"] = args.client_id
        cfg["port"] = args.port
        cfg["mode"] = "pkce"
    if args.redirect_uri:
        cfg["redirect_uri"] = args.redirect_uri
    save_config(cfg)
    out({"saved": str(CONFIG_FILE), "mode": cfg.get("mode"),
         "redirect_uri": cfg.get("redirect_uri") or f"http://127.0.0.1:{args.port}/callback",
         "next": "beatport_skill.py auth-status"})


def cmd_auth_status(args):
    status, body = api_get("/my/account/", quiet=True)
    out({"http": status, "authenticated": status == 200,
         "account": body if status == 200 else None,
         "detail": None if status == 200 else body})


def cmd_probe(args):
    """Find which /my/ endpoints this account+token can actually reach."""
    results = []
    for p in MY_ENDPOINT_CANDIDATES:
        status, body = api_get(p, {"per_page": 1}, quiet=True)
        sample = None
        if status == 200 and isinstance(body, dict):
            sample = {"count": body.get("count"),
                      "keys": sorted(body.keys())[:12],
                      "first_result_keys": sorted((body.get("results") or [{}])[0].keys())[:20]
                      if body.get("results") else None}
        results.append({"path": p, "http": status, "ok": status == 200, "shape": sample})
    working = [r["path"] for r in results if r["ok"]]
    cache = json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}
    cache["my_endpoints"] = working
    cache["probed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    CACHE_FILE.write_text(json.dumps(cache, indent=2))
    out({"working": working, "all": results, "cached_to": str(CACHE_FILE)})


def cmd_spec(args):
    status, body = api_get(SPEC_URL, quiet=True)
    if status != 200:
        die(f"Could not read the OpenAPI spec ({status}). It is auth-gated; "
            f"make sure your token is valid. Response: {body}")
    paths = sorted((body.get("paths") or {}).keys())
    if args.grep:
        paths = [p for p in paths if args.grep.lower() in p.lower()]
    cache = json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}
    cache["spec_paths"] = sorted((body.get("paths") or {}).keys())
    cache["spec_fetched_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    CACHE_FILE.write_text(json.dumps(cache, indent=2))
    out({"count": len(paths), "paths": paths, "cached_to": str(CACHE_FILE)})


def cmd_get(args):
    params = {}
    for kv in (args.param or []):
        k, _, v = kv.partition("=")
        params[k] = v
    out(api_get(args.path, params))


def cmd_search(args):
    if args.type == "tracks":
        tracks = bp_search_tracks(args.query, args.limit)
        out({"query": args.query, "count": len(tracks), "tracks": tracks})
    else:
        out(api_get("/catalog/search/",
                    {"q": args.query, "type": args.type, "per_page": args.limit}))


def cmd_track(args):
    out(norm_bp_track(api_get(f"/catalog/tracks/{args.track_id}/")))


def _my_listing(path_candidates, args, label):
    cache = json.loads(CACHE_FILE.read_text()) if CACHE_FILE.exists() else {}
    known = cache.get("my_endpoints") or []
    tried = []
    for p in path_candidates:
        if known and p not in known:
            continue
        status, body = api_get(p, {"per_page": 1}, quiet=True)
        tried.append({"path": p, "http": status})
        if status == 200:
            items = api_paged(p, args.limit, args.all)
            norm = [norm_bp_track(i.get("track") or i) or i
                    if isinstance(i, dict) else i for i in items]
            out({"source": p, "count": len(norm), label: norm})
            return
    die(f"No working endpoint for {label}. Tried: {tried}. "
        f"Run `beatport_skill.py probe` and `spec --grep my` to discover the real path "
        f"for your account, then use `get <path>` directly.")


def cmd_library(args):
    _my_listing(["/my/beatport/tracks/", "/my/collection/tracks/", "/my/library/"],
                args, "tracks")


def cmd_purchases(args):
    _my_listing(["/my/purchases/", "/my/orders/"], args, "purchases")


def cmd_downloads(args):
    _my_listing(["/my/downloads/"], args, "downloads")


def load_crate(path):
    p = Path(path)
    if not p.exists():
        p2 = CRATE_DIR / f"{path}.json"
        if p2.exists():
            p = p2
        else:
            die(f"Crate not found: {path}")
    crate = json.loads(p.read_text())
    if "tracks" not in crate:
        die(f"{p} is not a crate file (no 'tracks' key).")
    crate["_path"] = str(p)
    return crate


def cmd_match(args):
    crate = load_crate(args.crate)
    tracks = crate["tracks"]
    matched = ambiguous = missing = 0

    for t in tracks:
        if t.get("beatport") and t["beatport"].get("beatport_id") and not args.refresh:
            matched += 1
            continue

        best, method, candidates = None, None, []

        # 1. ISRC is exact. Spotify gives it; use it whenever it exists.
        if t.get("isrc"):
            hits = bp_search_tracks(t["isrc"], 10)
            exact = [h for h in hits if (h.get("isrc") or "").upper() == t["isrc"].upper()]
            if exact:
                best, method = exact[0], "isrc"

        # 2. Fall back to artist + title (+ mix), scored.
        if not best:
            queries = [f"{t.get('artist','')} {t.get('title','')}".strip()]
            if t.get("mix"):
                queries.insert(0, f"{t.get('artist','')} {t.get('title','')} {t['mix']}".strip())
            seen = {}
            for q in queries:
                if not q:
                    continue
                for h in bp_search_tracks(q, 25):
                    if h.get("beatport_id") not in seen:
                        seen[h["beatport_id"]] = h
            scored = sorted(((score_match(t, h), h) for h in seen.values()),
                            key=lambda x: -x[0])
            candidates = [{"score": round(s, 3), **h} for s, h in scored[:5]]
            if scored and scored[0][0] >= args.min_score:
                runner = scored[1][0] if len(scored) > 1 else 0.0
                best, method = scored[0][1], "fuzzy"
                if scored[0][0] - runner < 0.05:
                    method = "fuzzy-ambiguous"

        if best:
            t["beatport"] = {**best, "match_method": method,
                             "match_score": round(score_match(t, best), 3)
                             if method != "isrc" else 1.0,
                             "purchased": False}
            if method == "fuzzy-ambiguous":
                t["beatport"]["candidates"] = candidates
                ambiguous += 1
            else:
                matched += 1
        else:
            t["beatport"] = None
            t["beatport_candidates"] = candidates
            missing += 1

        time.sleep(args.delay)

    dest = Path(args.out) if args.out else Path(crate["_path"])
    crate.pop("_path", None)
    crate["matched_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    dest.write_text(json.dumps(crate, indent=2, ensure_ascii=False))
    out({"written": str(dest), "total": len(tracks), "matched": matched,
         "ambiguous_needs_review": ambiguous, "unmatched": missing,
         "next": f"beatport_skill.py plan {dest}"})


def cmd_plan(args):
    crate = load_crate(args.crate)
    buy, own, unmatched, review = [], [], [], []
    for t in crate["tracks"]:
        bp = t.get("beatport")
        if not bp:
            unmatched.append({"artist": t.get("artist"), "title": t.get("title"),
                              "source": t.get("source"), "url": t.get("url")})
            continue
        row = {"artist": bp.get("artist"), "title": bp.get("title"), "mix": bp.get("mix"),
               "label": bp.get("label"), "bpm": bp.get("bpm"), "key": bp.get("key"),
               "camelot": bp.get("camelot"), "price": bp.get("price"),
               "price_value": bp.get("price_value"), "beatport_id": bp.get("beatport_id"),
               "url": bp.get("url"), "match": bp.get("match_method"),
               "score": bp.get("match_score")}
        if bp.get("purchased"):
            own.append(row)
        elif bp.get("match_method") == "fuzzy-ambiguous":
            review.append(row)
        else:
            buy.append(row)

    total = sum(float(r["price_value"] or 0) for r in buy)
    # Beatport prices come back in minor units on some endpoints; flag rather than guess.
    est = round(total / 100, 2) if total > 200 else round(total, 2)

    out({
        "crate": crate.get("name"),
        "to_buy": buy,
        "needs_review_before_buying": review,
        "already_owned": own,
        "unmatched_on_beatport": unmatched,
        "counts": {"buy": len(buy), "review": len(review),
                   "owned": len(own), "unmatched": len(unmatched)},
        "estimated_total": est,
        "estimated_total_raw_sum": total,
        "cart_urls": [r["url"] for r in buy],
        "PURCHASE_GATE": "This skill does not buy anything. Review the list and the total, "
                         "then open the URLs and check out yourself at beatport.com.",
    })


def harmonic_order(rows, bpm_key="bpm", camelot_key="camelot"):
    """Greedy walk: start at the slowest track, then repeatedly take the candidate that is
    harmonically compatible (Camelot neighbour) with the smallest BPM step. Not a globally
    optimal ordering - a sane, mixable starting point you then hand-tune."""
    pool = [r for r in rows if r.get(bpm_key) and r.get(camelot_key)]
    if not pool:
        return []
    pool.sort(key=lambda r: r[bpm_key] or 0)
    order = [pool.pop(0)]
    while pool:
        cur = order[-1]
        compat = camelot_neighbors(cur.get(camelot_key))
        pool.sort(key=lambda r: (0 if r.get(camelot_key) in compat else 1,
                                 abs((r.get(bpm_key) or 0) - (cur.get(bpm_key) or 0))))
        order.append(pool.pop(0))
    return order


def cmd_report(args):
    crate = load_crate(args.crate)
    rows = []
    for t in crate["tracks"]:
        bp = t.get("beatport") or {}
        rows.append({
            "artist": bp.get("artist") or t.get("artist"),
            "title": bp.get("title") or t.get("title"),
            "mix": bp.get("mix") or t.get("mix"),
            "bpm": bp.get("bpm"),
            "key": bp.get("key"),
            "camelot": bp.get("camelot"),
            "label": bp.get("label"),
            "have_metadata": bool(bp.get("bpm") and bp.get("camelot")),
        })

    usable = [r for r in rows if r["have_metadata"]]
    if args.target_bpm:
        usable = [r for r in usable
                  if abs((r["bpm"] or 0) - args.target_bpm) <= args.bpm_tolerance]

    order = harmonic_order(usable)

    transitions = []
    for a, b in zip(order, order[1:]):
        transitions.append({
            "from": f"{a['artist']} - {a['title']}",
            "to": f"{b['artist']} - {b['title']}",
            "bpm": f"{a['bpm']} -> {b['bpm']}",
            "camelot": f"{a['camelot']} -> {b['camelot']}",
            "harmonic": b["camelot"] in camelot_neighbors(a["camelot"]),
            "bpm_jump": round(abs((b["bpm"] or 0) - (a["bpm"] or 0)), 1),
        })

    out({
        "crate": crate.get("name"),
        "total_tracks": len(rows),
        "with_bpm_and_key": len(usable),
        "missing_metadata": [f"{r['artist']} - {r['title']}"
                             for r in rows if not r["have_metadata"]],
        "bpm_range": ([min(r["bpm"] for r in usable), max(r["bpm"] for r in usable)]
                      if usable else None),
        "suggested_order": order,
        "transitions": transitions,
        "rough_transitions": [t for t in transitions
                              if not t["harmonic"] or t["bpm_jump"] > 6],
    })


def cmd_organize(args):
    """Match downloaded audio files on disk to the crate and emit an ordered m3u8."""
    d = Path(args.dir).expanduser()
    if not d.is_dir():
        die(f"Not a directory: {d}")
    exts = {".wav", ".aiff", ".aif", ".flac", ".mp3", ".m4a"}
    files = [p for p in d.rglob("*") if p.suffix.lower() in exts]
    crate = load_crate(args.crate)

    matched, unmatched_tracks = [], []
    used = set()
    for t in crate["tracks"]:
        bp = t.get("beatport") or {}
        want = _fold(f"{bp.get('artist') or t.get('artist')} "
                     f"{bp.get('title') or t.get('title')}")
        best, best_s = None, 0.0
        for f in files:
            if f in used:
                continue
            s = difflib.SequenceMatcher(None, want, _fold(f.stem)).ratio()
            if s > best_s:
                best, best_s = f, s
        if best and best_s >= args.min_score:
            used.add(best)
            matched.append({"track": f"{bp.get('artist') or t.get('artist')} - "
                                     f"{bp.get('title') or t.get('title')}",
                            "file": str(best), "score": round(best_s, 3),
                            "bpm": bp.get("bpm"), "camelot": bp.get("camelot")})
        else:
            unmatched_tracks.append(f"{bp.get('artist') or t.get('artist')} - "
                                    f"{bp.get('title') or t.get('title')}")

    # Playlist goes out in harmonic set order, not crate order - that is what you want
    # when you drag it into Ableton.
    ordered = harmonic_order(matched)
    ordered += [m for m in matched if m not in ordered]

    m3u = None
    if matched and args.m3u:
        m3u = d / f"{crate.get('name', 'crate')}.m3u8"
        lines = ["#EXTM3U"]
        for m in ordered:
            lines.append(f"#EXTINF:-1,{m['track']}  [{m.get('bpm')} BPM {m.get('camelot')}]")
            lines.append(m["file"])
        m3u.write_text("\n".join(lines) + "\n")

    out({"dir": str(d), "audio_files_found": len(files),
         "matched": ordered, "matched_count": len(matched),
         "playlist_order": [m["track"] for m in ordered],
         "crate_tracks_without_a_file": unmatched_tracks,
         "unused_files": [str(f) for f in files if f not in used],
         "m3u8": str(m3u) if m3u else None})


def cmd_camelot(args):
    code = to_camelot(args.key)
    out({"key": args.key, "camelot": code, "compatible": camelot_neighbors(code)})


def main():
    p = argparse.ArgumentParser(description="Beatport Skill")
    subs = p.add_subparsers(dest="command")

    s = subs.add_parser("setup")
    s.add_argument("--token"); s.add_argument("--client-id")
    s.add_argument("--redirect-uri"); s.add_argument("--port", type=int, default=8898)
    s.set_defaults(func=cmd_setup)

    subs.add_parser("login").set_defaults(func=lambda a: (do_login(), cmd_auth_status(a)))
    subs.add_parser("auth-status").set_defaults(func=cmd_auth_status)
    subs.add_parser("probe").set_defaults(func=cmd_probe)

    s = subs.add_parser("spec"); s.add_argument("--grep"); s.set_defaults(func=cmd_spec)

    s = subs.add_parser("get"); s.add_argument("path")
    s.add_argument("--param", action="append"); s.set_defaults(func=cmd_get)

    s = subs.add_parser("search"); s.add_argument("query")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--type", default="tracks"); s.set_defaults(func=cmd_search)

    s = subs.add_parser("track"); s.add_argument("track_id"); s.set_defaults(func=cmd_track)

    for name, fn in (("library", cmd_library), ("purchases", cmd_purchases),
                     ("downloads", cmd_downloads)):
        s = subs.add_parser(name)
        s.add_argument("--limit", type=int, default=100)
        s.add_argument("--all", action="store_true")
        s.set_defaults(func=fn)

    s = subs.add_parser("match"); s.add_argument("crate")
    s.add_argument("--out"); s.add_argument("--min-score", type=float, default=0.72)
    s.add_argument("--delay", type=float, default=0.25)
    s.add_argument("--refresh", action="store_true"); s.set_defaults(func=cmd_match)

    s = subs.add_parser("plan"); s.add_argument("crate"); s.set_defaults(func=cmd_plan)

    s = subs.add_parser("report"); s.add_argument("crate")
    s.add_argument("--target-bpm", type=float)
    s.add_argument("--bpm-tolerance", type=float, default=8)
    s.set_defaults(func=cmd_report)

    s = subs.add_parser("organize"); s.add_argument("crate")
    s.add_argument("--dir", required=True)
    s.add_argument("--min-score", type=float, default=0.55)
    s.add_argument("--m3u", action="store_true", default=True)
    s.set_defaults(func=cmd_organize)

    s = subs.add_parser("camelot"); s.add_argument("key"); s.set_defaults(func=cmd_camelot)

    args = p.parse_args()
    if not args.command:
        p.print_help(); sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
