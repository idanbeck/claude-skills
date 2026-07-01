"""Model invocation via `claude -p` (house pattern, copied from scansnap-bridge)."""
import json
import re
import subprocess
import sys
from datetime import datetime

from . import config


def log(msg, level="INFO"):
    print(f"[lr.claude {level}] {msg}", file=sys.stderr)


def _call_claude(prompt: str) -> str:
    """Raw claude -p call; prompt piped via stdin. Returns stdout ('' on error)."""
    try:
        result = subprocess.run(
            [config.CLAUDE_BIN, "-p", "--dangerously-skip-permissions"],
            input=prompt, capture_output=True, text=True,
            timeout=config.CLAUDE_TIMEOUT_S,
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        log("claude subprocess timed out", "ERROR")
        return ""
    except FileNotFoundError:
        log(f"claude binary not found at {config.CLAUDE_BIN}", "ERROR")
        return ""


def _parse_json_from_output(output: str):
    """Locate + parse a JSON object in free-form output. Returns (dict|None, str, err)."""
    output = (output or "").strip()
    output = re.sub(r"^```(?:json)?\s*", "", output)
    output = re.sub(r"\s*```$", "", output)
    output = re.sub(r"<thinking>.*?</thinking>\s*", "", output, flags=re.DOTALL)
    first, last = output.find("{"), output.rfind("}")
    if first == -1 or last == -1:
        return None, "", "no JSON object in output"
    js = output[first:last + 1]
    try:
        return json.loads(js), js, ""
    except json.JSONDecodeError as e:
        return None, js, str(e)


def _dump_debug(label, content):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    p = config.EVIDENCE_DIR / f"debug_{label}_{ts}.txt"
    p.write_text(content)
    return p


def call_json(prompt: str):
    """Run claude -p, parse JSON, retry once with a corrective reprompt on failure."""
    out = _call_claude(prompt)
    if not out:
        return None
    parsed, js, err = _parse_json_from_output(out)
    if parsed is not None:
        return parsed
    dbg = _dump_debug("attempt1", out)
    log(f"JSON parse failed ({err}); saved {dbg}", "WARN")
    retry = (
        "Your previous response failed to parse as JSON with this error:\n"
        f"  {err}\n\nHere was your (broken) output:\n```\n{js[:10000]}\n```\n\n"
        "Return the SAME content as STRICT valid JSON. Rules:\n"
        '  - Escape double quotes inside strings as \\"\n'
        "  - Escape backslashes as \\\\ and newlines as \\n\n"
        "  - No markdown fences. Emit ONLY the JSON object."
    )
    out2 = _call_claude(retry)
    parsed2, _, err2 = _parse_json_from_output(out2)
    if parsed2 is not None:
        log("retry succeeded", "INFO")
        return parsed2
    _dump_debug("attempt2", out2 or "")
    log(f"JSON parse failed again ({err2})", "ERROR")
    return None
