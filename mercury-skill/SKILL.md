# Mercury Skill — Read-only banking + burn analysis

Read Mercury bank balances and transactions, and compute net burn over a period. Use when the user asks about cash on hand, bank balances, what left the accounts, or monthly burn from the bank side.

**Read-only.** The token cannot move money. Pairs with `ramp-skill` for card/spend burn.

## Setup (one time)

1. Mercury dashboard → **Settings → Tokens** → generate a token, scope it **read-only**.
2. Save it:
   ```bash
   echo '{"api_token": "secret-token:..."}' > ~/.claude/skills/mercury-skill/config.json
   ```

## Commands

All output is JSON on stdout. Errors → JSON on stderr, non-zero exit.

```bash
# Balances across all accounts + total cash
python3 ~/.claude/skills/mercury-skill/mercury_skill.py accounts

# Quick "what's in the bank" number
python3 ~/.claude/skills/mercury-skill/mercury_skill.py summary

# Transactions in a date range (account = id, name substring, or 'all')
python3 ~/.claude/skills/mercury-skill/mercury_skill.py transactions all --start 2026-06-01 --end 2026-06-30
python3 ~/.claude/skills/mercury-skill/mercury_skill.py transactions checking --start 2026-06-01 --end 2026-06-30 --status sent

# Net burn over a period, broken down by counterparty + kind
python3 ~/.claude/skills/mercury-skill/mercury_skill.py burn --start 2026-06-01 --end 2026-06-30
python3 ~/.claude/skills/mercury-skill/mercury_skill.py burn --start 2026-06-01 --end 2026-06-30 --realized-only --top 30
```

## Notes

- Amounts: debits (money out) are **negative**, credits (money in) **positive**. `burn` reports `gross_outflow`, `gross_inflow`, and `net_burn = outflow − inflow`.
- `burn` excludes `cancelled`/`failed`. `--realized-only` counts just `sent`/`posted` in the outflow (excludes pending); pending is reported separately either way.
- `transactions`/`burn` auto-paginate the full range.
- Stdlib only (urllib); no dependencies.

## API

- Base: `https://api.mercury.com/api/v1`
- `GET /accounts`, `GET /account/{id}/transactions?limit=&offset=&start=&end=&status=`
- Auth: `Authorization: Bearer <api_token>`
