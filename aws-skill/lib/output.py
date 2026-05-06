"""Output formatters: json (default), table, markdown, ids.

All service/intent commands produce a list-of-dicts or a single dict, then
hand it here for printing.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, date
from typing import Any, Iterable, Optional

try:
    from tabulate import tabulate
except ImportError:  # pragma: no cover
    tabulate = None  # type: ignore


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, set):
        return sorted(obj)
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return str(obj)


def emit(
    data: Any,
    fmt: str = "json",
    *,
    columns: Optional[list[str]] = None,
    id_key: str = "id",
) -> None:
    """Print `data` in the requested format.

    fmt:
        json     — pretty-printed JSON (default; what Claude expects)
        table    — tabulated rows (terminal-readable)
        markdown — github-flavored markdown table
        ids      — extract one ID per line (good for pipelines)
    """
    fmt = (fmt or "json").lower()

    if fmt == "json":
        print(json.dumps(data, indent=2, default=_json_default, sort_keys=False))
        return

    rows = _normalize_to_rows(data)

    if fmt == "ids":
        for row in rows:
            value = row.get(id_key) or row.get("id") or row.get("Id") or row.get("name")
            if value:
                print(value)
        return

    if not rows:
        if fmt == "markdown":
            print("_(no rows)_")
        else:
            print("(no rows)")
        return

    if columns is None:
        # Use keys from the first row, preserving order.
        columns = list(rows[0].keys())

    table_rows = [[_render_cell(r.get(c)) for c in columns] for r in rows]

    if fmt == "table":
        if tabulate is None:
            # Fallback if tabulate isn't installed yet — fall back to JSON.
            print(json.dumps(rows, indent=2, default=_json_default), file=sys.stderr)
            print(
                "(install `tabulate` for prettier table output: "
                "pip install tabulate)",
                file=sys.stderr,
            )
            return
        print(tabulate(table_rows, headers=columns, tablefmt="psql"))
        return

    if fmt == "markdown":
        if tabulate is None:
            # Hand-roll a tiny markdown table if tabulate isn't there.
            print("| " + " | ".join(columns) + " |")
            print("| " + " | ".join("---" for _ in columns) + " |")
            for row in table_rows:
                print("| " + " | ".join(str(c) for c in row) + " |")
            return
        print(tabulate(table_rows, headers=columns, tablefmt="github"))
        return

    raise ValueError(f"Unknown output format: {fmt}")


def _normalize_to_rows(data: Any) -> list[dict]:
    """Coerce data into a list-of-dicts. Single dicts become one row."""
    if isinstance(data, list):
        return [d if isinstance(d, dict) else {"value": d} for d in data]
    if isinstance(data, dict):
        return [data]
    return [{"value": data}]


def _render_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        # Compact representation for nested dicts
        return json.dumps(value, default=_json_default, separators=(",", ":"))
    return str(value)


def emit_error(message: str, *, exit_code: int = 1) -> None:
    """Print a structured error and exit. Format mirrors other skills' convention."""
    print(json.dumps({"error": message}, indent=2))
    sys.exit(exit_code)
