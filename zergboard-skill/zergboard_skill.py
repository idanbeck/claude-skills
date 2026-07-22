#!/usr/bin/env python3
"""
Zergboard Skill — Read and manage Zergboard cards, boards, and workspaces
via the REST API with bearer-token authentication.

Usage:
    python zergboard_skill.py my-cards [--status STATUS] [--limit N]
    python zergboard_skill.py workspaces
    python zergboard_skill.py boards [WORKSPACE]
    python zergboard_skill.py cards BOARD [--status STATUS] [--priority P] [--limit N]
    python zergboard_skill.py card CARD_ID
    python zergboard_skill.py cycle BOARD
    python zergboard_skill.py cycles BOARD [--limit N]
    python zergboard_skill.py search "query" [--workspace WS] [--board BOARD] [--limit N]
    python zergboard_skill.py create BOARD --title "..." [--description "..."] [--priority P] [--column NAME] [--assignee EMAIL]
    python zergboard_skill.py update CARD_ID [--title "..."] [--description "..."] [--priority P] [--due YYYY-MM-DD] [--estimate N]
    python zergboard_skill.py move CARD_ID --column NAME [--position N]
    python zergboard_skill.py reorder ID1 ID2 ID3 ...
    python zergboard_skill.py comments CARD_ID
    python zergboard_skill.py comment CARD_ID --body "..."
    python zergboard_skill.py invite-guest BOARD --email EMAIL [--role ROLE]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SKILL_DIR = Path(__file__).parent
CONFIG_FILE = SKILL_DIR / "config.json"
DEFAULT_BASE_URL = "https://zergboard.fly.dev"


# ---------- Config & HTTP ----------


def load_config() -> Dict[str, Any]:
    if not CONFIG_FILE.exists():
        emit({
            "error": "No config file found",
            "setup_required": True,
            "instructions": [
                "1. Create an API token in Zergboard (settings or via the zb CLI).",
                "2. Save it to config:",
                f"   cat > {CONFIG_FILE} <<EOF",
                "   {\"base_url\": \"https://zergboard.fly.dev\", \"api_token\": \"zb_..._...\"}",
                "   EOF",
            ],
        })
        sys.exit(1)
    with open(CONFIG_FILE) as f:
        return json.load(f)


def emit(payload: Any) -> None:
    print(json.dumps(payload, indent=2, default=str))


def request(method: str, path: str, *, query: Optional[Dict[str, Any]] = None, body: Optional[Dict[str, Any]] = None, extra_headers: Optional[Dict[str, str]] = None) -> Any:
    cfg = load_config()
    token = cfg.get("api_token")
    base = (cfg.get("base_url") or DEFAULT_BASE_URL).rstrip("/")
    if not token:
        emit({"error": "config.json is missing api_token"})
        sys.exit(1)

    url = base + path
    if query:
        cleaned = {k: v for k, v in query.items() if v is not None}
        if cleaned:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(cleaned)

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    data: Optional[bytes] = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(url, method=method.upper(), headers=headers, data=data)
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.fp.read().decode("utf-8", errors="replace") if e.fp else str(e)
        try:
            parsed = json.loads(body_text)
        except json.JSONDecodeError:
            parsed = {"raw": body_text}
        emit({"error": f"HTTP {e.code}", "url": url, "method": method.upper(), "response": parsed})
        sys.exit(2)
    except urllib.error.URLError as e:
        emit({"error": f"Network error: {e.reason}", "url": url})
        sys.exit(2)


# ---------- Resolvers ----------


UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
EXTERNAL_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*-\d+$")


def is_uuid(s: str) -> bool:
    return bool(UUID_RE.match(s))


def resolve_workspace(identifier: Optional[str]) -> Dict[str, Any]:
    """Resolve a workspace by name, slug, or UUID. None falls back to default_organization_id."""
    cfg = load_config()
    if not identifier:
        identifier = cfg.get("default_organization_id")
    data = request("GET", "/api/orgs")
    orgs: List[Dict[str, Any]] = data.get("organizations", [])
    if not identifier:
        if len(orgs) == 1:
            return orgs[0]
        emit({"error": "No workspace specified and multiple available — pass WORKSPACE or set default_organization_id", "workspaces": [{"id": o["id"], "name": o["name"]} for o in orgs]})
        sys.exit(1)
    if is_uuid(identifier):
        match = next((o for o in orgs if o["id"] == identifier), None)
    else:
        ident_lower = identifier.lower()
        match = next((o for o in orgs if o["name"].lower() == ident_lower or o.get("slug", "").lower() == ident_lower), None)
    if not match:
        emit({"error": f"Workspace not found: {identifier}", "available": [o["name"] for o in orgs]})
        sys.exit(1)
    return match


def resolve_board(identifier: str, workspace: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Resolve a board by UUID, exact name, or card prefix."""
    if is_uuid(identifier):
        data = request("GET", f"/api/boards/{identifier}")
        return data["board"]

    if workspace is None:
        # Search across every workspace.
        orgs = request("GET", "/api/orgs").get("organizations", [])
        for org in orgs:
            try:
                board = _find_board_in_org(identifier, org["id"])
                if board:
                    return board
            except SystemExit:
                continue
        emit({"error": f"Board not found in any workspace: {identifier}"})
        sys.exit(1)
    board = _find_board_in_org(identifier, workspace["id"])
    if not board:
        emit({"error": f"Board not found in workspace {workspace['name']}: {identifier}"})
        sys.exit(1)
    return board


def _find_board_in_org(identifier: str, org_id: str) -> Optional[Dict[str, Any]]:
    data = request("GET", "/api/boards", query={"orgId": org_id})
    boards: List[Dict[str, Any]] = data.get("boards", [])
    ident_lower = identifier.lower()
    for b in boards:
        if b["name"].lower() == ident_lower:
            return b
    # Fallback: card prefix
    for b in boards:
        if str(b.get("card_prefix", "")).lower() == ident_lower:
            return b
    # Substring fallback
    for b in boards:
        if ident_lower in b["name"].lower():
            return b
    return None


def resolve_card(identifier: str) -> Dict[str, Any]:
    """Resolve a card by UUID or external_id (CES-1 etc.)."""
    if is_uuid(identifier):
        data = request("GET", f"/api/cards/{identifier}")
        return data.get("card", data)
    if EXTERNAL_ID_RE.match(identifier):
        data = request("GET", "/api/search/cards", query={"q": identifier, "limit": 50})
        cards = [c for c in data.get("cards", []) if (c.get("external_id") or "").upper() == identifier.upper()]
        if not cards:
            emit({"error": f"No card with external id {identifier}"})
            sys.exit(1)
        return _full_card(cards[0]["id"])
    emit({"error": f"Card identifier not recognized: {identifier} (expected UUID or e.g. CES-1)"})
    sys.exit(1)


def _if_match(card: Dict[str, Any]) -> Dict[str, str]:
    rev = card.get("revision")
    return {"If-Match": str(rev)} if rev is not None else {}


def _full_card(card_id: str) -> Dict[str, Any]:
    data = request("GET", f"/api/cards/{card_id}")
    return data.get("card", data)


def fetch_board_full(board_id: str) -> Dict[str, Any]:
    return request("GET", f"/api/boards/{board_id}")


def column_id_by_name(board_full: Dict[str, Any], column_name: str) -> Optional[str]:
    for c in board_full.get("columns", []):
        if c["name"].lower() == column_name.lower():
            return c["id"]
    return None


# ---------- Formatting ----------


def format_card(card: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": card.get("id"),
        "external_id": card.get("external_id"),
        "title": card.get("title"),
        "priority": card.get("priority"),
        "status": card.get("status"),
        "state_kind": card.get("state_kind"),
        "state_name": card.get("state_name"),
        "column_name": card.get("column_name"),
        "board_id": card.get("board_id"),
        "board_name": card.get("board_name"),
        "board_card_prefix": card.get("board_card_prefix"),
        "organization_id": card.get("organization_id"),
        "organization_name": card.get("organization_name"),
        "due_at": card.get("due_at"),
        "estimate_points": card.get("estimate_points"),
    }


def format_board_card(card: Dict[str, Any], columns: List[Dict[str, Any]], states: List[Dict[str, Any]]) -> Dict[str, Any]:
    column = next((c for c in columns if c["id"] == card.get("column_id")), None)
    state = next((s for s in states if s.get("id") == card.get("state_id")), None) if card.get("state_id") else None
    return {
        "id": card["id"],
        "external_id": card.get("external_id"),
        "title": card["title"],
        "priority": card.get("priority"),
        "status": card.get("status"),
        "state_kind": state.get("kind") if state else None,
        "state_name": state.get("name") if state else None,
        "column_name": column["name"] if column else None,
        "position": card.get("position"),
        "due_at": card.get("due_at"),
        "estimate_points": card.get("estimate_points"),
    }


# ---------- Commands ----------


def cmd_my_cards(args: argparse.Namespace) -> None:
    data = request("GET", "/api/me/cards", query={"status": args.status, "limit": args.limit})
    emit({"cards": [format_card(c) for c in data.get("cards", [])]})


def cmd_workspaces(_args: argparse.Namespace) -> None:
    data = request("GET", "/api/orgs")
    emit({"workspaces": data.get("organizations", [])})


def cmd_boards(args: argparse.Namespace) -> None:
    workspace = resolve_workspace(args.workspace)
    data = request("GET", "/api/boards", query={"orgId": workspace["id"]})
    emit({
        "workspace": {"id": workspace["id"], "name": workspace["name"]},
        "boards": data.get("boards", [])
    })


def cmd_cards(args: argparse.Namespace) -> None:
    board = resolve_board(args.board)
    full = fetch_board_full(board["id"])
    cards = full.get("cards", [])
    columns = full.get("columns", [])
    states = full.get("states", [])

    formatted = [format_board_card(c, columns, states) for c in cards]
    if args.status:
        formatted = [c for c in formatted if c["state_kind"] == args.status]
    if args.priority:
        formatted = [c for c in formatted if c["priority"] == args.priority]
    formatted = formatted[: args.limit]
    emit({
        "board": {"id": board["id"], "name": board["name"]},
        "cards": formatted,
    })


def cmd_card(args: argparse.Namespace) -> None:
    card = resolve_card(args.card)
    emit({"card": card})


def cmd_cycle(args: argparse.Namespace) -> None:
    board = resolve_board(args.board)
    full = fetch_board_full(board["id"])
    active = [c for c in full.get("cycles", []) if c.get("status") == "active"]
    emit({
        "board": {"id": board["id"], "name": board["name"]},
        "active_cycles": active,
    })


def cmd_cycles(args: argparse.Namespace) -> None:
    board = resolve_board(args.board)
    full = fetch_board_full(board["id"])
    cycles = full.get("cycles", [])[: args.limit]
    emit({
        "board": {"id": board["id"], "name": board["name"]},
        "cycles": cycles,
    })


def cmd_search(args: argparse.Namespace) -> None:
    workspace_id = None
    if args.workspace:
        workspace_id = resolve_workspace(args.workspace)["id"]
    board_id = None
    if args.board:
        board_id = resolve_board(args.board)["id"]
    data = request("GET", "/api/search/cards", query={
        "q": args.query,
        "limit": args.limit,
        "organization_id": workspace_id,
        "board_id": board_id,
    })
    emit({"cards": [format_card(c) for c in data.get("cards", [])]})


def cmd_create(args: argparse.Namespace) -> None:
    board = resolve_board(args.board)
    full = fetch_board_full(board["id"])
    columns = full.get("columns", [])
    if not columns:
        emit({"error": "Board has no columns"})
        sys.exit(1)
    column_id: Optional[str] = None
    if args.column:
        column_id = column_id_by_name(full, args.column)
        if not column_id:
            emit({"error": f"Column not found on board {board['name']}: {args.column}", "available": [c["name"] for c in columns]})
            sys.exit(1)
    else:
        column_id = columns[0]["id"]

    body: Dict[str, Any] = {
        "boardId": board["id"],
        "columnId": column_id,
        "title": args.title,
    }
    if args.description:
        body["description"] = args.description
    if args.priority:
        body["priority"] = args.priority
    if args.assignee:
        members = full.get("members", [])
        assignee = next((m for m in members if m["email"].lower() == args.assignee.lower()), None)
        if not assignee:
            emit({"error": f"Assignee email not on this board: {args.assignee}"})
            sys.exit(1)
        body["assigneeUserIds"] = [assignee["user_id"]]

    data = request("POST", "/api/cards", body=body)
    emit({"card": data.get("card", data)})


def cmd_update(args: argparse.Namespace) -> None:
    card = resolve_card(args.card)
    body: Dict[str, Any] = {}
    if args.title is not None: body["title"] = args.title
    if args.description is not None: body["description"] = args.description
    if args.priority is not None: body["priority"] = args.priority
    if args.estimate is not None: body["estimatePoints"] = args.estimate
    if args.due is not None:
        # Accept YYYY-MM-DD; promote to ISO 09:00.
        if re.match(r"^\d{4}-\d{2}-\d{2}$", args.due):
            body["dueAt"] = f"{args.due}T09:00:00.000Z"
        else:
            body["dueAt"] = args.due
    if not body:
        emit({"error": "Nothing to update — pass at least one of --title/--description/--priority/--due/--estimate"})
        sys.exit(1)
    data = request("PATCH", f"/api/cards/{card['id']}", body=body, extra_headers=_if_match(card))
    emit({"card": data.get("card", data)})


def cmd_move(args: argparse.Namespace) -> None:
    card = resolve_card(args.card)
    full = fetch_board_full(card["board_id"])
    target_col = column_id_by_name(full, args.column)
    if not target_col:
        emit({"error": f"Column not found: {args.column}", "available": [c["name"] for c in full.get("columns", [])]})
        sys.exit(1)
    body = {"targetColumnId": target_col, "targetPosition": args.position if args.position is not None else 0}
    data = request("POST", f"/api/cards/{card['id']}/move", body=body, extra_headers=_if_match(card))
    emit({"card": data})


def cmd_reorder(args: argparse.Namespace) -> None:
    if len(args.cards) < 2:
        emit({"error": "Pass at least 2 card ids in the desired top-to-bottom order"})
        sys.exit(1)
    cards = [resolve_card(c) for c in args.cards]
    column_ids = {c["column_id"] for c in cards}
    if len(column_ids) > 1:
        emit({"error": "Cards must all be in the same column to reorder", "columns": list(column_ids)})
        sys.exit(1)
    target_column = next(iter(column_ids))
    # Use the `move` endpoint with the same column id + a numeric target
    # position. The `position` endpoint only supports relative
    # actions (top/bottom/up/down) so isn't the right tool for an N-way
    # ordering.
    for index, card in enumerate(cards):
        request("POST", f"/api/cards/{card['id']}/move", body={
            "targetColumnId": target_column,
            "targetPosition": index
        }, extra_headers=_if_match(_full_card(card['id'])))
    emit({"reordered": [{"id": c["id"], "external_id": c.get("external_id"), "position": i} for i, c in enumerate(cards)]})


def cmd_comments(args: argparse.Namespace) -> None:
    card = resolve_card(args.card)
    data = request("GET", f"/api/cards/{card['id']}/comments")
    emit({"comments": data.get("comments", [])})


def cmd_comment(args: argparse.Namespace) -> None:
    card = resolve_card(args.card)
    data = request("POST", f"/api/cards/{card['id']}/comments", body={"body": args.body})
    emit({"comment": data.get("comment", data)})


def cmd_invite_guest(args: argparse.Namespace) -> None:
    board = resolve_board(args.board)
    data = request("POST", f"/api/boards/{board['id']}/guests", body={"email": args.email, "role": args.role})
    emit(data)


def cmd_delete_card(args: argparse.Namespace) -> None:
    card = resolve_card(args.card)
    request("DELETE", f"/api/cards/{card['id']}")
    emit({"ok": True, "deleted": {"id": card["id"], "external_id": card.get("external_id")}})


def cmd_attach(args: argparse.Namespace) -> None:
    import base64
    import mimetypes
    import os
    card = resolve_card(args.card)
    if not os.path.isfile(args.path):
        emit({"error": f"File not found: {args.path}"})
        sys.exit(1)
    with open(args.path, "rb") as f:
        raw = f.read()
    if len(raw) > 5 * 1024 * 1024:
        emit({"error": f"File is {len(raw)} bytes; the server cap is 5MB."})
        sys.exit(1)
    filename = args.filename or os.path.basename(args.path)
    mime = args.mime or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    body = {
        "filename": filename,
        "mime_type": mime,
        "data": base64.b64encode(raw).decode("ascii"),
    }
    data = request("POST", f"/api/cards/{card['id']}/attachments", body=body)
    emit(data)


def cmd_attachments(args: argparse.Namespace) -> None:
    card = resolve_card(args.card)
    data = request("GET", f"/api/cards/{card['id']}/attachments")
    emit(data)


def cmd_create_board(args: argparse.Namespace) -> None:
    workspace = resolve_workspace(args.workspace)
    body: Dict[str, Any] = {
        "organizationId": workspace["id"],
        "name": args.name,
    }
    if args.description:
        body["description"] = args.description
    if args.columns:
        body["columns"] = args.columns
    data = request("POST", "/api/boards", body=body)
    emit(data)


# ---------- Argparse ----------


def main() -> None:
    p = argparse.ArgumentParser(prog="zergboard_skill", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("my-cards")
    s.add_argument("--status", choices=["todo", "in_progress", "done", "canceled"])
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(func=cmd_my_cards)

    s = sub.add_parser("workspaces")
    s.set_defaults(func=cmd_workspaces)

    s = sub.add_parser("boards")
    s.add_argument("workspace", nargs="?")
    s.set_defaults(func=cmd_boards)

    s = sub.add_parser("cards")
    s.add_argument("board")
    s.add_argument("--status", choices=["todo", "in_progress", "done", "canceled"])
    s.add_argument("--priority", choices=["urgent", "high", "medium", "low"])
    s.add_argument("--limit", type=int, default=200)
    s.set_defaults(func=cmd_cards)

    s = sub.add_parser("card")
    s.add_argument("card")
    s.set_defaults(func=cmd_card)

    s = sub.add_parser("cycle")
    s.add_argument("board")
    s.set_defaults(func=cmd_cycle)

    s = sub.add_parser("cycles")
    s.add_argument("board")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_cycles)

    s = sub.add_parser("search")
    s.add_argument("query")
    s.add_argument("--workspace")
    s.add_argument("--board")
    s.add_argument("--limit", type=int, default=25)
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("create")
    s.add_argument("board")
    s.add_argument("--title", required=True)
    s.add_argument("--description")
    s.add_argument("--priority", choices=["urgent", "high", "medium", "low"])
    s.add_argument("--column")
    s.add_argument("--assignee")
    s.set_defaults(func=cmd_create)

    s = sub.add_parser("update")
    s.add_argument("card")
    s.add_argument("--title")
    s.add_argument("--description")
    s.add_argument("--priority", choices=["urgent", "high", "medium", "low"])
    s.add_argument("--due")
    s.add_argument("--estimate", type=int)
    s.set_defaults(func=cmd_update)

    s = sub.add_parser("move")
    s.add_argument("card")
    s.add_argument("--column", required=True)
    s.add_argument("--position", type=int)
    s.set_defaults(func=cmd_move)

    s = sub.add_parser("reorder")
    s.add_argument("cards", nargs="+")
    s.set_defaults(func=cmd_reorder)

    s = sub.add_parser("comments")
    s.add_argument("card")
    s.set_defaults(func=cmd_comments)

    s = sub.add_parser("comment")
    s.add_argument("card")
    s.add_argument("--body", required=True)
    s.set_defaults(func=cmd_comment)

    s = sub.add_parser("invite-guest")
    s.add_argument("board")
    s.add_argument("--email", required=True)
    s.add_argument("--role", choices=["admin", "editor", "viewer"], default="viewer")
    s.set_defaults(func=cmd_invite_guest)

    s = sub.add_parser("delete-card", help="Delete a card permanently.")
    s.add_argument("card")
    s.set_defaults(func=cmd_delete_card)

    s = sub.add_parser("attach", help="Upload a file as a card attachment (5MB max).")
    s.add_argument("card")
    s.add_argument("--path", required=True, help="Local path to the file to upload.")
    s.add_argument("--filename", help="Override the on-server filename (defaults to basename).")
    s.add_argument("--mime", help="Override the MIME type (defaults to mimetypes.guess_type).")
    s.set_defaults(func=cmd_attach)

    s = sub.add_parser("attachments", help="List attachments on a card.")
    s.add_argument("card")
    s.set_defaults(func=cmd_attachments)

    s = sub.add_parser("create-board", help="Create a new board in a workspace.")
    s.add_argument("name")
    s.add_argument("--workspace")
    s.add_argument("--description")
    s.add_argument("--columns", nargs="+", help="Override default columns (default: Backlog, In Progress, Review, Done).")
    s.set_defaults(func=cmd_create_board)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
