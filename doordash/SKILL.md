---
name: doordash
description: Order food on DoorDash for the Beck family using the DoorDash CLI (dd-cli), composing a balanced order that covers everyone's tastes and is age-appropriate for the kids, then placing it only after Idan approves the exact items, total cost, tip, card, and ETA. Use when Idan wants to order dinner/food for the family, wants a DoorDash recommendation, or says "order us food." Reads Personal/Family Food Profile.md for tastes, allergies, and rules.
---

# DoorDash (family ordering via dd-cli)

Order food for the Beck family: pick a restaurant, compose an order that covers everyone's
tastes + health + the kids' ages, build the cart with `dd-cli`, and **place it only after
Idan approves the items, total, tip, card, and ETA.**

## Execution: dd-cli (installed + authed)

- Binary at `~/.local/bin/dd-cli`, signed in as **idanbeck@gmail.com** (**v0.2.3**). For command
  navigation see the **`dd-cli-usage`** skill; drill with `--help` on demand.
- **Always** run `dd-cli --json-output <cmd>` and read data from the **`structuredContent.<field>`**
  object (e.g. `structuredContent.addresses`, `.cards`, `.carts`, `.stores`, `.quote`). **Ignore**
  `widget_type` / `assistant_instructions` / any "the widget above" text — terminal context, no UI.
- **`--intent` is REQUIRED on every tool-backed command** (v0.2.2 / CLI-401) — `search`, `menu`,
  `cart *`, `order *`, `address list`, `payment-method list`. Omit it and the command errors out.
  Use this exact value for a family dinner run (two lines, and reuse it verbatim across the whole
  pipeline so the session reads as one workflow):

  ```
  Summary: Help Idan order dinner delivery for his family at home
  user prompt/purpose: "<Idan's verbatim ask, e.g. order us food for the family tonight>"
  ```

  Shell-friendly: `INTENT=$'Summary: ...\nuser prompt/purpose: "..."'` then `--intent "$INTENT"`.
- **🔒 `--intent` is sent to DoorDash and reviewed by them. NEVER put profile detail in it.**
  DoorDash's own guidance says to exclude health/medical details and information about other
  people. That means **no allergies, no Noa's iron requirement, no kids' names/ages, no
  "toddler"/"picky", no street address.** Keep the food logic local to this skill and the helper —
  the intent line stays generic ("his family at home"). This is the one field that leaves the box.
- **Auth (v0.2.3 — much better):** desktop sessions now keep a **refresh token** in the macOS
  keychain and renew the access token automatically, so the old "re-login every time it expires"
  tax is gone. You should rarely see an auth error now.
  If one does appear (*"missing credentials"* / *"Failed to authenticate"*), `dd-cli login` is an
  **interactive browser flow you cannot run** — **ask Idan to run `! dd-cli login` himself**, then
  re-verify with a read-only `address list` before continuing. Don't burn turns retrying.
  (Headless alternative, not needed on this Mac: `export-token` → `DD_CLI_ACCESS_TOKEN`;
  refresh tokens are NOT stored in headless/cloud contexts.)
- **Every subcommand — even `--help` — requires credentials.** Only the top-level `dd-cli --help`
  works signed out. So a bare `dd-cli order status --help` failing is an *auth* signal, not a
  missing-command signal.
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
   If you're unsure whether it went through, **do not re-submit** — recover the `order_uuid` from
   `order history` and check `order status --order-uuid <uuid>`.
   **Capture the `order_uuid` from the submit response immediately** — `order status` *requires*
   `--order-uuid`; there is no "status of my last order" call.
4. **Name the card + confirm the tip.** Surface the default card (brand + last4) in the report.
   **`--tip-cents` defaults to `0` (no tip) — always pass it explicitly**; default is **15%**
   (profile), in **CENTS** (`--tip-cents 800` = $8.00, not $0.08). If Idan wants a *different*
   card, the CLI can't swap it — route him to `order checkout-url` to finish in the browser.
5. **Reconcile before submit.** The report's numbers must come from `order preview`, not guesses.
   If a fresh preview drifts materially from what was approved, re-approve.
6. **Quote-matching flags.** `--priority` and `--no-apply-credits` **must be passed identically to
   `order preview` and `order submit`**, or the amount charged won't match the amount approved.
   Default for family orders: pass **neither** (standard delivery, credits auto-applied). Same rule
   for `--fulfillment` — omit at submit to inherit the cart's mode, or pass the *same* value.
7. **Never set `--include-work-benefits`** on a family order. Home delivery to Shibley is personal
   spend; work-benefits flags belong to Epoch/company orders only.

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
  - **⛔ BLOCKERS (exit 1 — must fix, never order through them):** allergen match · **spicy
    assigned to a kid or Noa** · **no iron-rich item for Noa** · a **kid with no item of their
    own** · a **travels-badly item** (soup dumplings/XLB) on a delivery order · **no noodle/rice
    base**. These are Idan's hard rules, not preferences.
  - **⚠️ Notes (exit 0 — advisory):** no veg, no protein, >1 fried, pricey item (>$30), high
    total (>$150), **`SPICE UNVERIFIED`**, **`AVOIDING`** (per-person soft avoid), and the
    standing Noa soft-food/choking reminder (can't be auto-verified — **you** must eyeball
    the actual dish).
  - 🌶️ **`SPICE UNVERIFIED` is the one to actually act on.** A dish name does **not** tell you
    the spice level, and `"table"` dishes reach the kids. Added 2026-08-14 after Cashew Chicken
    *and* Mixed Vegetable with Thai Basil both arrived spicy with neutral names — the name-based
    spicy scan passed both. When you see it: request mild explicitly in the item options /
    special instructions, swap to a structurally-plain dish, or make it parents-only.
  - **Per-person prefs are enforced from the profile JSON:** `no_gos[]` → **blocker**,
    `avoid_soft[]` → note, and `protein_preference[]` is surfaced as the suggested swap order.
    Matching is substring-on-item-name, so only concrete food words work (`"beef"` ✓,
    `"adventurous"` ✗ — harmless no-op).
  - *Fixed 2026-08-14: these hard rules were previously filed as soft notes, so `check` returned
    "Ready"/exit 0 on an order that was spicy-for-Zev, iron-less, and left Sara nothing. With
    `allergies: none` on file, exit 1 was unreachable — the validator could not block at all.*
- **dd-cli commands used:** `search` · `menu` · `cart add-items|show|remove-item|list|delete` ·
  `order preview|submit|status|checkout-url|history` · `address list` · `payment-method list`.

## Flow

**Set `INTENT` once at the top of the run and pass `--intent "$INTENT"` on every command below.**

0. **Auth pre-flight:** `dd-cli --json-output address list --intent "$INTENT"`. If it errors on
   auth, stop and ask Idan to run `! dd-cli login`. Everything downstream fails without this.
0b. 🔎 **PULL `dd-cli order history` BEFORE the vault's restaurant list — it is the real "historical".**
   `dd-cli --json-output order history --max 100 --days 365 --intent "$INTENT"` → count `store_name`
   frequency AND read `orders[].items[]` for the **exact repeat dishes to reorder**. The vault's
   Restaurants table is a hand-written *summary*; the order log is *evidence*, and on 2026-08-19
   they disagreed badly — the KB pointed at Sushi Koya/Yuki while the actual #1 was **Sushi Arashi
   (5 of 35 orders)**, with Akita and Harumi next and none of them in the KB. It also disproved a
   "not available locally" claim I'd written. **Then** fold in the profile for tastes/rules.
   ⚠️ **Absence from DoorDash history ≠ not a favorite** — Kazoo is a dine-in Japantown regular
   with zero delivery orders. If Idan names a place you don't see, `search` for it; don't doubt him.
1. **Read the profile:** `python3 doordash_skill.py profile`. Confirm allergies are set. Note
   tastes/no-gos, health mode, budget, the kids (Sara 7, **Zev 5 — picky/plain**, **Noa ~16mo —
   toddler, iron-priority**), and the restaurant list. *(Local only — never goes into `--intent`.)*
2. **Resolve location:** from the step-0 `address list` → the `is_default` entry's lat/lng
   (currently Shibley, 37.285902 / -121.896708). Scan the **full** `addresses[]` — the default can
   be anywhere in the list.
3. **Pick the restaurant:** the one Idan asked for, or propose 1–2 from the profile. Rotate
   cuisine vs the Hits log. **Authentic only** (no American-Chinese — "we don't like the fake stuff").
4. **Find the store:** `dd-cli --json-output search -q "<cuisine>" --lat 37.285902 --lng -121.896708 --limit 8 --intent "$INTENT"`
   → `structuredContent.stores[].store_id`. **Pre-flight:** `dd-cli --json-output cart list --intent "$INTENT"`
   — only **one open cart per store** is allowed, so if one already exists there, extend it (reuse
   its `cart_uuid`) or `cart delete` it; don't silently stack a new one.
4b. **⏱️ IF TIME MATTERS, CHECK ASAP FIRST.** `search` returns **no ETA**. A store that only does
   scheduled windows is indistinguishable from a 20-minute store until you preview a *built* cart.
   Build a minimal cart → `order preview` → confirm **`quote.delivery_availability.asap_available`
   is `true`** and read `asap_minutes_range_string`. **Then** hone the items. (2026-08-14: composed
   a full IZAKA-YA order before discovering `asap_available: false`, earliest window 8:10 PM on a
   7:20 PM order — total rebuild under time pressure.) Abandoning a store? `cart delete --cart-uuid`.
5. **Read the menu:** `dd-cli --json-output menu --store-id <id> --intent "$INTENT"` →
   `structuredContent.menu_id` + `items[].item_id` + prices. Use **real** names / prices / ids —
   don't invent them. **Ignore `is_popular` / `popularity_rank`** — DoorDash says that data isn't
   decision-grade right now.
5b. **Assign proteins per person BEFORE composing.** When a dish takes a protein choice, read the
   person's `protein_preference[]` from the profile. **Stacey → seafood → tofu → chicken; beef
   last and generally not at all** (and never low-grade Thai-restaurant beef — that's what made
   2026-08-14 a miss). Don't let one protein dominate the whole order.
5c. 📏 **SIZE FOR THE ADULTS.** Idan and Stacey eat the majority of every order; the kids barely
   dent theirs. A long item list is NOT the same as enough food — the 2026-08-19 Kazoo order ran
   15 items at a nominal +40% and **both adults were still hungry with almost no leftovers**.
   When adding the leftover buffer, add **substantial adult mains** (donburi, chirashi, entrées,
   combo boats), never more sides or small plates.
5d. 🔍 **Judge the PORTION, not the name or the price.** "Poki Salad" at $11.45 read like a full
   salad and arrived as an appetizer. Anything from an appetizer/small-plate section is a side,
   full stop. And **never double up on one ingredient** — tamago nigiri *plus* a tamago omelet
   meant two egg dishes and neither got eaten.
6. **Compose the order** per the profile's rules: protein + veg + starch; **a noodle/rice base**;
   **a safe item for each kid** (Zev = plain: fries/nuggets/plain noodles/cheese pizza); **a soft,
   iron-rich, no-choking option Noa can share** (soft beef / dark-meat chicken / tofu / lentils /
   spinach) ideally with a **vitamin-C** side; ≤1 fried; **spicy = parents only**; **order +10–20%
   extra** for leftovers; **skip items that travel badly** (soup dumplings) for delivery.
7. **Build the cart:**
   `dd-cli --json-output cart add-items --store-id <id> --menu-id <menu_id> --items-json '[{"item_id":"...","item_name":"...","quantity":1}, ...]' --intent "$INTENT"`
   → `structuredContent` returns the `cart_uuid`. Keep passing that `cart_uuid` on further calls.
   Adjust with `cart show --cart-uuid <u>` / `cart remove-item --cart-uuid <u> --cart-item-id <n>`
   (note: `cart_item_id` is the cart-line `id`, not `item_id`). Item customizations go in
   `nested_options[]` (each needs `id`+`name`+`quantity`). **Don't pass `--group-cart`** — that's a
   shareable multi-participant cart, not what a family dinner on one card needs.
   - **Expect partial failures.** Many restaurant mains have a **required** option group
     (`Protein Choice`) and error with `item_validation_error`. **The error payload returns
     `item_errors[].required_options[]` with every option's `id`/`name`/`price`** — read it and
     re-add those items with `nested_options`, appending via `--cart-uuid`. Don't re-fetch the menu.
   - **Always check `item_errors` and the `Cart now has N items` count** — `cart add-items` reports
     *partial* success (`"partially succeeded"`) and returns exit 0. Silently missing items is the
     failure mode.
   - **Search dish names loosely/phonetically.** Menus spell things their own way — Pad See Ew was
     listed as `#132. Pad Se Ew`. A strict regex on the spoken spelling finds nothing and you'll
     wrongly conclude the restaurant doesn't carry it.
   - ⚠️ **`menu` returns a CAPPED ~150 items.** Items you have genuinely ordered before can be
     absent from the response (Ikura and Chicken Katsu were missing for Arashi despite appearing in
     past orders). **Never conclude "they don't carry it" from `menu` alone** — cross-check
     `order history`, and search names loosely (nigiri is often listed as `"<Fish> (2 Pcs)"`).
   - **Parse menus with Python `json`, not `grep -oE`** — a regex sweep over a ~200KB menu JSON can
     backtrack catastrophically and hang for minutes.
   - **Confirm a specifically-requested dish exists BEFORE committing to a store** (Zev's satay
     wasn't on any of Thai Spice's 123 items). Check, then pick the restaurant.
8. **Validate food logic:** write the order JSON (names/prices from the menu; see shape below) and
   run `python3 doordash_skill.py check order.json`. Fix blockers (exit 1) / refusals (exit 2).
9. **Preview (authoritative, NO charge):**
   `dd-cli --json-output order preview --cart-uuid <u> --intent "$INTENT"` → read the real
   **subtotal, fees, tax, and ETA** from `structuredContent.quote` / `delivery_availability`.
   Compute the **tip** (15% default). Pass no `--priority` / `--no-apply-credits` (see rule 6).
10. **Show Idan the approval report** — items + who (from your composition) with the **real preview
    numbers + tip + grand total + ETA + the named default card**. Wait for an explicit **"approved."**
    (He may edit — adjust the cart and re-preview.)
11. **Submit (charges default card, once):**
    `dd-cli --json-output order submit --cart-uuid <u> --tip-cents <cents> -y --intent "$INTENT"`
    **Immediately record `order_uuid` from the response**, then confirm with
    `dd-cli --json-output order status --order-uuid <order_uuid> --intent "$INTENT"`.
    **Never re-run submit.** If the response was lost, find the order via
    `order history --intent "$INTENT"` and check its status — do not submit again.
    - 🔴 **v0.2.3 `order status` schema — VERIFIED 2026-08-19 against a real past order.**
      **The status field MOVED into `result` and the vocabulary CHANGED:**
      ```
      structuredContent.success                    true
      structuredContent.message                    "Order Complete"
      structuredContent.result.status              "completed"   ← was "successful" at TOP level
      structuredContent.result.action_required     false
      structuredContent.result.merchant_name       "Thai Spice"
      structuredContent.result.is_pickup           false
      structuredContent.result.quoted_delivery_time / actual_delivery_time
      structuredContent.result.estimated_pickup_time / actual_pickup_time
      structuredContent.result.delivery_window_start / delivery_window_end
      structuredContent.result.eta_trend           (running-late trend, null when on time)
      structuredContent.result.late_reason / cancellation_reason / status_message
      structuredContent.result.status_updated_at
      ```
      ☠️ **This is a silent-failure trap.** v0.2.2 code reading `structuredContent.status` now
      gets `None`, and `"successful"` no longer appears anywhere — so a naive
      `status == "successful"` check reads as "the order did NOT go through" on an order that
      went through perfectly. Combined with a non-idempotent `order submit`, that could tempt a
      DUPLICATE CHARGE. **Read `result.status`, and treat an unrecognized value as UNKNOWN —
      never as failure, and never as grounds to re-submit.** When in doubt, `order history`.
      Timestamps are **UTC (Z)** — convert before showing Idan a local time.
    - Because status is now richer, `order status` is worth re-polling to answer "where is it?"
      rather than only as a one-shot did-it-go-through check.
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
- **`--intent` is required everywhere (v0.2.2)** and is **transmitted to DoorDash** — generic only,
  no allergies / medical / kids' details / address. See the Execution section for the exact wording.
- **`search` needs explicit `--lat/--lng`** — it does not auto-use the saved default address.
  Without them it falls back to `DD_LAT`/`DD_LNG` and finally a **Cupertino default** — wrong city,
  wrong stores. Always pass them.
- **`order submit` is silent-charge + non-idempotent** — approval gate, run once, capture
  `order_uuid`, verify with `order status --order-uuid <uuid>`. A different card requires
  `order checkout-url` (browser). **`order status` output shape changed in v0.2.3 — re-verify
  the field names on first live use.**
- **New in v0.2.3 (verified):** `address find --query "<address>"` resolves free text to
  candidates, `address add --place-id <id>` saves it **as the default** (⚠️ does **NOT** dedupe —
  run `address list` first), and `address set` changes the default among saved ones. Also
  `order history --include-group-order` (plus `--max` 1-100, `--days` default 90 / cap 365).
- **`--tip-cents` defaults to 0** — silently no tip if you forget it. Always pass it.
- **Version note:** now on **v0.2.3** (2026-08-19, checksum-verified). Backups:
  `~/.local/bin/dd-cli.v0.2.2.bak`, `dd-cli.v0.2.0.bak`.
  - ⚠️ **v0.2.3 changed PACKAGING to a PyInstaller *onedir* bundle.** The binary alone is NOT
    runnable — it needs a sibling **`~/.local/bin/_internal/`** directory (~19MB). **Install by
    running the archive's `bash install.sh`**, never by copying just the binary (that fails with
    `Failed to load Python shared library ... _internal/libpython3.13.dylib`). Same applies to any
    future upgrade.
  - 🔴 **v0.2.3 `order status` response shape changed and is explicitly NOT backward-compatible.**
  - Also new in 0.2.3: `address find` / `address add`, `order history --include-group-order`,
    and automatic keychain token refresh.
  - v0.2.2 brought mandatory `--intent`, headless `DD_CLI_ACCESS_TOKEN`, group carts,
    `--priority`, `--no-apply-credits`.
- **Toddler safety for Noa is non-negotiable:** no whole grapes/nuts/hard chunks/popcorn; nothing
  spicy; soft small pieces she can gum.
- **Budget is flexible** — don't optimize for cost, but **flag anything unusually pricey** (the
  helper flags items > $30 and totals > $150).
- **Groceries/retail** (not restaurants): use `find-nearby-stores` / `find-items` /
  `build-grocery-list`, not `search`.
- **Keep the profile current:** when Idan reacts to a meal, update the per-person Loves/No-gos and
  the Hits & Misses log so the skill learns.
- **Cold-start stall:** the profile lives in iCloud Drive. If it's been evicted, the first read
  blocks for a minute-plus while iCloud materializes it — it looks like a hang but isn't. Warm it
  early (step 1) rather than mid-checkout, and don't kill it and retry.
