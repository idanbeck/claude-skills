#!/usr/bin/env python3
"""
Notion Skill - Read Notion databases and pages.

Uses the Notion API with internal integration token authentication.
Supports multiple workspaces/accounts.

Usage:
    python notion_skill.py accounts
    python notion_skill.py databases [-a ACCOUNT]
    python notion_skill.py query DATABASE_ID [-a ACCOUNT] [--limit N]
    python notion_skill.py page PAGE_ID [-a ACCOUNT]
    python notion_skill.py search "query" [-a ACCOUNT] [--type database|page]
    python notion_skill.py export DATABASE_ID [-a ACCOUNT] [--output FILE]
"""

import argparse
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Dict, Any, List

# Paths
SKILL_DIR = Path(__file__).parent
CONFIG_FILE = SKILL_DIR / "config.json"

# Notion API
API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def load_config() -> Dict:
    """Load config with account tokens."""
    if not CONFIG_FILE.exists():
        print(json.dumps({
            "error": "No config file found",
            "setup_required": True,
            "instructions": [
                "1. Go to https://www.notion.so/my-integrations",
                "2. Create an integration for each workspace",
                "3. Copy the Internal Integration Secret for each",
                "4. Share your databases/pages with each integration",
                f"5. Create config with accounts (see SKILL.md)"
            ]
        }, indent=2))
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        return json.load(f)


def get_token(account: Optional[str] = None) -> str:
    """Get token for specified account or default."""
    config = load_config()

    accounts = config.get("accounts", {})

    # If no accounts dict, check for legacy single-token format
    if not accounts and config.get("token"):
        return config["token"]

    if not accounts:
        print(json.dumps({"error": "No accounts configured"}))
        sys.exit(1)

    # If no account specified, use default or first account
    if not account:
        account = config.get("default_account")
        if not account:
            account = list(accounts.keys())[0]

    if account not in accounts:
        print(json.dumps({
            "error": f"Account not found: {account}",
            "available_accounts": list(accounts.keys())
        }))
        sys.exit(1)

    return accounts[account]["token"]


def api_request(endpoint: str, method: str = "GET", data: Optional[Dict] = None, account: Optional[str] = None) -> Dict:
    """Make a request to Notion API."""
    token = get_token(account)

    url = f"{API_BASE}/{endpoint}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

    body = json.dumps(data).encode("utf-8") if data else None

    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else str(e)
        try:
            error_json = json.loads(error_body)
            print(json.dumps({
                "error": f"HTTP {e.code}",
                "message": error_json.get("message", "Unknown error"),
                "code": error_json.get("code", "unknown")
            }, indent=2))
        except:
            print(json.dumps({"error": f"HTTP {e.code}", "details": error_body}))
        sys.exit(1)
    except urllib.error.URLError as e:
        print(json.dumps({"error": f"Connection error: {e.reason}"}))
        sys.exit(1)


def extract_property_value(prop: Dict) -> Any:
    """Extract the value from a Notion property."""
    prop_type = prop.get("type")

    if prop_type == "title":
        texts = prop.get("title", [])
        return "".join(t.get("plain_text", "") for t in texts)

    elif prop_type == "rich_text":
        texts = prop.get("rich_text", [])
        return "".join(t.get("plain_text", "") for t in texts)

    elif prop_type == "number":
        return prop.get("number")

    elif prop_type == "select":
        select = prop.get("select")
        return select.get("name") if select else None

    elif prop_type == "multi_select":
        return [s.get("name") for s in prop.get("multi_select", [])]

    elif prop_type == "status":
        status = prop.get("status")
        return status.get("name") if status else None

    elif prop_type == "date":
        date = prop.get("date")
        if date:
            start = date.get("start", "")
            end = date.get("end")
            return f"{start} - {end}" if end else start
        return None

    elif prop_type == "people":
        people = prop.get("people", [])
        return [p.get("name", p.get("id")) for p in people]

    elif prop_type == "email":
        return prop.get("email")

    elif prop_type == "phone_number":
        return prop.get("phone_number")

    elif prop_type == "url":
        return prop.get("url")

    elif prop_type == "checkbox":
        return prop.get("checkbox")

    elif prop_type == "relation":
        relations = prop.get("relation", [])
        return [r.get("id") for r in relations]

    elif prop_type == "rollup":
        rollup = prop.get("rollup", {})
        rollup_type = rollup.get("type")
        if rollup_type == "number":
            return rollup.get("number")
        elif rollup_type == "array":
            return [extract_property_value({"type": item.get("type"), **item})
                    for item in rollup.get("array", [])]
        return rollup

    elif prop_type == "formula":
        formula = prop.get("formula", {})
        formula_type = formula.get("type")
        return formula.get(formula_type)

    elif prop_type == "created_time":
        return prop.get("created_time")

    elif prop_type == "last_edited_time":
        return prop.get("last_edited_time")

    elif prop_type == "created_by":
        user = prop.get("created_by", {})
        return user.get("name", user.get("id"))

    elif prop_type == "last_edited_by":
        user = prop.get("last_edited_by", {})
        return user.get("name", user.get("id"))

    elif prop_type == "files":
        files = prop.get("files", [])
        result = []
        for f in files:
            if f.get("type") == "file":
                result.append(f.get("file", {}).get("url"))
            elif f.get("type") == "external":
                result.append(f.get("external", {}).get("url"))
        return result

    return f"<{prop_type}>"


def format_page(page: Dict) -> Dict:
    """Format a page/database entry for output."""
    properties = page.get("properties", {})

    formatted_props = {}
    title = None

    for name, prop in properties.items():
        value = extract_property_value(prop)
        formatted_props[name] = value

        # Capture title
        if prop.get("type") == "title":
            title = value

    return {
        "id": page.get("id"),
        "title": title,
        "url": page.get("url"),
        "created_time": page.get("created_time"),
        "last_edited_time": page.get("last_edited_time"),
        "properties": formatted_props,
    }


def get_block_content(block_id: str, account: Optional[str] = None) -> List[Dict]:
    """Get all blocks (content) for a page."""
    blocks = []
    has_more = True
    start_cursor = None

    while has_more:
        endpoint = f"blocks/{block_id}/children"
        if start_cursor:
            endpoint += f"?start_cursor={start_cursor}"

        data = api_request(endpoint, account=account)
        blocks.extend(data.get("results", []))
        has_more = data.get("has_more", False)
        start_cursor = data.get("next_cursor")

    return blocks


def extract_block_text(block: Dict) -> str:
    """Extract plain text from a block."""
    block_type = block.get("type")
    block_data = block.get(block_type, {})

    if "rich_text" in block_data:
        texts = block_data.get("rich_text", [])
        return "".join(t.get("plain_text", "") for t in texts)

    return ""


# ============ Commands ============

def cmd_accounts(args):
    """List configured accounts."""
    config = load_config()
    accounts = config.get("accounts", {})

    if not accounts and config.get("token"):
        print(json.dumps({
            "accounts": [{"name": "default", "note": "legacy single-token config"}],
            "default": "default"
        }, indent=2))
        return

    default = config.get("default_account", list(accounts.keys())[0] if accounts else None)

    account_list = []
    for name, info in accounts.items():
        account_list.append({
            "name": name,
            "email": info.get("email"),
            "workspace": info.get("workspace"),
            "is_default": name == default,
        })

    print(json.dumps({
        "accounts": account_list,
        "default": default,
    }, indent=2))


def cmd_databases(args):
    """List all databases."""
    data = api_request("search", method="POST", data={
        "filter": {"value": "database", "property": "object"},
        "page_size": 100
    }, account=args.account)

    databases = []
    for db in data.get("results", []):
        title_prop = db.get("title", [])
        title = "".join(t.get("plain_text", "") for t in title_prop)

        # Get property names and types
        props = db.get("properties", {})
        prop_summary = {name: p.get("type") for name, p in props.items()}

        databases.append({
            "id": db.get("id"),
            "title": title or "(Untitled)",
            "url": db.get("url"),
            "properties": prop_summary,
        })

    print(json.dumps({
        "account": args.account or "(default)",
        "databases": databases,
        "total": len(databases),
    }, indent=2))


def cmd_query(args):
    """Query a database."""
    database_id = args.database_id.replace("-", "")

    query_body = {
        "page_size": args.limit or 100
    }

    # Add filter if provided
    if args.filter:
        parts = args.filter.split(":", 1)
        if len(parts) == 2:
            prop_name, value = parts
            # Simple equals filter - assumes text/select property
            query_body["filter"] = {
                "property": prop_name,
                "rich_text": {"equals": value}
            }

    results = []
    has_more = True
    start_cursor = None
    fetched = 0

    while has_more and fetched < (args.limit or 100):
        if start_cursor:
            query_body["start_cursor"] = start_cursor

        data = api_request(f"databases/{database_id}/query", method="POST", data=query_body, account=args.account)

        for page in data.get("results", []):
            if fetched >= (args.limit or 100):
                break
            results.append(format_page(page))
            fetched += 1

        has_more = data.get("has_more", False)
        start_cursor = data.get("next_cursor")

    print(json.dumps({
        "account": args.account or "(default)",
        "database_id": args.database_id,
        "results": results,
        "total": len(results),
    }, indent=2))


def cmd_page(args):
    """Get a page with its content."""
    page_id = args.page_id.replace("-", "")

    # Get page properties
    page = api_request(f"pages/{page_id}", account=args.account)
    formatted = format_page(page)

    # Get page content
    blocks = get_block_content(page_id, account=args.account)

    content = []
    for block in blocks:
        block_type = block.get("type")
        text = extract_block_text(block)

        content.append({
            "type": block_type,
            "text": text,
            "has_children": block.get("has_children", False),
        })

    formatted["content"] = content

    print(json.dumps(formatted, indent=2))


def cmd_search(args):
    """Search for pages or databases."""
    query_body = {
        "query": args.query,
        "page_size": 20
    }

    if args.type:
        query_body["filter"] = {
            "value": args.type,
            "property": "object"
        }

    data = api_request("search", method="POST", data=query_body, account=args.account)

    results = []
    for item in data.get("results", []):
        obj_type = item.get("object")

        if obj_type == "database":
            title_prop = item.get("title", [])
            title = "".join(t.get("plain_text", "") for t in title_prop)
            results.append({
                "type": "database",
                "id": item.get("id"),
                "title": title or "(Untitled)",
                "url": item.get("url"),
            })

        elif obj_type == "page":
            formatted = format_page(item)
            formatted["type"] = "page"
            results.append(formatted)

    print(json.dumps({
        "account": args.account or "(default)",
        "query": args.query,
        "results": results,
        "total": len(results),
    }, indent=2))


def cmd_export(args):
    """Export entire database to JSON."""
    database_id = args.database_id.replace("-", "")

    # First get database schema
    db_info = api_request(f"databases/{database_id}", account=args.account)
    title_prop = db_info.get("title", [])
    db_title = "".join(t.get("plain_text", "") for t in title_prop)

    props = db_info.get("properties", {})
    schema = {name: p.get("type") for name, p in props.items()}

    # Query all entries
    results = []
    has_more = True
    start_cursor = None

    while has_more:
        query_body = {"page_size": 100}
        if start_cursor:
            query_body["start_cursor"] = start_cursor

        data = api_request(f"databases/{database_id}/query", method="POST", data=query_body, account=args.account)

        for page in data.get("results", []):
            results.append(format_page(page))

        has_more = data.get("has_more", False)
        start_cursor = data.get("next_cursor")

    export_data = {
        "database": {
            "id": args.database_id,
            "title": db_title,
            "schema": schema,
        },
        "entries": results,
        "total": len(results),
    }

    if args.output:
        with open(args.output, "w") as f:
            json.dump(export_data, f, indent=2)
        print(json.dumps({
            "success": True,
            "file": args.output,
            "entries_exported": len(results),
        }, indent=2))
    else:
        print(json.dumps(export_data, indent=2))


# ============ Main ============

def main():
    parser = argparse.ArgumentParser(
        description="Notion Skill - Read Notion databases and pages"
    )
    parser.add_argument("-a", "--account", help="Account/workspace to use")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Accounts
    sub = subparsers.add_parser("accounts", help="List configured accounts")
    sub.set_defaults(func=cmd_accounts)

    # Databases
    sub = subparsers.add_parser("databases", help="List all databases")
    sub.add_argument("-a", "--account", help="Account/workspace to use")
    sub.set_defaults(func=cmd_databases)

    # Query
    sub = subparsers.add_parser("query", help="Query a database")
    sub.add_argument("database_id", help="Database ID")
    sub.add_argument("-a", "--account", help="Account/workspace to use")
    sub.add_argument("-l", "--limit", type=int, default=100, help="Number of results")
    sub.add_argument("-f", "--filter", help="Filter as PROPERTY:VALUE")
    sub.set_defaults(func=cmd_query)

    # Page
    sub = subparsers.add_parser("page", help="Get a page")
    sub.add_argument("page_id", help="Page ID")
    sub.add_argument("-a", "--account", help="Account/workspace to use")
    sub.set_defaults(func=cmd_page)

    # Search
    sub = subparsers.add_parser("search", help="Search Notion")
    sub.add_argument("query", help="Search query")
    sub.add_argument("-a", "--account", help="Account/workspace to use")
    sub.add_argument("-t", "--type", choices=["database", "page"], help="Filter by type")
    sub.set_defaults(func=cmd_search)

    # Export
    sub = subparsers.add_parser("export", help="Export database to JSON")
    sub.add_argument("database_id", help="Database ID")
    sub.add_argument("-a", "--account", help="Account/workspace to use")
    sub.add_argument("-o", "--output", help="Output file (default: stdout)")
    sub.set_defaults(func=cmd_export)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
