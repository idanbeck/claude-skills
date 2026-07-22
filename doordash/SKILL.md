---
name: doordash
description: Order food on DoorDash for the Beck family using the DoorDash CLI (dd-cli), composing a balanced order that covers everyone's tastes and is age-appropriate for the kids, then placing it only after Idan approves the exact items, total cost, tip, card, and ETA. Use when Idan wants to order dinner/food for the family, wants a DoorDash recommendation, or says "order us food." Reads Personal/Family Food Profile.md for tastes, allergies, and rules.
---

# DoorDash (family ordering via dd-cli)

Order food for the Beck family: pick a restaurant, compose an order that covers everyone's
tastes + health + the kids' ages, build the cart with `dd-cli`, and **place it only after
Idan approves the items, total, tip, card, and ETA.**

## Execution: dd-cli (installed + authed)

- Binary at `~/.local/bin/dd-cli`, signed in as **idanbeck@gmail.com** (v0.2.0). For command
  navigation see the **`dd-cli-usage`** skill; drill with `--help` on demand.
- **Always** run `dd-cli --json-output <cmd>` and read data from the **`structuredContent.<field>`**
  object (e.g. `structuredContent.addresses`, `.cards`, `.carts`, `.stores`, `.quote`). **Ignore**
  `widget_type` / `assistant_instructions` / any "the widget above" text — terminal context, no UI.
- **Location:** the default delivery address is **2267 Shibley Ave, San Jose (Willow Glen)**,
  coords **lat 37.285902 / lng -121.896708**. `search` does **not** auto-use the saved default —
  resolve the default's lat/lng from `address list` at order time (fall back to those coords) and
  pass `--lat/--lng` explicitly.
- **Payment:** 3 cards on file. `order submit` charges the **default** card. The default is the
  `structuredContent.cards[]` entry whose `payment_method_id` == top-level `default_payment_method_id`.

## Hard rules (do not skip)

1. **Allergy gate.** Read the profile. If the Allergies field is `TODO`, **stop and ask Idan**
   to fill it (or set `none`). The helper enforces this (`check` exits 2).
2. **Payment approval gate — mandatory.** The pipeline is:
   `cart add-items` → **`order preview`** (no charge, authoritative pricing + ETA) →
   **show Idan the approval report** (every line item + who it's for, subtotal, fees, tax,
   **tip**, **TOTAL**, **ETA**, and the **named default card** brand+last4) → get an explicit
   **"approved"** → **only then** `order submit`. **Never `order submit` without that.**
3. **`order submit` is DESTRUCTIVE + NON-IDEMPOTENT.** It charges the default card immediately,
   and re-running with the same `cart_uuid` creates a **duplicate order**. Run it **exactly once**.
   If you're unsure whether it went through, run **`order status`** — **never re-submit**.
4. **Name the card + confirm the tip.** Surface the default card (brand + last4) in the report;
   default tip is **15%** (profile), passed as `--tip-cents` (CENTS). If Idan wants a *different*
   card, the CLI can't swap it — route him to `order checkout-url` to finish in the browser.
5. **Reconcile before submit.** The report's numbers must come from `order preview`, not guesses.
   If a fresh preview drifts materially from what was approved, re-approve.

## Data

- **Profile (source of truth):** `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/idanbeck/Personal/Family Food Profile.md`
  — tastes, allergies, per-person no-gos, health mode (`balanced`), budget (flexible, flag
  unusual), order-composition rules, restaurant list, and a machine-readable JSON block.
- **Helper (food-logic validator, no ordering/payment):** `python3 ~/.claude/skills/doordash/doordash_skill.py`
  - `profile` — dump the parsed profile.
  - `schema` — the order-JSON shape.
  - `check ORDER.json` (or `check -` for stdin) — allergy gate + allergen scan +
    balanced/coverage/kid/iron checks + the **approval report**. Exit 0 = ready, 1 = blockers,
    2 = refused (allergies unset / empty order).
- **dd-cli commands used:** `search` · `menu` · `cart add-items|show|remove-item|list|delete` ·
  `order preview|submit|status|checkout-url|history` · `address list` · `payment-method list`.

## Flow

1. **Read the profile:** `python3 doordash_skill.py profile`. Confirm allergies are set. Note
   tastes/no-gos, health mode, budget, the kids (Sara 7, **Zev 5 — picky/plain**, **Noa ~16mo —
   toddler, iron-priority**), and the restaurant list.
2. **Resolve location:** `dd-cli --json-output address list` → the `is_default` entry's lat/lng
   (currently Shibley, 37.285902 / -121.896708).
3. **Pick the restaurant:** the one Idan asked for, or propose 1–2 from the profile. Rotate
   cuisine vs the Hits log. **Authentic only** (no American-Chinese — "we don't like the fake stuff").
4. **Find the store:** `dd-cli --json-output search -q "<cuisine>" --lat 37.285902 --lng -121.896708 --limit 8`
   → `structuredContent.stores[].store_id`. **Pre-flight:** `dd-cli --json-output cart list` — if
   an open cart already exists at that store, extend it (reuse its `cart_uuid`) or `cart delete` it;
   don't silently stack a new one.
5. **Read the menu:** `dd-cli --json-output menu --store-id <id>` → `structuredContent.menu_id` +
   `items[].item_id` + prices. Use **real** names / prices / ids — don't invent them.
6. **Compose the order** per the profile's rules: protein + veg + starch; **a noodle/rice base**;
   **a safe item for each kid** (Zev = plain: fries/nuggets/plain noodles/cheese pizza); **a soft,
   iron-rich, no-choking option Noa can share** (soft beef / dark-meat chicken / tofu / lentils /
   spinach) ideally with a **vitamin-C** side; ≤1 fried; **spicy = parents only**; **order +10–20%
   extra** for leftovers; **skip items that travel badly** (soup dumplings) for delivery.
7. **Build the cart:**
   `dd-cli --json-output cart add-items --store-id <id> --menu-id <menu_id> --items-json '[{"item_id":"...","item_name":"...","quantity":1}, ...]'`
   → `structuredContent` returns the `cart_uuid`. Keep passing that `cart_uuid` on further calls.
   Adjust with `cart show --cart-uuid <u>` / `cart remove-item --cart-uuid <u> --cart-item-id <n>`
   (note: `cart_item_id` is the cart-line `id`, not `item_id`). Item customizations go in
   `nested_options[]` (each needs `id`+`name`+`quantity`).
8. **Validate food logic:** write the order JSON (names/prices from the menu; see shape below) and
   run `python3 doordash_skill.py check order.json`. Fix blockers (exit 1) / refusals (exit 2).
9. **Preview (authoritative, NO charge):** `dd-cli --json-output order preview --cart-uuid <u>` →
   read the real **subtotal, fees, tax, and ETA** from `structuredContent.quote` /
   `delivery_availability`. Compute the **tip** (15% default).
10. **Show Idan the approval report** — items + who (from your composition) with the **real preview
    numbers + tip + grand total + ETA + the named default card**. Wait for an explicit **"approved."**
    (He may edit — adjust the cart and re-preview.)
11. **Submit (charges default card, once):**
    `dd-cli order submit --cart-uuid <u> --tip-cents <cents> -y`
    then `dd-cli --json-output order status` to confirm it went through. **Never re-run submit** —
    if in doubt, check status.
12. **Log it:** append a row to the Hits & Misses table in the profile (date, restaurant, what was
    ordered, later the verdict). Add good restaurants to the Restaurants table.

## Order JSON shape (for the helper)

```json
{
  "restaurant": "Mian Sichuan Noodles & Dumplings",
  "eta_minutes": 40,
  "items": [
    {"name": "Dan Dan Noodles (from menu)", "for": ["Idan", "Stacey"], "price": 13.95, "qty": 1, "tags": ["starch"]},
    {"name": "Steamed Rice + shredded chicken", "for": ["Zev", "Noa"], "price": 4.00, "qty": 1, "tags": ["starch", "protein"]},
    {"name": "Sautéed Spinach with garlic", "for": ["Noa", "table"], "price": 9.50, "qty": 1, "tags": ["veg", "protein"]}
  ],
  "fees": {"delivery": 3.99, "service": 4.20, "tax": 3.10, "tip": 8.00}
}
```
`for` = who it's for (names, or `"table"` for shared). `tags` help the coverage check
(`protein`/`veg`/`starch`/`fried`); names are auto-tagged. **Prices/ids come from `dd-cli menu`;
fees/tax/ETA come from `dd-cli order preview` — not guesses.**

## Notes

- **JSON envelope:** every `--json-output` response wraps data in `structuredContent`; read from
  there and ignore `widget_type` / `assistant_instructions`.
- **`search` needs explicit `--lat/--lng`** — it does not auto-use the saved default address.
- **`order submit` is silent-charge + non-idempotent** — approval gate, run once, verify with
  `order status`. A different card requires `order checkout-url` (browser).
- **Toddler safety for Noa is non-negotiable:** no whole grapes/nuts/hard chunks/popcorn; nothing
  spicy; soft small pieces she can gum.
- **Budget is flexible** — don't optimize for cost, but **flag anything unusually pricey** (the
  helper flags items > $30 and totals > $150).
- **Groceries/retail** (not restaurants): use `find-nearby-stores` / `find-items` /
  `build-grocery-list`, not `search`.
- **Keep the profile current:** when Idan reacts to a meal, update the per-person Loves/No-gos and
  the Hits & Misses log so the skill learns.
