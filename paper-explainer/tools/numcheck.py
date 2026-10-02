"""Number normalization helpers (from ~/paper-videos/gpu-course/tools/numcheck.py): spelled-out numbers -> digits, and a
Counter of the numbers in a text, used to diff what was sent to TTS against what a transcriber heard."""

import json
import re
import sys
from collections import Counter
from pathlib import Path

ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}


SCALES = {"hundred": 100, "thousand": 1000, "million": 10**6, "billion": 10**9}
SMALL = {w: i for i, w in enumerate(ONES)}
SMALL.update(TENS)


def words_to_digits(t):
    """Convert spelled-out numbers ("one hundred sixty-three thousand eight hundred forty",
    "a hundred and eighty", "one point five three") to digits; leaves other text alone."""
    toks = re.findall(r"[A-Za-z]+|\d+(?:[.,]\d+)*|[^A-Za-z\d]+", t.replace("-", " "))
    out, i = [], 0
    def is_num(w):
        return w.lower() in SMALL or w.lower() in SCALES
    while i < len(toks):
        w = toks[i]
        if is_num(w) or (w.lower() == "a" and i + 2 < len(toks) and toks[i + 2].lower() in SCALES):
            total, cur, j, last = 0, 0, i, i
            while j < len(toks):
                x = toks[j].lower()
                if x.strip() == "" and j + 1 < len(toks):
                    j += 1
                    continue
                if x in SMALL:
                    cur += SMALL[x]
                elif x == "a" and j + 2 < len(toks) and toks[j + 2].lower() in SCALES:
                    cur += 1
                elif x in SCALES:
                    cur = max(cur, 1) * SCALES[x] if SCALES[x] == 100 else 0 if False else cur
                    if SCALES[x] >= 1000:
                        total += max(cur, 1) * SCALES[x]
                        cur = 0
                elif x == "and" and j + 2 < len(toks) and toks[j + 2].lower() in SMALL:
                    pass
                elif x == "point" and j + 2 < len(toks) and toks[j + 2].lower() in SMALL:
                    k = j + 2
                    digs = ""
                    while k < len(toks) and (toks[k].lower() in ONES[:10] or toks[k].strip() == "" or toks[k].lower() == "oh"):
                        if toks[k].strip():
                            digs += "0" if toks[k].lower() == "oh" else str(ONES.index(toks[k].lower()))
                        k += 1
                    out.append(f"{total + cur}.{digs}")
                    i = k
                    break
                else:
                    break
                last = j
                j += 1
            else:
                pass
            if i > last:
                continue
            out.append(str(total + cur))
            i = last + 1
            continue
        out.append(w)
        i += 1
    return "".join(out).lower()


def nums(t):
    t = words_to_digits(t)
    t = re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)
    return Counter(re.findall(r"\d+(?:\.\d+)?", t))


