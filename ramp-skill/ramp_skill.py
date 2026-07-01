#!/usr/bin/env python3
"""Ramp skill — Python stdlib only.

Wraps the Ramp developer API (https://api.ramp.com/developer/v1).
Auth: OAuth2 client-credentials from ~/.claude/skills/ramp-skill/config.json
      {"client_id": "...", "client_secret": "...",
       "scopes": "transactions:read users:read cards:read reimbursements:read"}
Create an app in Ramp -> Settings -> Developer API (requires admin), copy the
client id/secret, and grant the read scopes. Token is cached in cache.json.

All success output is JSON on stdout. Errors -> JSON on stderr, non-zero exit.

Commands:
  transactions       list card transactions in a date range
  spend-summary      total card spend over a period, by category / merchant / user
  users              list users
  cards              list cards
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
CACHE_PATH = os.path.join(SCRIPT_DIR, "cache.json")
API_ROOT = "https://api.ramp.com/developer/v1"
TOKEN_URL = "https://api.ramp.com/developer/v1/token"
DEFAULT_SCOPES = "transactions:read users:read cards:read reimbursements:read"
COUNTS = {"CLEARED", "COMPLETED", "PENDING"}   # states that represent real spend
DEAD = {"DECLINED", "ERROR", "CANCELED", "CANCELLED"}


def die(msg, status=1, **extra):
    blob = {"error": msg}
    blob.update(extra)
    print(json.dumps(blob, indent=2), file=sys.stderr)
    sys.exit(status)


def load_config():
    if not os.path.exists(CONFIG_PATH):
        die(
            f"Missing {CONFIG_PATH}. Create it from a Ramp developer app:\n"
            f'  echo \'{{"client_id":"...","client_secret":"...","scopes":"{DEFAULT_SCOPES}"}}\' '
            f"> {CONFIG_PATH}"
        )
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_cache():
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_cache(d):
    with open(CACHE_PATH, "w") as f:
        json.dump(d, f)


def get_token():
    cfg = load_config()
    cid, csec = cfg.get("client_id"), cfg.get("client_secret")
    if not cid or not csec:
        die("client_id / client_secret missing in config.json")
    cache = load_cache()
    if cache.get("access_token") and cache.get("expires_at", 0) > time.time() + 60:
        return cache["access_token"]
    scopes = cfg.get("scopes", DEFAULT_SCOPES)
    body = urllib.parse.urlencode({"grant_type": "client_credentials", "scope": scopes}).encode()
    basic = base64.b64encode(f"{cid}:{csec}".encode()).decode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            tok = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        die(f"Token HTTP {e.code}", status_code=e.code, body=e.read().decode(errors="replace")[:1200])
    except urllib.error.URLError as e:
        die(f"Network error getting token: {e.reason}")
    access = tok.get("access_token")
    if not access:
        die("No access_token in token response", response=tok)
    save_cache({"access_token": access, "expires_at": time.time() + int(tok.get("expires_in", 3600))})
    return access


def api_get(path, params=None):
    token = get_token()
    url = f"{API_ROOT}{path}"
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            url += "?" + urllib.parse.urlencode(clean, doseq=True)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        die(f"HTTP {e.code} on {path}", status_code=e.code, body=e.read().decode(errors="replace")[:1200])
    except urllib.error.URLError as e:
        die(f"Network error on {path}: {e.reason}")


def fetch_paginated(path, params=None, cap=None):
    items, cursor = [], None
    base = dict(params or {})
    while True:
        p = dict(base)
        if cursor:
            p["start"] = cursor
        data = api_get(path, p)
        items.extend(data.get("data", []))
        nxt = (data.get("page") or {}).get("next")
        if not nxt or (cap and len(items) >= cap):
            break
        q = urllib.parse.parse_qs(urllib.parse.urlparse(nxt).query)
        cursor = q.get("start", [None])[0]
        if not cursor:
            break
    return items[:cap] if cap else items


def _rfc3339(d, end=False):
    if not d:
        return None
    if "T" in d:
        return d
    return f"{d}T23:59:59Z" if end else f"{d}T00:00:00Z"


def money(x):
    try:
        return round(float(x), 2)
    except (TypeError, ValueError):
        return 0.0


def holder_name(t):
    ch = t.get("card_holder") or {}
    name = " ".join(x for x in [ch.get("first_name"), ch.get("last_name")] if x).strip()
    return name or t.get("user_id") or "(unknown)"


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_transactions(args):
    txns = fetch_paginated(
        "/transactions",
        {"from_date": _rfc3339(args.start), "to_date": _rfc3339(args.end, end=True), "page_size": 100},
        cap=args.limit,
    )
    out = []
    for t in txns:
        out.append({
            "date": t.get("user_transaction_time"),
            "amount": money(t.get("amount")),
            "merchant": t.get("merchant_name"),
            "category": t.get("sk_category_name"),
            "user": holder_name(t),
            "state": t.get("state"),
            "memo": t.get("memo"),
        })
    out.sort(key=lambda r: r.get("date") or "", reverse=True)
    print(json.dumps({"count": len(out), "transactions": out}, indent=2))


def cmd_spend_summary(args):
    txns = fetch_paginated(
        "/transactions",
        {"from_date": _rfc3339(args.start), "to_date": _rfc3339(args.end, end=True), "page_size": 100},
    )
    total = pending = 0.0
    by_cat, by_merch, by_user = defaultdict(float), defaultdict(float), defaultdict(float)
    counted = 0
    for t in txns:
        state = (t.get("state") or "").upper()
        if state in DEAD:
            continue
        amt = money(t.get("amount"))
        if amt <= 0:
            continue
        counted += 1
        total += amt
        if state == "PENDING":
            pending += amt
        by_cat[t.get("sk_category_name") or "(uncategorized)"] += amt
        by_merch[t.get("merchant_name") or "(unknown)"] += amt
        by_user[holder_name(t)] += amt

    def top(d, n):
        return [{"name": k, "amount": round(v, 2)} for k, v in sorted(d.items(), key=lambda kv: kv[1], reverse=True)[:n]]

    print(json.dumps({
        "period": {"start": args.start, "end": args.end},
        "transaction_count": counted,
        "total_spend": round(total, 2),
        "pending_included": round(pending, 2),
        "by_category": top(by_cat, args.top),
        "by_merchant": top(by_merch, args.top),
        "by_user": top(by_user, args.top),
        "note": "Card spend here is the DETAIL behind the single 'Ramp' debit in Mercury burn — do not add the two totals together (double-count).",
    }, indent=2))


def cmd_users(args):
    users = fetch_paginated("/users", {"page_size": 100})
    print(json.dumps({"count": len(users), "users": [
        {"id": u.get("id"), "name": " ".join(x for x in [u.get("first_name"), u.get("last_name")] if x),
         "email": u.get("email"), "role": u.get("role"), "status": u.get("status")} for u in users]}, indent=2))


def cmd_cards(args):
    cards = fetch_paginated("/cards", {"page_size": 100})
    print(json.dumps({"count": len(cards), "cards": [
        {"id": c.get("id"), "display_name": c.get("display_name"), "last_four": c.get("last_four"),
         "user": c.get("cardholder_name"), "state": c.get("state")} for c in cards]}, indent=2))


def main():
    p = argparse.ArgumentParser(description="Ramp read-only spend skill")
    sub = p.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("transactions", help="card transactions in a date range")
    t.add_argument("--start", help="YYYY-MM-DD (inclusive)")
    t.add_argument("--end", help="YYYY-MM-DD (inclusive)")
    t.add_argument("--limit", type=int, help="cap number returned")
    t.set_defaults(fn=cmd_transactions)

    s = sub.add_parser("spend-summary", help="total card spend by category/merchant/user")
    s.add_argument("--start", required=True, help="YYYY-MM-DD (inclusive)")
    s.add_argument("--end", required=True, help="YYYY-MM-DD (inclusive)")
    s.add_argument("--top", type=int, default=20, help="top N per breakdown")
    s.set_defaults(fn=cmd_spend_summary)

    sub.add_parser("users", help="list users").set_defaults(fn=cmd_users)
    sub.add_parser("cards", help="list cards").set_defaults(fn=cmd_cards)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
