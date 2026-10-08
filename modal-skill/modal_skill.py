#!/usr/bin/env python3
"""
Modal Skill: cost visibility and control for the Modal workspace.

Read commands (safe):
  summary  [--for "this month"|"last month"|YYYY-MM]   billed/metered + month-end projection
  burn     [--days N]                                   daily spend, average, projection
  top      [--days N] [--by app|resource] [--limit N]   top spenders
  today                                                 hourly spend today (local time) + run rate
  active                                                apps with running containers right now
  idle     [--days N]                                   warm functions with runners but no work
  app      NAME [--days N]                              one app: functions, live stats, cost
  report   [--start D] [--end D] [-r d|h] [--csv]       raw billing report passthrough

Write commands (dry run unless --yes):
  scale    APP FUNCTION --min N [--max N] [--buffer N] [--scaledown-window S] [--yes]
  stop     APP [--yes]

Billing and listing use the `modal` CLI. Function-level commands (idle, app, scale)
use the Modal SDK, run under the same Python interpreter as the CLI.
"""

import argparse
import calendar
import collections
import datetime as dt
import json
import os
import shutil
import subprocess
import sys

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SKILL_DIR, "config.json")


# ---------- helpers ----------

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def modal_bin():
    b = shutil.which("modal")
    if not b:
        sys.exit("modal CLI not found. Install it (brew install modal or pip install modal) and run `modal token new`.")
    return b


def sdk_python():
    """The interpreter the modal CLI runs under, so SDK calls match the CLI version."""
    try:
        with open(modal_bin()) as f:
            first = f.readline().strip()
        if first.startswith("#!") and "python" in first:
            return first[2:].strip()
    except Exception:
        pass
    return sys.executable


def run_cli(args, timeout=300):
    r = subprocess.run([modal_bin()] + args, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout).strip()
        sys.exit(f"modal {' '.join(args)} failed:\n{msg[-1500:]}")
    return r.stdout


def cli_json(args, timeout=300):
    out = run_cli(args + ["--json"], timeout=timeout)
    return json.loads(out) if out.strip() else []


def run_sdk(code, timeout=600):
    """Run a snippet under the CLI's interpreter; it must print one JSON document."""
    r = subprocess.run([sdk_python(), "-c", code], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        sys.exit(f"Modal SDK call failed:\n{r.stderr[-1500:]}")
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    return json.loads(lines[-1]) if lines else None


def money(x):
    return f"${x:,.2f}"


def billing_rows(start, end, resolution="d", resources=True, tz=None):
    """Billing report rows. Daily reports are limited to 31 days per call, so chunk."""
    rows = []
    s = dt.date.fromisoformat(start)
    e = dt.date.fromisoformat(end)
    step = 31 if resolution == "d" else 7
    while s < e:
        chunk_end = min(e, s + dt.timedelta(days=step))
        args = ["billing", "report", "--start", s.isoformat(), "--end", chunk_end.isoformat(), "-r", resolution]
        if resources:
            args.append("--show-resources")
        if tz:
            args += ["--tz", tz]
        rows += cli_json(args, timeout=600)
        s = chunk_end
    return rows


def window(days):
    end = dt.date.today() + dt.timedelta(days=1)  # end is exclusive; include today
    start = end - dt.timedelta(days=days)
    return start.isoformat(), end.isoformat()


def table(rows, headers):
    widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) if rows else len(str(h)) for i, h in enumerate(headers)]
    line = "  ".join(str(h).ljust(w) for h, w in zip(headers, widths))
    print(line)
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(str(c).ljust(w) for c, w in zip(r, widths)))


def emit(data, as_json, render):
    if as_json:
        print(json.dumps(data, indent=2, default=str))
    else:
        render(data)


# ---------- read commands ----------

def cmd_summary(a):
    period = a.period or "this month"
    data = cli_json(["billing", "summary", "--for", period])
    out = {"period": period, **data}
    if period == "this month":
        today = dt.date.today()
        days_in = calendar.monthrange(today.year, today.month)[1]
        elapsed = today.day - 1 + dt.datetime.now().hour / 24 or 1
        metered = float(data.get("metered_cost", 0))
        out["projected_month_metered"] = round(metered / elapsed * days_in, 2)
    budget = load_config().get("monthly_budget")
    if budget:
        out["monthly_budget"] = budget

    def render(d):
        print(f"Modal billing, {d['period']}")
        print(f"  billed  {money(float(d.get('billed_cost', 0)))}")
        print(f"  metered {money(float(d.get('metered_cost', 0)))}")
        for k, v in (d.get("metered_cost_breakdown") or {}).items():
            print(f"    {k:16} {money(float(v))}")
        if "projected_month_metered" in d:
            print(f"  projected month (metered, at current pace): {money(d['projected_month_metered'])}")
        if d.get("monthly_budget"):
            print(f"  budget {money(d['monthly_budget'])}")
    emit(out, a.json, render)


def cmd_burn(a):
    start, end = window(a.days)
    rows = billing_rows(start, end, "d", resources=False)
    day = collections.defaultdict(float)
    for r in rows:
        day[r["interval_start"][:10]] += float(r["cost"])
    days = sorted(day)
    full = [day[d] for d in days[:-1]] or [day[d] for d in days]
    last7 = full[-7:]
    avg7 = sum(last7) / len(last7) if last7 else 0
    out = {"daily": {d: round(day[d], 2) for d in days}, "avg_last7_full_days": round(avg7, 2),
           "projected_30d_at_avg7": round(avg7 * 30, 2)}

    def render(d):
        peak = max(d["daily"].values() or [1])
        for k, v in d["daily"].items():
            bar = "#" * int(40 * v / peak) if peak else ""
            print(f"  {k}  {money(v):>11}  {bar}")
        print(f"7-day average (full days): {money(d['avg_last7_full_days'])}/day  ->  ~{money(d['projected_30d_at_avg7'])} per 30 days")
    emit(out, a.json, render)


def cmd_top(a):
    start, end = window(a.days)
    rows = billing_rows(start, end, "d", resources=True)
    key = "description" if a.by == "app" else "resource"
    tot = collections.defaultdict(float)
    mix = collections.defaultdict(lambda: collections.defaultdict(float))
    first = {}
    for r in rows:
        k = (r.get(key) or r.get("object_id")) if key == "description" else r["resource"]
        c = float(r["cost"])
        tot[k] += c
        mix[k][r["resource"] if key == "description" else (r.get("description") or "")] += c
        first[k] = min(first.get(k, r["interval_start"][:10]), r["interval_start"][:10])
    ranked = sorted(tot.items(), key=lambda kv: -kv[1])[: a.limit]
    grand = sum(tot.values())
    out = [{"name": k, "cost": round(v, 2), "share": round(v / grand, 3) if grand else 0,
            "first_seen": first[k],
            "top_component": max(mix[k].items(), key=lambda kv: kv[1])[0] if mix[k] else ""} for k, v in ranked]

    def render(d):
        print(f"Top {a.by}s, last {a.days} days (total {money(grand)})")
        table([[x["name"][:52], money(x["cost"]), f"{x['share']*100:.0f}%", x["first_seen"], x["top_component"][:30]] for x in d],
              [a.by, "cost", "share", "first seen", "biggest component"])
    emit(out, a.json, render)


def cmd_today(a):
    rows = cli_json(["billing", "report", "--for", "today", "-r", "h", "--tz", "local", "--show-resources"])
    hr = collections.defaultdict(float)
    app = collections.defaultdict(float)
    for r in rows:
        hr[r["interval_start"][11:13]] += float(r["cost"])
        app[r.get("description") or r.get("object_id")] += float(r["cost"])
    hours = sorted(hr)
    complete = hours[:-1] if len(hours) > 1 else hours
    rate = sum(hr[h] for h in complete[-3:]) / max(1, len(complete[-3:]))
    out = {"hourly": {h: round(hr[h], 2) for h in hours}, "total_so_far": round(sum(hr.values()), 2),
           "run_rate_per_hour_last3": round(rate, 2), "run_rate_per_day": round(rate * 24, 2),
           "top_apps": [{"app": k, "cost": round(v, 2)} for k, v in sorted(app.items(), key=lambda kv: -kv[1])[:10]]}

    def render(d):
        print("Hourly (local): " + "  ".join(f"{h}:{money(v)}" for h, v in d["hourly"].items()))
        print(f"Today so far {money(d['total_so_far'])}; run rate {money(d['run_rate_per_hour_last3'])}/h (~{money(d['run_rate_per_day'])}/day)")
        table([[x["app"][:55], money(x["cost"])] for x in d["top_apps"]], ["app", "today"])
    emit(out, a.json, render)


def running_by_app():
    containers = cli_json(["container", "list"])
    apps = {x["app_id"]: x for x in cli_json(["app", "list"])}
    by = collections.defaultdict(list)
    for c in containers:
        by[c.get("app_id")].append(c)
    return by, apps


def uptime_hours(ts):
    try:
        t = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        return (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 3600
    except Exception:
        return None


def cmd_active(a):
    by, apps = running_by_app()
    today = {}
    for r in cli_json(["billing", "report", "--for", "today", "-r", "d"]):
        today[r.get("object_id")] = today.get(r.get("object_id"), 0) + float(r["cost"])
    out = []
    for app_id, cs in by.items():
        info = apps.get(app_id, {})
        ups = [u for u in (uptime_hours(c.get("start_time")) for c in cs) if u is not None]
        out.append({"app_id": app_id, "name": info.get("description") or cs[0].get("app_name"), "state": info.get("state"),
                    "containers": len(cs), "oldest_container_h": round(max(ups), 1) if ups else None,
                    "cost_today": round(today.get(app_id, 0), 2)})
    out.sort(key=lambda x: -x["cost_today"])

    def render(d):
        table([[x["name"][:50], x["state"], x["containers"], x["oldest_container_h"], money(x["cost_today"])] for x in d],
              ["app", "state", "containers", "oldest (h)", "cost today (UTC)"])
    emit(out, a.json, render)


SDK_FUNCTIONS = r'''
import asyncio, json, sys, modal
from modal.client import _Client
from modal_proto import api_pb2
async def layouts(ids):
    c = await _Client.from_env()
    out = {}
    for app_id in ids:
        try:
            r = await c.stub.AppGetLayout(api_pb2.AppGetLayoutRequest(app_id=app_id))
            out[app_id] = list(dict(r.app_layout.function_ids).keys())
        except Exception as e:
            out[app_id] = {"error": str(e)[:200]}
    return out
apps = json.loads(%(apps)r)
lay = asyncio.run(layouts([x["app_id"] for x in apps]))
res = []
for x in apps:
    fns = lay.get(x["app_id"])
    if not isinstance(fns, list):
        res.append({**x, "error": fns}); continue
    for fn in fns:
        try:
            f = modal.Function.from_name(x["name"], fn); f.hydrate()
            s = f.get_current_stats()
            res.append({**x, "function": fn, "runners": s.num_total_runners, "running_inputs": s.num_running_inputs, "backlog": s.backlog})
        except Exception as e:
            res.append({**x, "function": fn, "error": str(e)[:200]})
print(json.dumps(res))
'''


def function_stats(apps):
    code = SDK_FUNCTIONS % {"apps": json.dumps(apps)}
    return run_sdk(code) or []


def cmd_idle(a):
    by, apps = running_by_app()
    targets = [{"app_id": k, "name": apps.get(k, {}).get("description") or v[0].get("app_name")}
               for k, v in by.items() if apps.get(k, {}).get("state") == "deployed"]
    stats = function_stats(targets)
    start, end = window(a.days)
    cost = collections.defaultdict(float)
    for r in billing_rows(start, end, "d", resources=False):
        cost[r.get("object_id")] += float(r["cost"])
    protected = set(load_config().get("protected_apps", []))
    idle = [s for s in stats if not s.get("error") and s.get("runners", 0) > 0 and s.get("running_inputs", 0) == 0 and s.get("backlog", 0) == 0]
    for s in idle:
        s["cost_window"] = round(cost.get(s["app_id"], 0), 2)
        s["protected"] = s["name"] in protected
    idle.sort(key=lambda s: -s["cost_window"])

    def render(d):
        if not d:
            print("No idle warm functions right now.")
            return
        print(f"Functions holding warm containers with no work in flight (cost = whole app, last {a.days} days):")
        table([[s["name"][:42], s["function"][:28], s["runners"], money(s["cost_window"]), "yes" if s["protected"] else ""] for s in d],
              ["app", "function", "runners", "app cost", "protected"])
        print("\nTo scale one to zero (cold starts after): modal_skill.py scale APP FUNCTION --min 0 --yes")
    emit(idle, a.json, render)


def cmd_app(a):
    apps = cli_json(["app", "list"])
    match = [x for x in apps if x.get("description") == a.name or x.get("app_id") == a.name]
    if not match:
        sys.exit(f"No app named {a.name}")
    info = sorted(match, key=lambda x: str(x.get("created_at")))[-1]
    by, _ = running_by_app()
    stats = function_stats([{"app_id": info["app_id"], "name": info["description"]}]) if info.get("state") == "deployed" else []
    start, end = window(a.days)
    day = collections.defaultdict(float)
    res = collections.defaultdict(float)
    for r in billing_rows(start, end, "d", resources=True):
        if r.get("object_id") == info["app_id"]:
            day[r["interval_start"][:10]] += float(r["cost"])
            res[r["resource"]] += float(r["cost"])
    out = {"app": info, "containers": len(by.get(info["app_id"], [])), "functions": stats,
           "daily": {k: round(v, 2) for k, v in sorted(day.items())},
           "by_resource": {k: round(v, 2) for k, v in sorted(res.items(), key=lambda kv: -kv[1])},
           "total": round(sum(day.values()), 2)}

    def render(d):
        i = d["app"]
        print(f"{i['description']}  ({i['app_id']})  state={i['state']}  created={i.get('created_at')}  containers now={d['containers']}")
        for f in d["functions"]:
            print(f"  fn {f.get('function')}: runners={f.get('runners')} running_inputs={f.get('running_inputs')} backlog={f.get('backlog')} {f.get('error','')}")
        print(f"Cost, last {a.days} days: {money(d['total'])}  by resource: " + ", ".join(f"{k} {money(v)}" for k, v in d["by_resource"].items()))
        for k, v in d["daily"].items():
            print(f"  {k}  {money(v)}")
    emit(out, a.json, render)


def cmd_report(a):
    args = ["billing", "report"]
    if a.start:
        args += ["--start", a.start]
    if a.end:
        args += ["--end", a.end]
    if getattr(a, "for_", None):
        args += ["--for", a.for_]
    args += ["-r", a.resolution]
    if a.show_resources:
        args.append("--show-resources")
    if a.csv:
        args.append("--csv")
    elif a.json:
        args.append("--json")
    print(run_cli(args, timeout=600))


# ---------- write commands ----------

def guard(app_name, a, action):
    protected = set(load_config().get("protected_apps", []))
    if app_name in protected and not a.force:
        sys.exit(f"{app_name} is in protected_apps (config.json). Re-run with --force after confirming with Idan.")
    if not a.yes:
        print(f"DRY RUN: would {action}. Re-run with --yes after Idan confirms.")
        return False
    return True


def cmd_scale(a):
    settings = {"min_containers": a.min}
    if a.max is not None:
        settings["max_containers"] = a.max
    if a.buffer is not None:
        settings["buffer_containers"] = a.buffer
    if a.scaledown_window is not None:
        settings["scaledown_window"] = a.scaledown_window
    if not guard(a.app, a, f"set autoscaler {settings} on {a.app}.{a.function}"):
        return
    code = (
        "import json, modal\n"
        f"f = modal.Function.from_name({a.app!r}, {a.function!r}); f.hydrate()\n"
        f"f.update_autoscaler(**{settings!r})\n"
        "s = f.get_current_stats()\n"
        "print(json.dumps({'ok': True, 'runners': s.num_total_runners, 'running_inputs': s.num_running_inputs, 'backlog': s.backlog}))\n"
    )
    print(json.dumps(run_sdk(code), indent=2))
    print("Note: update_autoscaler lasts until the app is next deployed; change the code's min_containers too, or a redeploy restores it.")


def cmd_stop(a):
    if not guard(a.app, a, f"stop app {a.app} (all its containers)"):
        return
    print(run_cli(["app", "stop", a.app]))


def main():
    p = argparse.ArgumentParser(description="Modal cost visibility and control")
    p.add_argument("--json", action="store_true", help="JSON output")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("summary"); s.add_argument("--for", dest="period")
    s = sub.add_parser("burn"); s.add_argument("--days", type=int, default=14)
    s = sub.add_parser("top"); s.add_argument("--days", type=int, default=7); s.add_argument("--by", choices=["app", "resource"], default="app"); s.add_argument("--limit", type=int, default=15)
    sub.add_parser("today")
    sub.add_parser("active")
    s = sub.add_parser("idle"); s.add_argument("--days", type=int, default=7)
    s = sub.add_parser("app"); s.add_argument("name"); s.add_argument("--days", type=int, default=14)
    s = sub.add_parser("report"); s.add_argument("--start"); s.add_argument("--end"); s.add_argument("--for", dest="for_"); s.add_argument("-r", "--resolution", default="d"); s.add_argument("--show-resources", action="store_true"); s.add_argument("--csv", action="store_true")
    s = sub.add_parser("scale"); s.add_argument("app"); s.add_argument("function"); s.add_argument("--min", type=int, required=True); s.add_argument("--max", type=int); s.add_argument("--buffer", type=int); s.add_argument("--scaledown-window", type=int); s.add_argument("--yes", action="store_true"); s.add_argument("--force", action="store_true")
    s = sub.add_parser("stop"); s.add_argument("app"); s.add_argument("--yes", action="store_true"); s.add_argument("--force", action="store_true")

    a = p.parse_args()
    {"summary": cmd_summary, "burn": cmd_burn, "top": cmd_top, "today": cmd_today, "active": cmd_active,
     "idle": cmd_idle, "app": cmd_app, "report": cmd_report, "scale": cmd_scale, "stop": cmd_stop}[a.cmd](a)


if __name__ == "__main__":
    main()
