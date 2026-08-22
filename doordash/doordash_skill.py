#!/usr/bin/env python3
"""
doordash skill — deterministic safety + approval helper for family DoorDash orders.

The *ordering* itself is done by the agent driving the DoorDash CLI (`dd-cli`,
installed at ~/.local/bin, authed as idanbeck@gmail.com): search -> menu ->
cart add-items -> order preview -> order submit. This helper enforces the parts
that must NOT depend on the agent remembering:

  • hard ALLERGY gate  (refuses to order while allergies are unset)
  • allergen scan of the proposed items
  • balanced-health + coverage checks (protein / veg present, ≤1 fried)
  • per-kid coverage (each kid has something they'll eat) + iron for Noa
  • the APPROVAL REPORT (line items, who, subtotal, fees, total, ETA)

Nothing here places an order or touches payment. It validates a proposed order
(prices/ids from `dd-cli menu`, fees/ETA from `dd-cli order preview`) and prints
the report the agent shows Idan; only after Idan approves does the agent run
`dd-cli order submit` (which charges his default card — non-idempotent, run once).

Commands:
    profile                      print the parsed family profile (JSON block)
    check ORDER.json             validate an order + print the approval report
    check -                      (read the order JSON from stdin)
    schema                       print the order-JSON schema/example
"""

import json
import re
import sys
from pathlib import Path

# Canonical profile lives in the Obsidian vault (single source of truth).
PROFILE_MD = (
    Path.home()
    / "Library/Mobile Documents/iCloud~md~obsidian/Documents/idanbeck/Personal/Family Food Profile.md"
)

FRIED_WORDS = ("fried", "tempura", "katsu", "karaage", "crispy", "nugget", "wing")
VEG_WORDS = ("salad", "veg", "edamame", "broccoli", "greens", "cucumber", "spinach",
             "kale", "avocado", "seaweed", "vegetable", "slaw", "asparagus")
PROTEIN_WORDS = ("chicken", "beef", "pork", "fish", "salmon", "tuna", "shrimp", "tofu",
                 "egg", "steak", "lamb", "turkey", "paneer", "bean", "lentil")
# iron-rich + toddler-friendly foods (for Noa, who is iron-deficient). Word-boundary
# matched so "green beans" / "eggplant" don't false-positive as iron.
IRON_REGEX = re.compile(
    r"\b(beef|steak|brisket|lamb|tofu|lentils?|dal|spinach|liver|meatball|congee|"
    r"edamame|pho|eggs?|dark meat|chicken thigh|shredded chicken|black beans?|"
    r"kidney beans?)\b"
)  # \begg\b intentionally does NOT match "eggplant"

UNUSUAL_ITEM_PRICE = 30.0   # flag single items pricier than this
UNUSUAL_TOTAL = 150.0       # flag totals above this (budget is otherwise flexible)


def load_profile() -> dict:
    if not PROFILE_MD.exists():
        sys.exit(f"Profile not found: {PROFILE_MD}\nCreate Personal/Family Food Profile.md first.")
    text = PROFILE_MD.read_text()
    m = re.search(r"## Machine-Readable.*?```json\s*(\{.*?\})\s*```", text, re.S)
    if not m:
        sys.exit("No machine-readable JSON block found in the profile. See `schema`.")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        sys.exit(f"Profile JSON block is malformed: {e}")


def allergen_terms(prof: dict) -> tuple:
    """Return (status, terms).  status: 'unset' | 'none' | 'set'."""
    a = prof.get("allergies", "TODO")
    if isinstance(a, str):
        s = a.strip().lower()
        if s in ("todo", "", "unknown"):
            return "unset", []
        if s in ("none", "none confirmed", "n/a"):
            return "none", []
        # comma/semicolon-separated free text
        terms = [t.strip() for t in re.split(r"[;,]", a) if t.strip()]
        return "set", terms
    if isinstance(a, list):
        if not a:
            return "none", []
        terms = []
        for item in a:
            if isinstance(item, str):
                terms.append(item)
            elif isinstance(item, dict):
                terms.append(str(item.get("allergen", "")))
        return "set", [t for t in terms if t]
    return "unset", []


def tag_item(name: str, tags: list) -> set:
    n = name.lower()
    t = set(x.lower() for x in (tags or []))
    # "fried rice" is stir-fried, not deep-fried — don't count it against the fried cap
    if "fried rice" not in n and any(w in n for w in FRIED_WORDS): t.add("fried")
    if any(w in n for w in VEG_WORDS): t.add("veg")
    if any(w in n for w in PROTEIN_WORDS): t.add("protein")
    return t


def money(x) -> str:
    return f"${x:,.2f}"


def check(order: dict) -> int:
    prof = load_profile()
    people = prof.get("people", {})
    kids = [name for name, p in people.items() if p.get("kid")]
    fails, warns = [], []

    # ---- HARD allergy gate -------------------------------------------------
    status, terms = allergen_terms(prof)
    if status == "unset":
        print("⛔ REFUSING TO ORDER — allergies are not set in the profile.")
        print("   Fill the 'Allergies' field in Personal/Family Food Profile.md")
        print("   (set it to `none` if there are none), then re-run.")
        return 2

    items = order.get("items", [])
    if not items:
        print("⛔ Order has no items."); return 2

    # ---- allergen scan -----------------------------------------------------
    if terms:
        low_terms = [t.lower() for t in terms]
        for it in items:
            nm = it.get("name", "").lower()
            hits = [t for t in low_terms if t and t in nm]
            if hits:
                fails.append(f"ALLERGEN in '{it.get('name')}': matches {hits} — verify or remove.")

    # ---- coverage / balanced-health ---------------------------------------
    all_tags = set()
    fried = 0
    for it in items:
        tg = tag_item(it.get("name", ""), it.get("tags"))
        all_tags |= tg
        if "fried" in tg:
            fried += 1
    if "veg" not in all_tags:
        warns.append("No vegetable/salad detected — balanced mode wants a veg for the table.")
    if "protein" not in all_tags:
        warns.append("No obvious protein detected across the order.")
    if fried > 1:
        warns.append(f"{fried} fried items — balanced mode caps fried at ~1.")

    # ---- noodles/rice base + travels-badly (Idan's rules) ------------------
    names_low = [it.get("name", "").lower() for it in items]
    if prof.get("require_noodles_or_rice"):
        noodle_words = ("noodle", "rice", "chow mein", "chow fun", "lo mein", "udon",
                        "pasta", "vermicelli", "pho", "congee")
        if not any(any(w in n for w in noodle_words) for n in names_low):
            fails.append("No noodles or rice — include a noodle/rice base (Zev's staple + a "
                         "shareable neutral for everyone).")
    seen_bad = set()
    for term in prof.get("avoid_delivery", []):
        t = term.lower()
        for it in items:
            nm = it.get("name", "")
            # one blocker per offending ITEM, not per matching term ("soup dumpling"+"xlb")
            if t in nm.lower() and nm not in seen_bad:
                seen_bad.add(nm)
                fails.append(f"Travels badly: '{nm}' — {term} don't survive "
                             f"delivery (dine-in only). Swap it out.")

    # ---- spicy is parents-only (kids + Noa can't handle it) ---------------
    if prof.get("kids_no_spicy"):
        spicy_words = ("spicy", "chili", "chilli", "mala", "mapo", "kung pao", "hot pepper",
                       "jalapeno", "szechuan pepper", "sichuan pepper")
        # negation cues that mean the dish is explicitly mild ("no chili", "not spicy", "mild")
        mild_cues = ("no chili", "no chilli", "not spicy", "non-spicy", "non spicy",
                     "no spice", "without chili", "without spice", "mild")
        no_spice = set(kids) | {"Noa"}
        for it in items:
            nm = it.get("name", "").lower()
            if any(c in nm for c in mild_cues):
                continue  # explicitly marked mild — trust it
            if any(w in nm for w in spicy_words):
                served_kids = [w for w in it.get("for", []) if w in no_spice]
                if served_kids:
                    fails.append(f"SPICY '{it.get('name')}' is assigned to {served_kids} — "
                                 f"spicy is parents-only; give the kids a mild dish instead.")

    # ---- unverifiable spice on a kid's dish --------------------------------
    # 2026-08-14: "Cashew Chicken" and "Mixed Vegetable with Thai Basil" both
    # arrived SPICY. Neither name contains a spice word, so the scan above
    # passed them. A dish name does not tell you the spice level — so flag any
    # kid-assigned dish that isn't structurally plain.
    if prof.get("kids_no_spicy"):
        plain_words = ("plain", "steamed", "boiled", "white rice", "jasmine rice", "brown rice",
                       "satay", "skewer", "teriyaki", "nugget", "fries", "edamame",
                       "cucumber", "california roll", "rice")
        # NOTE: "noodle" is deliberately NOT here — pad thai / drunken noodles /
        # pad ke mao are noodle dishes that arrive spicy.
        # a "table" dish is shared — it reaches the kids too (the 2026-08-14 spicy
        # Mixed Vegetable was labelled table-only and still landed in front of them)
        no_spice = set(kids) | {"Noa", "table"}
        for it in items:
            nm = it.get("name", "")
            served = [w for w in it.get("for", []) if w in no_spice]
            if served and not any(p in nm.lower() for p in plain_words):
                warns.append(
                    f"SPICE UNVERIFIED: '{nm}' is assigned to {served} but isn't a plainly-mild "
                    f"dish. A name without a spice word does NOT mean mild (burned us 2026-08-14). "
                    f"Request mild explicitly, or keep this one parents-only."
                )

    # ---- per-person no-gos / soft avoids -----------------------------------
    # `no_gos` are hard (blocker); `avoid_soft` are preferences we default away
    # from but Idan can knowingly override (note). Matched on the item name, so
    # only concrete food words work ("beef"); abstract ones ("adventurous") no-op.
    for it in items:
        nm = it.get("name", "")
        nl = nm.lower()
        for who in it.get("for", []):
            pers = people.get(who)
            if not pers:
                continue
            for term in pers.get("no_gos", []) or []:
                t = str(term).strip().lower()
                if t and t in nl:
                    fails.append(f"NO-GO: '{nm}' is assigned to {who}, who doesn't eat "
                                 f"'{term}'. Reassign it or pick a different protein.")
            for term in pers.get("avoid_soft", []) or []:
                t = str(term).strip().lower()
                if t and t in nl:
                    pref = pers.get("protein_preference") or []
                    alt = (" Prefer " + " → ".join(pref) + ".") if pref else ""
                    warns.append(f"AVOIDING: '{nm}' is assigned to {who}, who is trying to "
                                 f"avoid '{term}'.{alt}")

    # ---- per-kid coverage --------------------------------------------------
    covered = set()
    for it in items:
        for who in it.get("for", []):
            covered.add(who)
    for kid in kids:
        if kid not in covered:  # a shared "table" dish doesn't count — kids need their own
            fails.append(
                f"No item assigned to {kid} — assign them something they'll actually eat "
                f"(esp. Zev, who's picky about plain food)."
            )
    noa = people.get("Noa", {})
    if noa:
        warns.append("Noa (toddler) eats from the table — confirm a soft, no-choking-hazard option exists.")
        if noa.get("iron_priority"):
            has_iron = any(IRON_REGEX.search(it.get("name", "").lower()) for it in items)
            if not has_iron:
                fails.append(
                    "IRON: no iron-rich item for Noa (she's iron-deficient — top priority). "
                    "Add soft beef / dark-meat chicken / tofu / lentils / spinach, ideally "
                    "with a vitamin-C side."
                )

    # ---- cost --------------------------------------------------------------
    subtotal = sum(float(it.get("price", 0)) * int(it.get("qty", 1)) for it in items)
    fees = order.get("fees", {}) or {}
    fee_total = sum(float(v) for v in fees.values())
    total = subtotal + fee_total
    for it in items:
        if float(it.get("price", 0)) > UNUSUAL_ITEM_PRICE:
            warns.append(f"Pricey item: '{it.get('name')}' at {money(it['price'])} (flagging, not blocking).")
    if total > UNUSUAL_TOTAL:
        warns.append(f"Total {money(total)} is on the high side — flagging (budget is flexible).")

    # ---- APPROVAL REPORT ---------------------------------------------------
    print("=" * 60)
    print(f"  APPROVAL REPORT — {order.get('restaurant', '(restaurant?)')}")
    print("=" * 60)
    print(f"  Deliver to: {prof.get('address', '?')}")
    eta = order.get("eta_minutes")
    print(f"  ETA: ~{eta} min" if eta else "  ETA: (read from cart)")
    print("  " + "-" * 56)
    for it in items:
        who = ", ".join(it.get("for", [])) or "table"
        line = float(it.get("price", 0)) * int(it.get("qty", 1))
        q = f"{it.get('qty',1)}× " if int(it.get('qty', 1)) > 1 else ""
        label = f"{q}{it.get('name')}"          # pad the WHOLE label so the qty prefix
        print(f"    {label:<34} {money(line):>9}   ({who})")   # doesn't shift the money column
    print("  " + "-" * 56)
    print(f"    {'Subtotal':<34} {money(subtotal):>9}")
    for k in ("delivery", "service", "tax", "tip"):
        if k in fees:
            print(f"    {k.capitalize():<34} {money(float(fees[k])):>9}")
    print(f"    {'TOTAL':<34} {money(total):>9}")
    print("=" * 60)

    status_terms = "none" if status == "none" else ", ".join(terms)
    print(f"  Allergies on file: {status_terms}")
    if fails:
        print("\n  ⛔ BLOCKERS (fix before ordering):")
        for f in fails:
            print(f"     • {f}")
    if warns:
        print("\n  ⚠️  Notes:")
        for w in warns:
            print(f"     • {w}")
    print()
    if fails:
        print("  → Not safe to order as-is. Resolve blockers above.")
        return 1
    print("  → Ready. Ask Idan to APPROVE this exact order + total before placing.")
    print("     Do NOT place the order or pay without explicit approval.")
    return 0


SCHEMA_EXAMPLE = {
    "restaurant": "Sushi Koya",
    "eta_minutes": 40,
    "items": [
        {"name": "Chicken Teriyaki Bowl", "for": ["Idan"], "price": 15.95, "qty": 1,
         "tags": ["protein"]},
        {"name": "Salmon Nigiri (from cart)", "for": ["Stacey"], "price": 8.50, "qty": 1,
         "tags": ["protein"]},
        {"name": "Edamame", "for": ["table"], "price": 5.50, "qty": 1, "tags": ["veg"]},
        {"name": "Cucumber Roll", "for": ["Sara", "Noa"], "price": 4.95, "qty": 1,
         "tags": ["veg"]},
        {"name": "Steamed Rice + shredded chicken", "for": ["Zev", "Noa"], "price": 4.00,
         "qty": 1, "tags": ["starch", "protein"]},
    ],
    "fees": {"delivery": 3.99, "service": 4.20, "tax": 3.10, "tip": 8.00},
}


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__); return
    cmd = args[0]
    if cmd == "profile":
        print(json.dumps(load_profile(), indent=2))
    elif cmd == "schema":
        print(json.dumps(SCHEMA_EXAMPLE, indent=2))
    elif cmd == "check":
        src = args[1] if len(args) > 1 else "-"
        raw = sys.stdin.read() if src == "-" else Path(src).read_text()
        try:
            order = json.loads(raw)
        except json.JSONDecodeError as e:
            sys.exit(f"Order JSON is malformed: {e}")
        sys.exit(check(order))
    else:
        sys.exit(f"unknown command: {cmd}\n{__doc__}")


if __name__ == "__main__":
    main()
