#!/usr/bin/env python3
"""Mercury skill — Python stdlib only.

Wraps the Mercury Bank API (https://api.mercury.com/api/v1).
Auth: Bearer token from ~/.claude/skills/mercury-skill/config.json
      {"api_token": "secret-token:mercury_production_..."}
Generate a READ-ONLY token in the Mercury dashboard -> Settings -> Tokens
(scope it read-only; it cannot move money).

All success output is JSON on stdout. Errors -> JSON on stderr, non-zero exit.

Commands:
  accounts                       list accounts + balances + total cash
  summary                        total available/current cash across all accounts
  transactions ACCOUNT           list transactions for an account in a date range
  burn                           inflow vs outflow (net burn) over a period, by counterparty
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
API_ROOT = "https://api.mercury.com/api/v1"

# statuses that represent money that actually moved / will move (exclude noise)
REALIZED = {"sent", "posted", "completed"}
DEAD = {"cancelled", "canceled", "failed"}


def die(msg, status=1, **extra):
    blob = {"error": msg}
    blob.update(extra)
    print(json.dumps(blob, indent=2), file=sys.stderr)
    sys.exit(status)


def load_config():
    if not os.path.exists(CONFIG_PATH):
        die(
            f"Missing {CONFIG_PATH}. Create it with a read-only Mercury token:\n"
            f"  echo '{{\"api_token\": \"secret-token:...\"}}' > {CONFIG_PATH}"
        )
    with open(CONFIG_PATH) as f:
        return json.load(f)


def api_get(path, params=None):
    cfg = load_config()
    token = cfg.get("api_token") or cfg.get("api_key")
    if not token:
        die("api_token missing in config.json")
    url = f"{API_ROOT}{path}"
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            url += "?" + urllib.parse.urlencode(clean, doseq=True)
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        die(f"HTTP {e.code} on {path}", status_code=e.code, body=body[:1200])
    except urllib.error.URLError as e:
        die(f"Network error on {path}: {e.reason}")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def get_accounts():
    data = api_get("/accounts")
    if isinstance(data, list):
        return data
    return data.get("accounts", [])


def resolve_accounts(ref):
    """Return list of account dicts for a ref (id, name-substring, or 'all'/None)."""
    accts = get_accounts()
    if not ref or ref == "all":
        return accts
    for a in accts:
        if a.get("id") == ref:
            return [a]
    low = ref.lower()
    matches = [a for a in accts if low in (a.get("name", "").lower())]
    if len(matches) == 1:
        return matches
    if len(matches) > 1:
        die(f"Ambiguous account '{ref}'", matches=[a.get("name") for a in matches])
    die(f"No account matching '{ref}'", available=[a.get("name") for a in accts])


def fetch_transactions(account_id, start=None, end=None, status=None, cap=None):
    txns, offset, page = [], 0, 500
    while True:
        data = api_get(
            f"/account/{account_id}/transactions",
            {"limit": page, "offset": offset, "start": start, "end": end, "status": status},
        )
        batch = data.get("transactions", []) if isinstance(data, dict) else data
        if not batch:
            break
        txns.extend(batch)
        offset += len(batch)
        total = data.get("total") if isinstance(data, dict) else None
        if (total is not None and offset >= total) or (cap and len(txns) >= cap) or len(batch) < page:
            break
    return txns[:cap] if cap else txns


def money(x):
    try:
        return round(float(x), 2)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_accounts(args):
    accts = get_accounts()
    rows, total_avail, total_current = [], 0.0, 0.0
    for a in accts:
        avail = money(a.get("availableBalance"))
        curr = money(a.get("currentBalance"))
        total_avail += avail
        total_current += curr
        rows.append({
            "id": a.get("id"),
            "name": a.get("name"),
            "type": a.get("type") or a.get("kind"),
            "status": a.get("status"),
            "availableBalance": avail,
            "currentBalance": curr,
        })
    print(json.dumps({
        "accounts": rows,
        "total_available": round(total_avail, 2),
        "total_current": round(total_current, 2),
        "account_count": len(rows),
    }, indent=2))


def cmd_summary(args):
    accts = get_accounts()
    total = round(sum(money(a.get("availableBalance")) for a in accts), 2)
    print(json.dumps({
        "total_cash_available": total,
        "accounts": {a.get("name"): money(a.get("availableBalance")) for a in accts},
    }, indent=2))


def cmd_transactions(args):
    accts = resolve_accounts(args.account)
    out = []
    for a in accts:
        txns = fetch_transactions(a["id"], args.start, args.end, args.status, args.limit)
        for t in txns:
            out.append({
                "account": a.get("name"),
                "postedAt": t.get("postedAt"),
                "createdAt": t.get("createdAt"),
                "amount": money(t.get("amount")),
                "counterparty": t.get("counterpartyName") or t.get("counterpartyNickname"),
                "kind": t.get("kind"),
                "status": t.get("status"),
                "note": t.get("note") or t.get("externalMemo") or t.get("bankDescription"),
            })
    out.sort(key=lambda r: r.get("postedAt") or r.get("createdAt") or "", reverse=True)
    print(json.dumps({"count": len(out), "transactions": out}, indent=2))


def cmd_burn(args):
    accts = resolve_accounts(args.account)
    inflow = outflow = pending_out = 0.0
    by_counterparty = defaultdict(float)
    by_kind = defaultdict(float)
    n = 0
    for a in accts:
        for t in fetch_transactions(a["id"], args.start, args.end):
            status = (t.get("status") or "").lower()
            if status in DEAD:
                continue
            amt = money(t.get("amount"))
            n += 1
            if amt < 0:
                if status in REALIZED or not args.realized_only:
                    outflow += -amt
                    cp = t.get("counterpartyName") or t.get("counterpartyNickname") or "(unknown)"
                    by_counterparty[cp] += -amt
                    by_kind[t.get("kind") or "other"] += -amt
                if status not in REALIZED:
                    pending_out += -amt
            elif amt > 0:
                inflow += amt
    top = sorted(by_counterparty.items(), key=lambda kv: kv[1], reverse=True)[: args.top]
    print(json.dumps({
        "period": {"start": args.start, "end": args.end},
        "accounts": [a.get("name") for a in accts],
        "transaction_count": n,
        "gross_outflow": round(outflow, 2),
        "gross_inflow": round(inflow, 2),
        "net_burn": round(outflow - inflow, 2),
        "pending_outflow_included": round(pending_out, 2),
        "by_kind": {k: round(v, 2) for k, v in sorted(by_kind.items(), key=lambda kv: kv[1], reverse=True)},
        "top_outflows_by_counterparty": [{"counterparty": k, "amount": round(v, 2)} for k, v in top],
    }, indent=2))


def main():
    p = argparse.ArgumentParser(description="Mercury Bank read-only skill")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("accounts", help="list accounts + balances + total cash").set_defaults(fn=cmd_accounts)
    sub.add_parser("summary", help="total cash across accounts").set_defaults(fn=cmd_summary)

    t = sub.add_parser("transactions", help="transactions for an account in a date range")
    t.add_argument("account", nargs="?", default="all", help="account id, name substring, or 'all'")
    t.add_argument("--start", help="YYYY-MM-DD (inclusive)")
    t.add_argument("--end", help="YYYY-MM-DD (inclusive)")
    t.add_argument("--status", help="filter: sent|pending|cancelled|failed")
    t.add_argument("--limit", type=int, help="cap number returned")
    t.set_defaults(fn=cmd_transactions)

    b = sub.add_parser("burn", help="inflow vs outflow (net burn) over a period")
    b.add_argument("--start", required=True, help="YYYY-MM-DD (inclusive)")
    b.add_argument("--end", required=True, help="YYYY-MM-DD (inclusive)")
    b.add_argument("--account", default="all", help="account id/name or 'all' (default)")
    b.add_argument("--top", type=int, default=25, help="top N outflow counterparties")
    b.add_argument("--realized-only", action="store_true", help="count only sent/posted (exclude pending) in outflow")
    b.set_defaults(fn=cmd_burn)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
