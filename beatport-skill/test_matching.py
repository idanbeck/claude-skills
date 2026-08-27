#!/usr/bin/env python3
"""Regression tests for the parts of beatport-skill that must not silently drift:
Camelot key mapping and the Spotify->Beatport track matcher.

Run: python3 ~/.claude/skills/beatport-skill/test_matching.py
No network, no credentials, stdlib only.
"""
import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("bp", Path(__file__).parent / "beatport_skill.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

TH = 0.72
failures = []


def check(cond, label):
    if not cond:
        failures.append(label)
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}")


print("Camelot wheel")
codes = set()
for (root, mode), code in m._CAMELOT.items():
    got = m.to_camelot(f"{root.capitalize()} {mode}")
    check(got == code, f"{root} {mode} -> {code} (got {got})")
    codes.add(code)
check(len(codes) == 24, "all 24 Camelot codes are distinct")
check(m.to_camelot("C# Minor") == "12A", "enharmonic C# minor == Db minor == 12A")
check(m.to_camelot("G# min") == "1A", "abbreviated 'min' + sharp spelling")
check(m.to_camelot("A#  Minor") == "3A", "extra whitespace")
check(m.to_camelot("Gb Major") == "2B", "Gb major == F# major == 2B")
check(m.to_camelot("C#/Db Minor") == "12A", "Beatport slash spelling")
check(m.to_camelot("A♭ Minor") == "1A", "unicode flat sign")
check(m.to_camelot("garbage") is None, "unparseable key returns None")
check(m.to_camelot(None) is None, "None key returns None")
check(m.to_camelot("A Minor")[:-1] == m.to_camelot("C Major")[:-1],
      "relative major/minor share a Camelot number")
check(m.camelot_neighbors("8A") == ["8A", "9A", "7A", "8B"], "neighbours of 8A")
check(m.camelot_neighbors("12A") == ["12A", "1A", "11A", "12B"], "wraparound 12 -> 1")
check(m.camelot_neighbors("1B") == ["1B", "2B", "12B", "1A"], "wraparound 1 -> 12")
check(m.camelot_neighbors(None) == [], "no key, no neighbours")

print("\nTrack matcher (threshold %.2f)" % TH)
CASES = [
    (dict(artist="Bicep", title="Glue", mix="", duration_ms=330000),
     dict(artist="Bicep", title="Glue", mix="Original Mix", remixers=[], length_ms=331000),
     True, "original -> original"),
    (dict(artist="Bicep", title="Glue", mix="Original Mix", duration_ms=330000),
     dict(artist="Bicep", title="Glue", mix="Chaos In The CBD Remix",
          remixers=["Chaos In The CBD"], length_ms=420000),
     False, "WRONG remix when original was asked for"),
    (dict(artist="Bicep", title="Glue", mix="", duration_ms=330000),
     dict(artist="Bicep", title="Glue", mix="Chaos In The CBD Remix",
          remixers=["Chaos In The CBD"], length_ms=340000),
     False, "unrequested remix does not auto-match"),
    (dict(artist="Bicep", title="Glue - Chaos In The CBD Remix", mix="", duration_ms=420000),
     dict(artist="Bicep", title="Glue", mix="Chaos In The CBD Remix",
          remixers=["Chaos In The CBD"], length_ms=421000),
     True, "correct remix, dash form in title"),
    (dict(artist="Kolsch", title="Grey", mix="", duration_ms=400000),
     dict(artist="Kolsch", title="Grey", mix="Tale Of Us Remix",
          remixers=["Tale Of Us"], length_ms=410000),
     False, "remix not asked for"),
    (dict(artist="Kolsch", title="Grey (Tale Of Us Remix)", mix="", duration_ms=400000),
     dict(artist="Kolsch", title="Grey", mix="Tale Of Us Remix",
          remixers=["Tale Of Us"], length_ms=410000),
     True, "correct remix, parenthesised in title"),
    (dict(artist="ANOTR", title="Relax My Eyes", mix="", duration_ms=300000),
     dict(artist="ANOTR", title="Relax My Eyes", mix="Extended Mix",
          remixers=[], length_ms=360000),
     True, "extended mix is the same track"),
    (dict(artist="Fred again..", title="Delilah (pull me out of this)", mix="",
          duration_ms=230000),
     dict(artist="Fred again..", title="Delilah", mix="Original Mix",
          remixers=[], length_ms=232000),
     True, "parenthesised subtitle is not a remix"),
    (dict(artist="Bjork", title="Hyperballad", mix="", duration_ms=300000),
     dict(artist="Björk", title="Hyperballad", mix="Original Mix",
          remixers=[], length_ms=301000),
     True, "accented artist name"),
    (dict(artist="Chris Stussy", title="Movin", mix="", duration_ms=380000),
     dict(artist="Chris Stussy", title="Movin'", mix="Original Mix",
          remixers=[], length_ms=381000),
     True, "apostrophe difference"),
    (dict(artist="Kaytranada feat. Anderson .Paak", title="Twin Flame", mix="",
          duration_ms=200000),
     dict(artist="Kaytranada", title="Twin Flame", mix="Original Mix",
          remixers=[], length_ms=201000),
     True, "feat. credit stripped"),
    (dict(artist="Bicep", title="Glue", mix="", duration_ms=330000),
     dict(artist="Disclosure", title="Latch", mix="Original Mix",
          remixers=[], length_ms=250000),
     False, "completely unrelated track"),
    (dict(artist="Four Tet", title="Baby", mix="", duration_ms=300000),
     dict(artist="Justin Bieber", title="Baby", mix="Original Mix",
          remixers=[], length_ms=214000),
     False, "same title, wrong artist"),
]
for crate, bp, expected, label in CASES:
    s = m.score_match(crate, bp)
    check((s >= TH) == expected, f"{label}  (score {s:.3f})")

print("\nHarmonic ordering")
rows = [{"bpm": 128, "camelot": "8A", "t": "a"}, {"bpm": 126, "camelot": "8B", "t": "b"},
        {"bpm": 130, "camelot": "9A", "t": "c"}, {"bpm": 140, "camelot": "6A", "t": "d"}]
order = m.harmonic_order(rows)
check([r["t"] for r in order] == ["b", "a", "c", "d"], "greedy walk starts slowest, stays harmonic")
check(m.harmonic_order([]) == [], "empty input")
check(m.harmonic_order([{"bpm": None, "camelot": None}]) == [], "rows without bpm/key are dropped")

print()
if failures:
    print(f"{len(failures)} FAILURE(S):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("All checks passed.")
