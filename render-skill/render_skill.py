#!/usr/bin/env python3
"""Render skill — Python stdlib only.

Subcommands wrap the Render REST API (https://api.render.com/v1).
Auth: Bearer token from ~/.claude/skills/render-skill/config.json {"api_key": "rnd_..."}

All output is JSON-on-stdout. Errors exit non-zero with an {error,status,body} blob.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
CACHE_PATH = os.path.join(SCRIPT_DIR, "cache.json")
API_ROOT = "https://api.render.com/v1"

# Render service types accepted by the /services filter.
SERVICE_TYPES = {"web_service", "private_service", "background_worker", "cron_job", "static_site"}


# ---------------------------------------------------------------------------
# Config + cache
# ---------------------------------------------------------------------------

def load_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        die(
            f"Missing {CONFIG_PATH}. Create it with: "
            f'echo \'{{"api_key": "rnd_YOUR_KEY"}}\' > {CONFIG_PATH}',
            status=1,
        )
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def load_cache() -> dict:
    if not os.path.exists(CACHE_PATH):
        return {"services": {}, "databases": {}, "owner_id": None, "fetched_at": 0}
    try:
        with open(CACHE_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {"services": {}, "databases": {}, "owner_id": None, "fetched_at": 0}


def save_cache(cache: dict) -> None:
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f, indent=2)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def api_request(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    body: Any = None,
    accept: str = "application/json",
) -> Any:
    config = load_config()
    api_key = config.get("api_key")
    if not api_key:
        die("api_key missing in config.json")

    url = f"{API_ROOT}{path}"
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            url = f"{url}?{urllib.parse.urlencode(clean, doseq=True)}"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": accept,
    }
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(url, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            if not raw:
                return None
            if accept == "application/json":
                return json.loads(raw)
            return raw.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        die(
            json.dumps({"error": "render_api_error", "status": e.code, "url": url, "body": body_text}),
            status=2,
            raw=True,
        )
    except urllib.error.URLError as e:
        die(json.dumps({"error": "render_network_error", "url": url, "detail": str(e)}), status=2, raw=True)


def paginated_get(path: str, *, params: dict | None = None, page_size: int = 100, max_pages: int = 20) -> list:
    """Walk Render's cursor-pagination, returning a flat list of `.<entity>` rows.

    Render wraps each entity in `{"<entity>": {...}, "cursor": "..."}`. We surface the inner
    entity directly.
    """
    base_params = dict(params or {})
    base_params.setdefault("limit", page_size)
    all_rows: list = []
    cursor = None
    for _ in range(max_pages):
        p = dict(base_params)
        if cursor:
            p["cursor"] = cursor
        page = api_request("GET", path, params=p)
        if not isinstance(page, list):
            return all_rows
        if not page:
            break
        last_cursor = None
        for entry in page:
            if isinstance(entry, dict):
                if "cursor" in entry:
                    last_cursor = entry["cursor"]
                inner = next((v for k, v in entry.items() if k != "cursor"), None)
                if inner is not None:
                    all_rows.append(inner)
        if not last_cursor or len(page) < page_size:
            break
        cursor = last_cursor
    return all_rows


# ---------------------------------------------------------------------------
# Resolvers
# ---------------------------------------------------------------------------

def refresh_service_cache(cache: dict) -> dict:
    services = paginated_get("/services")
    cache["services"] = {s["id"]: {"id": s["id"], "name": s.get("name", ""), "type": s.get("type", ""), "suspended": s.get("suspended")} for s in services if isinstance(s, dict) and s.get("id")}
    cache["fetched_at"] = int(time.time())
    save_cache(cache)
    return cache


def refresh_database_cache(cache: dict) -> dict:
    rows = paginated_get("/postgres")
    cache["databases"] = {r["id"]: {"id": r["id"], "name": r.get("name", ""), "database_name": r.get("databaseName", ""), "plan": r.get("plan")} for r in rows if isinstance(r, dict) and r.get("id")}
    cache["fetched_at"] = int(time.time())
    save_cache(cache)
    return cache


def resolve_service_id(name_or_id: str) -> str:
    if re.match(r"^srv-[a-z0-9]+$", name_or_id):
        return name_or_id
    cache = load_cache()
    if not cache.get("services"):
        refresh_service_cache(cache)
    # exact name match first
    for sid, s in cache["services"].items():
        if s.get("name") == name_or_id:
            return sid
    # substring fallback
    candidates = [sid for sid, s in cache["services"].items() if name_or_id.lower() in s.get("name", "").lower()]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        names = [cache["services"][c].get("name") for c in candidates]
        die(json.dumps({"error": "ambiguous_service", "query": name_or_id, "matches": names}), status=3, raw=True)
    # cache may be stale — try refresh once
    refresh_service_cache(cache)
    for sid, s in cache["services"].items():
        if s.get("name") == name_or_id:
            return sid
    die(json.dumps({"error": "service_not_found", "query": name_or_id}), status=3, raw=True)


def resolve_database_id(name_or_id: str) -> str:
    if re.match(r"^dpg-[a-z0-9]+$", name_or_id):
        return name_or_id
    cache = load_cache()
    if not cache.get("databases"):
        refresh_database_cache(cache)
    for did, d in cache["databases"].items():
        if d.get("name") == name_or_id or d.get("database_name") == name_or_id:
            return did
    candidates = [did for did, d in cache["databases"].items() if name_or_id.lower() in (d.get("name", "") + " " + d.get("database_name", "")).lower()]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        names = [cache["databases"][c].get("name") for c in candidates]
        die(json.dumps({"error": "ambiguous_database", "query": name_or_id, "matches": names}), status=3, raw=True)
    refresh_database_cache(cache)
    for did, d in cache["databases"].items():
        if d.get("name") == name_or_id or d.get("database_name") == name_or_id:
            return did
    die(json.dumps({"error": "database_not_found", "query": name_or_id}), status=3, raw=True)


# ---------------------------------------------------------------------------
# Commands — services
# ---------------------------------------------------------------------------

def cmd_services(args) -> None:
    params: dict = {}
    if args.type:
        params["type"] = _normalize_service_type(args.type)
    if args.name:
        params["name"] = args.name
    rows = paginated_get("/services", params=params, page_size=args.limit or 100, max_pages=1 if args.limit else 20)
    if args.limit:
        rows = rows[: args.limit]
    cache = load_cache()
    cache["services"] = {**(cache.get("services") or {}), **{r["id"]: {"id": r["id"], "name": r.get("name", ""), "type": r.get("type", ""), "suspended": r.get("suspended")} for r in rows if r.get("id")}}
    save_cache(cache)
    print(json.dumps([_summarize_service(r) for r in rows], indent=2))


def cmd_service(args) -> None:
    sid = resolve_service_id(args.target)
    row = api_request("GET", f"/services/{sid}")
    print(json.dumps(row, indent=2))


def cmd_service_env(args) -> None:
    sid = resolve_service_id(args.target)
    rows = paginated_get(f"/services/{sid}/env-vars")
    flat = [{"key": e.get("key"), "value": e.get("value")} for e in rows if isinstance(e, dict)]
    if args.key:
        match = next((e for e in flat if e["key"] == args.key), None)
        if match is None:
            die(json.dumps({"error": "env_var_not_found", "service": sid, "key": args.key}), status=3, raw=True)
        print(json.dumps(match, indent=2))
        return
    print(json.dumps(flat, indent=2))


def cmd_service_env_set(args) -> None:
    sid = resolve_service_id(args.target)
    rows = paginated_get(f"/services/{sid}/env-vars")
    current = [{"key": e.get("key"), "value": e.get("value")} for e in rows if isinstance(e, dict)]
    seen = False
    for entry in current:
        if entry["key"] == args.key:
            entry["value"] = args.value
            seen = True
            break
    if not seen:
        current.append({"key": args.key, "value": args.value})
    api_request("PUT", f"/services/{sid}/env-vars", body=current)
    result: dict = {"service": sid, "key": args.key, "set_at": int(time.time())}
    if not args.no_deploy:
        deploy = api_request("POST", f"/services/{sid}/deploys", body={"clearCache": "do_not_clear"})
        result["deploy"] = deploy
    print(json.dumps(result, indent=2))


def cmd_deploys(args) -> None:
    sid = resolve_service_id(args.target)
    rows = paginated_get(f"/services/{sid}/deploys", page_size=args.limit or 20, max_pages=1)
    rows = rows[: args.limit or 20]
    print(json.dumps([_summarize_deploy(r) for r in rows], indent=2))


def cmd_deploy(args) -> None:
    sid = resolve_service_id(args.target)
    body: dict = {"clearCache": "clear" if args.clear_cache else "do_not_clear"}
    if args.commit:
        body["commitId"] = args.commit
    result = api_request("POST", f"/services/{sid}/deploys", body=body)
    print(json.dumps(result, indent=2))


def cmd_logs(args) -> None:
    sid = resolve_service_id(args.target)
    params: dict = {
        "ownerId": _ensure_owner_id(),
        "resource": sid,
        "limit": args.limit or 200,
        "direction": "backward",
    }
    if args.since:
        params["startTime"] = _resolve_since(args.since)
    result = api_request("GET", "/logs", params=params)
    print(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# Commands — postgres
# ---------------------------------------------------------------------------

def cmd_databases(args) -> None:
    rows = paginated_get("/postgres")
    if args.name:
        rows = [r for r in rows if args.name.lower() in (r.get("name", "") + " " + r.get("databaseName", "")).lower()]
    cache = load_cache()
    cache["databases"] = {**(cache.get("databases") or {}), **{r["id"]: {"id": r["id"], "name": r.get("name", ""), "database_name": r.get("databaseName", ""), "plan": r.get("plan")} for r in rows if r.get("id")}}
    save_cache(cache)
    print(json.dumps([_summarize_database(r) for r in rows], indent=2))


def cmd_database(args) -> None:
    did = resolve_database_id(args.target)
    row = api_request("GET", f"/postgres/{did}")
    print(json.dumps(row, indent=2))


def cmd_database_url(args) -> None:
    did = resolve_database_id(args.target)
    info = api_request("GET", f"/postgres/{did}/connection-info")
    if not isinstance(info, dict):
        die(json.dumps({"error": "unexpected_connection_info", "received": info}), status=3, raw=True)
    if args.internal:
        result = {"connection_string": info.get("internalConnectionString")}
    elif args.external:
        result = {"connection_string": info.get("externalConnectionString")}
    else:
        # Default to external — that's what laptops need.
        result = {"connection_string": info.get("externalConnectionString")}
    result["psql_command"] = info.get("psqlCommand")
    result["database"] = did
    print(json.dumps(result, indent=2))


def cmd_psql(args) -> None:
    did = resolve_database_id(args.target)
    info = api_request("GET", f"/postgres/{did}/connection-info")
    if not isinstance(info, dict) or not info.get("externalConnectionString"):
        die(json.dumps({"error": "no_external_connection_string", "database": did}), status=3, raw=True)
    conn = info["externalConnectionString"]
    # exec psql in place
    os.execvp("psql", ["psql", conn])


def cmd_exports(args) -> None:
    sid = resolve_service_id(args.target)
    rows = paginated_get(f"/services/{sid}/env-vars")
    lines = []
    for e in rows:
        if not isinstance(e, dict):
            continue
        key = e.get("key")
        value = e.get("value")
        if not key or value is None:
            continue
        escaped = str(value).replace("'", "'\\''")
        lines.append(f"export {key}='{escaped}'")
    print("\n".join(lines))


def cmd_exports_db(args) -> None:
    did = resolve_database_id(args.target)
    info = api_request("GET", f"/postgres/{did}/connection-info")
    if not isinstance(info, dict):
        die(json.dumps({"error": "unexpected_connection_info", "received": info}), status=3, raw=True)
    conn = info.get("externalConnectionString")
    if not conn:
        die(json.dumps({"error": "no_external_connection_string", "database": did}), status=3, raw=True)
    escaped = conn.replace("'", "'\\''")
    print(f"export DATABASE_URL='{escaped}'")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _summarize_service(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "type": row.get("type"),
        "suspended": row.get("suspended"),
        "serviceDetails": {
            "url": (row.get("serviceDetails") or {}).get("url"),
            "region": (row.get("serviceDetails") or {}).get("region"),
            "plan": (row.get("serviceDetails") or {}).get("plan"),
            "env": (row.get("serviceDetails") or {}).get("env"),
        },
        "updatedAt": row.get("updatedAt"),
    }


def _summarize_database(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "name": row.get("name"),
        "databaseName": row.get("databaseName"),
        "user": row.get("databaseUser"),
        "plan": row.get("plan"),
        "region": row.get("region"),
        "version": row.get("version"),
        "status": row.get("status"),
        "updatedAt": row.get("updatedAt"),
    }


def _summarize_deploy(row: dict) -> dict:
    commit = row.get("commit") or {}
    return {
        "id": row.get("id"),
        "status": row.get("status"),
        "trigger": row.get("trigger"),
        "createdAt": row.get("createdAt"),
        "finishedAt": row.get("finishedAt"),
        "commit": {
            "id": commit.get("id"),
            "message": commit.get("message"),
        },
    }


def _normalize_service_type(value: str) -> str:
    aliases = {
        "web": "web_service",
        "private": "private_service",
        "worker": "background_worker",
        "background": "background_worker",
        "static": "static_site",
        "cron": "cron_job",
    }
    canonical = aliases.get(value, value)
    if canonical not in SERVICE_TYPES:
        die(json.dumps({"error": "unknown_service_type", "value": value, "allowed": sorted(SERVICE_TYPES) + sorted(aliases.keys())}), status=1, raw=True)
    return canonical


def _resolve_since(spec: str) -> str:
    """Accepts '10m', '2h', '1d', or an ISO8601 timestamp."""
    m = re.match(r"^(\d+)([smhd])$", spec)
    if not m:
        return spec  # assume caller passed an ISO timestamp
    n, unit = int(m.group(1)), m.group(2)
    seconds = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit] * n
    ts = time.gmtime(time.time() - seconds)
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", ts)


def _ensure_owner_id() -> str:
    cache = load_cache()
    if cache.get("owner_id"):
        return cache["owner_id"]
    owners = api_request("GET", "/owners")
    if isinstance(owners, list):
        for entry in owners:
            owner = entry.get("owner") if isinstance(entry, dict) else None
            if isinstance(owner, dict) and owner.get("id"):
                cache["owner_id"] = owner["id"]
                save_cache(cache)
                return cache["owner_id"]
    die(json.dumps({"error": "no_owner_found"}), status=3, raw=True)
    return ""  # unreachable


def die(message: str, *, status: int = 1, raw: bool = False) -> None:
    if raw:
        print(message, file=sys.stderr)
    else:
        print(message, file=sys.stderr)
    sys.exit(status)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render skill — services, postgres, deploys, env vars, logs.")
    sub = parser.add_subparsers(dest="command")

    p_services = sub.add_parser("services", help="List services")
    p_services.add_argument("--type", help="web|worker|static|cron|background|private (or full Render names)")
    p_services.add_argument("--name", help="Filter by name substring")
    p_services.add_argument("--limit", type=int, help="Cap rows returned")
    p_services.set_defaults(func=cmd_services)

    p_service = sub.add_parser("service", help="Get one service")
    p_service.add_argument("target", help="Name or service id (srv-...)")
    p_service.set_defaults(func=cmd_service)

    p_env = sub.add_parser("service-env", help="List env vars for a service")
    p_env.add_argument("target")
    p_env.add_argument("--key", help="Filter to a single key")
    p_env.set_defaults(func=cmd_service_env)

    p_env_set = sub.add_parser("service-env-set", help="Set an env var on a service")
    p_env_set.add_argument("target")
    p_env_set.add_argument("key")
    p_env_set.add_argument("value")
    p_env_set.add_argument("--no-deploy", action="store_true", help="Skip triggering a deploy after the change")
    p_env_set.set_defaults(func=cmd_service_env_set)

    p_deploys = sub.add_parser("deploys", help="List recent deploys for a service")
    p_deploys.add_argument("target")
    p_deploys.add_argument("--limit", type=int, default=20)
    p_deploys.set_defaults(func=cmd_deploys)

    p_deploy = sub.add_parser("deploy", help="Trigger a deploy on a service")
    p_deploy.add_argument("target")
    p_deploy.add_argument("--clear-cache", action="store_true")
    p_deploy.add_argument("--commit", help="Specific git commit SHA")
    p_deploy.set_defaults(func=cmd_deploy)

    p_logs = sub.add_parser("logs", help="Recent logs for a service")
    p_logs.add_argument("target")
    p_logs.add_argument("--limit", type=int, default=200)
    p_logs.add_argument("--since", help="Window like 10m, 2h, 1d, or ISO8601 timestamp")
    p_logs.set_defaults(func=cmd_logs)

    p_dbs = sub.add_parser("databases", help="List Postgres databases")
    p_dbs.add_argument("--name", help="Filter by name substring")
    p_dbs.set_defaults(func=cmd_databases)

    p_db = sub.add_parser("database", help="Get one Postgres database")
    p_db.add_argument("target", help="Name or db id (dpg-...)")
    p_db.set_defaults(func=cmd_database)

    p_dburl = sub.add_parser("database-url", help="Get a Postgres connection string")
    p_dburl.add_argument("target")
    group = p_dburl.add_mutually_exclusive_group()
    group.add_argument("--internal", action="store_true")
    group.add_argument("--external", action="store_true")
    p_dburl.set_defaults(func=cmd_database_url)

    p_psql = sub.add_parser("psql", help="Open a psql shell against a Render Postgres")
    p_psql.add_argument("target")
    p_psql.set_defaults(func=cmd_psql)

    p_exp = sub.add_parser("exports", help="Print export statements for all service env vars")
    p_exp.add_argument("target")
    p_exp.set_defaults(func=cmd_exports)

    p_exp_db = sub.add_parser("exports-db", help="Print export DATABASE_URL for a database")
    p_exp_db.add_argument("target")
    p_exp_db.set_defaults(func=cmd_exports_db)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not getattr(args, "command", None):
        parser.print_help()
        sys.exit(0)
    args.func(args)


if __name__ == "__main__":
    main()
