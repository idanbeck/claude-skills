"""Write/delete safety guardrails.

Convention:
    - reads are free
    - writes (start/stop/put/provision/associate-eip/...) require --confirm
    - deletes (terminate/teardown/rm/delete/...) require --confirm-delete
        (separate flag, intentionally — prevents `--confirm` muscle-memory
        from green-lighting destructive ops by accident)
"""
from __future__ import annotations

import sys
from typing import Optional


class ConfirmationRequired(RuntimeError):
    """Raised when an operation needs --confirm or --confirm-delete and didn't get it."""


def require_confirm(args, op: str) -> None:
    """For mutating ops that aren't deletes."""
    if not getattr(args, "confirm", False):
        raise ConfirmationRequired(
            f"Operation '{op}' is a write and requires --confirm. "
            f"Re-run with --confirm to execute, or --dry-run to see the plan."
        )


def require_confirm_delete(args, op: str) -> None:
    """For destructive ops. Stricter than --confirm."""
    if not getattr(args, "confirm_delete", False):
        raise ConfirmationRequired(
            f"Operation '{op}' is destructive and requires --confirm-delete. "
            f"This is intentionally a different flag from --confirm. "
            f"Re-run with --confirm-delete to execute, or --dry-run to preview."
        )


def is_dry_run(args) -> bool:
    return bool(getattr(args, "dry_run", False))
