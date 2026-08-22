---
name: zergbnb-skill
description: Search stays, price a trip, book and cancel reservations, manage host properties and generated listings, submit reviews, and administer payments on zergbnb. Use when the user asks to find a place to stay, check availability or a total price, look at a booking, list or create host properties, generate listing copy from photos, check payout onboarding, or inspect zergbnb's ranking and fee policy.
allowed-tools: Bash, Read
---

# zergbnb

An Airbnb/VRBO competitor built on two structural bets. Both change how you
should use this tool, so read them before your first call.

1. **Hosts cannot write guest-visible prose.** Listing copy is generated from
   verified photo evidence, and every sentence cites the evidence it rests on.
   If a user asks you to "write a description" for their property, the answer is
   to upload better photos and run `properties generate` — the API will reject
   prose with a 422 that explains this.

2. **The total price is the price.** Quotes return what the guest actually pays,
   fees included, with cleaning folded into the nightly rate. There is no
   checkout-time reveal. When reporting a price to a user, report the **total**,
   not a per-night figure.

## Setup

```bash
cd /Users/idanbeck/zerg-stack/zapps/zergbnb
npm run cli -- profile set prod --base-url https://zergbnb.com --token-env ZERGBNB_TOKEN
```

The profile stores the *name* of an environment variable, never a token. Export
`ZERGBNB_TOKEN` for authenticated calls. Public commands need no credential.

## Output contract

Every command prints **one line of JSON to stdout**:

```json
{"ok":true,"result":{...}}
```

Failures print to **stderr** and never to stdout:

```json
{"ok":false,"error":{"code":"NOT_FOUND","message":"HTTP 404","details":{...}}}
```

Branch on the **exit code**, not the message:

| 0 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|
| ok | usage | config | auth needed | forbidden | not found | rate limited | network | api error |

`npm run cli -- help-exit-codes` prints this at runtime.

## Common workflows

### Find a place and price it

```bash
npm run cli -- listings search --query "beach house" --city "Santa Cruz" --guests 4
npm run cli -- listings search --lat 36.9741 --lng -122.0308 --radiusKm 25 --guests 4
npm run cli -- listings get 2-bed-santa-cruz-9vrorg
npm run cli -- listings quote --slug 2-bed-santa-cruz-9vrorg \
  --checkIn 2026-09-01 --checkOut 2026-09-04 --adults 2
```

The quote's `guestTotalCents` is what the guest pays. `lines` is the full
breakdown. There will never be a cleaning line — it is inside the nightly rate.

### Book

```bash
# Take quoteId from the quote above; the price is frozen to it.
npm run cli -- reservations book --quoteId <uuid>
npm run cli -- reservations get ZB-7K3M2Q
```

### Host a property

```bash
npm run cli -- properties create --hostAccountId <uuid> --propertyType apartment \
  --roomType entire_place --maxGuests 4 --bedrooms 2 --beds 3 --bathroomsTenths 15 \
  --city "Santa Cruz" --country US --latitude 36.9741 --longitude -122.0308
npm run cli -- properties extract-facts <propertyId>   # vision over the photos
npm run cli -- properties generate <propertyId>        # copy from that evidence
```

`generate` returns a `verifierReport`. If `status` is `needs_review`, the copy
failed verification — read `verifierReport.violations` and tell the user what
evidence is missing rather than offering to write the text yourself.

### Understand the ranking

```bash
npm run cli -- ranking explain
```

## Identifiers

Anywhere an id is accepted you may pass a **listing slug** or a **reservation
code** (`ZB-XXXXXX`) instead of a UUID. Do not look up a UUID first — it costs a
turn and buys nothing.

## Guardrails

- **Destructive actions plan by default.** `reservations cancel` and
  `admin set-mode` print what they *would* do and change nothing. Show that plan
  to the user and only re-run with `--confirm-reviewed` after they agree.
- **Never pass a token on the command line.** Use `--token-env`.
- **Never offer to write listing copy.** The API rejects it; the fix is evidence.
- **Quotes expire in 30 minutes.** If a booking fails with `quote_expired`, get a
  fresh quote rather than retrying the old one.
- **`admin set-mode live` charges real cards.** It needs a typed confirmation
  phrase and a recent sign-in. Do not run it unless the user explicitly asks.

## Escape hatch

Any route not wrapped above:

```bash
npm run cli -- api GET /api/some/route
npm run cli -- api POST /api/some/route -d key=value -d other=thing
```

Paths must start with `/` — absolute URLs are refused so a profile's credential
cannot be aimed at another host.

## Diagnosing

```bash
npm run cli -- doctor    # config state; never prints token values
npm run cli -- health    # liveness + database
npm run cli -- help      # the full resource catalog, machine-readable
```

`help` returns the entire catalog as JSON, so you can discover actions and their
flags at runtime rather than guessing from this document.
