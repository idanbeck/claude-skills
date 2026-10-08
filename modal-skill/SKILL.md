---
name: modal-skill
description: See and control Modal spend for the Epoch workspace. Billing summaries with month-end projection, daily burn, top spenders by app or resource, today's hourly run rate, running apps, idle warm functions, and per-app drill-downs. Can scale a function's warm pool or stop an app, but only with explicit confirmation. Use when the user asks about Modal costs, GPU spend, what's running on Modal, warm containers, or wants to cut Modal usage.
allowed-tools: Bash, Read
---

# Modal Skill: costs and control

Wraps the `modal` CLI (billing, apps, containers) and the Modal SDK (function stats, autoscaler). It uses whatever profile `modal profile current` shows (here: `epoch`).

```bash
M=~/.claude/skills/modal-skill/modal_skill.py
```

## Read commands (always safe)

| Command | What it shows |
|---|---|
| `python3 $M summary` | This month billed and metered, breakdown (deployed, ephemeral, LLM tokens, volumes), **projected month total** |
| `python3 $M summary --for "last month"` | Any month (`YYYY-MM` also works) |
| `python3 $M burn --days 14` | Daily spend chart, 7-day average, 30-day projection |
| `python3 $M top --days 7 [--by resource] [--limit 15]` | Top apps (or resources: L4, H100, B200, CPU…) with share, first-seen date and biggest component. New apps show up by their first-seen date |
| `python3 $M today` | Hourly spend today (local time), run rate per hour and per day, top apps today |
| `python3 $M active` | Apps with running containers: count, oldest container's age, cost today (UTC) |
| `python3 $M idle --days 7` | **Warm functions doing nothing:** runners > 0, no inputs in flight, empty backlog. Main source of avoidable always-on cost |
| `python3 $M app NAME --days 14` | One app: functions, live stats, cost per day and per resource |
| `python3 $M report --start 2026-10-01 [--end …] [-r h] [--show-resources] [--csv]` | Raw billing report passthrough (daily ranges ≤ 31 days) |

Add `--json` before the subcommand for machine-readable output, e.g. `python3 $M --json top --days 7`.

## Write commands (dry run unless `--yes`)

| Command | Effect |
|---|---|
| `python3 $M scale APP FUNCTION --min 0 [--max N] [--buffer N] [--scaledown-window S] --yes` | Changes the live autoscaler (`Function.update_autoscaler`). **Lasts until the app is redeployed.** Also change `min_containers` in the app's code, or the next deploy brings the warm pool back |
| `python3 $M stop APP --yes` | `modal app stop`. Ends every container in the app |

## Rules
1. **Never run `scale` or `stop` with `--yes` until Idan has confirmed that exact action in chat.** Run without `--yes` first and show the dry run.
2. **Apps in `protected_apps` (config.json) also need `--force`.** These are customer-facing production paths (e.g. the OCR services). Scaling them to zero adds cold starts to production.
3. **Don't stop another session's running work** (corsair CI, canaries, hive runs) without asking. Find out who owns it first; `app NAME` shows when it was created.
4. Billing data lags by roughly an hour. Hourly figures for the current hour are partial.
5. Cost is per app, not per function. `idle` shows the whole app's cost next to an idle function.

## Config (`config.json`, gitignored; see `config.example.json`)
```json
{ "monthly_budget": 10000, "protected_apps": ["zep-unlimited-ocr", "zep-paddle-ocr-vlm", "zep-document-ocr-ensemble"] }
```

## Setup
- `modal` CLI installed (`brew install modal` or `pip install modal`) and authenticated (`modal token new`, profile `epoch`).
- SDK commands run under the CLI's own Python (read from the `modal` script's shebang), so the SDK version always matches the CLI.
