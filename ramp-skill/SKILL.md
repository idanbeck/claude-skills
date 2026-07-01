# Ramp Skill — Read-only card spend + burn breakdown

Read Ramp card transactions and summarize spend by category / merchant / user over a period. Use when the user asks where card spend went, or to break down the card side of monthly burn.

Pairs with `mercury-skill`. **Important:** Ramp card spend is the *detail behind* the single "Ramp" debit that leaves the bank in Mercury — don't add the two burn totals together (double-count). Mercury = cash out; Ramp = what that cash bought.

## Setup (one time)

1. Ramp → **Settings → Developer API** (requires admin) → create an app → copy the **Client ID** and **Client Secret**, and grant read scopes (`transactions:read`, `users:read`, `cards:read`, `reimbursements:read`).
2. Save it:
   ```bash
   echo '{"client_id":"...","client_secret":"...","scopes":"transactions:read users:read cards:read reimbursements:read"}' \
     > ~/.claude/skills/ramp-skill/config.json
   ```
The OAuth token is fetched automatically and cached in `cache.json`.

## Commands

All output is JSON on stdout. Errors → JSON on stderr, non-zero exit.

```bash
# Total card spend over a period, broken down by category / merchant / user
python3 ~/.claude/skills/ramp-skill/ramp_skill.py spend-summary --start 2026-06-01 --end 2026-06-30

# Raw card transactions in a range
python3 ~/.claude/skills/ramp-skill/ramp_skill.py transactions --start 2026-06-01 --end 2026-06-30

# Reference
python3 ~/.claude/skills/ramp-skill/ramp_skill.py users
python3 ~/.claude/skills/ramp-skill/ramp_skill.py cards
```

## Notes

- Amounts are positive spend. `spend-summary` excludes `DECLINED`/`ERROR`; `PENDING` is included and reported separately.
- Auto-paginates the full range via the `page.next` cursor.
- Stdlib only (urllib); no dependencies.

## API

- Base: `https://api.ramp.com/developer/v1`
- Token: `POST /token` (Basic client_id:client_secret, `grant_type=client_credentials`)
- `GET /transactions?from_date=&to_date=&page_size=`, `GET /users`, `GET /cards`
- Auth: `Authorization: Bearer <access_token>`
