"""Subprocess helpers for shelling out to sibling skills (gmail, playwright)."""
import json
import subprocess


def run(args, timeout=180, input_text=None):
    return subprocess.run([str(a) for a in args], capture_output=True, text=True,
                          timeout=timeout, input=input_text)


def run_json(args, timeout=180):
    """Run a command and parse the first JSON object/array from stdout.
    Sibling skills sometimes print a warning line before the JSON."""
    r = run(args, timeout=timeout)
    out = r.stdout or ""
    obj_i, obj_j = out.find("{"), out.rfind("}")
    arr_i, arr_j = out.find("["), out.rfind("]")
    candidates = []
    if obj_i != -1 and obj_j != -1:
        candidates.append((obj_i, out[obj_i:obj_j + 1]))
    if arr_i != -1 and arr_j != -1:
        candidates.append((arr_i, out[arr_i:arr_j + 1]))
    candidates.sort()  # take whichever appears first
    for _, blob in candidates:
        try:
            return json.loads(blob)
        except json.JSONDecodeError:
            continue
    return None
