#!/usr/bin/env python3
"""
Figma Skill - Read files, export assets, and manage comments.

Usage:
    python figma_skill.py me
    python figma_skill.py files [--project PROJECT_ID]
    python figma_skill.py get FILE_KEY
    python figma_skill.py nodes FILE_KEY --ids "1:2,1:3"
    python figma_skill.py images FILE_KEY --ids "1:2,1:3" [--format png|jpg|svg|pdf] [--scale N]
    python figma_skill.py components FILE_KEY
    python figma_skill.py styles FILE_KEY
    python figma_skill.py comments FILE_KEY
    python figma_skill.py add-comment FILE_KEY --message "..." [--x X] [--y Y] [--node-id ID]
    python figma_skill.py projects TEAM_ID
    python figma_skill.py team-components TEAM_ID
    python figma_skill.py versions FILE_KEY
"""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("Run: pip install requests")
    sys.exit(1)

SKILL_DIR = Path(__file__).parent
CONFIG_FILE = SKILL_DIR / "config.json"

FIGMA_API = "https://api.figma.com/v1"


def get_config() -> dict:
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)

    print("\n" + "=" * 60)
    print("FIGMA SETUP REQUIRED")
    print("=" * 60)
    print("\n1. Go to Figma → Account Settings → Personal Access Tokens")
    print("2. Create a new token")
    print("3. Create config.json:")
    print(f"   {CONFIG_FILE}")
    print('   {"access_token": "YOUR_TOKEN"}')
    print("=" * 60 + "\n")
    sys.exit(1)


def api_request(endpoint: str, method: str = "GET", data: dict = None, params: dict = None) -> dict:
    config = get_config()
    headers = {"X-Figma-Token": config["access_token"]}
    url = f"{FIGMA_API}{endpoint}"

    if method == "GET":
        r = requests.get(url, headers=headers, params=params)
    elif method == "POST":
        r = requests.post(url, headers=headers, json=data)
    else:
        raise ValueError(f"Unsupported: {method}")

    if r.status_code >= 400:
        return {"error": True, "status": r.status_code, "message": r.text}

    return r.json()


def cmd_me(args):
    result = api_request("/me")
    print(json.dumps(result, indent=2))


def cmd_files(args):
    if args.project:
        result = api_request(f"/projects/{args.project}/files")
    else:
        # List recent files requires team context, so we'll show help
        print(json.dumps({
            "error": "Specify --project PROJECT_ID to list files",
            "hint": "Use 'projects TEAM_ID' to find project IDs"
        }, indent=2))
        return
    print(json.dumps(result, indent=2))


def cmd_get(args):
    result = api_request(f"/files/{args.file_key}")

    if result.get("error"):
        print(json.dumps(result, indent=2))
        return

    # Simplify output
    doc = result.get("document", {})
    output = {
        "name": result.get("name"),
        "lastModified": result.get("lastModified"),
        "version": result.get("version"),
        "thumbnailUrl": result.get("thumbnailUrl"),
        "pages": [{
            "id": p.get("id"),
            "name": p.get("name"),
            "childCount": len(p.get("children", [])),
        } for p in doc.get("children", [])],
    }
    print(json.dumps(output, indent=2))


def cmd_nodes(args):
    ids = args.ids.replace(" ", "")
    result = api_request(f"/files/{args.file_key}/nodes", params={"ids": ids})
    print(json.dumps(result, indent=2))


def cmd_images(args):
    ids = args.ids.replace(" ", "")
    params = {
        "ids": ids,
        "format": args.format,
        "scale": args.scale,
    }
    result = api_request(f"/images/{args.file_key}", params=params)
    print(json.dumps(result, indent=2))


def cmd_components(args):
    result = api_request(f"/files/{args.file_key}/components")

    if result.get("error"):
        print(json.dumps(result, indent=2))
        return

    components = [{
        "key": c.get("key"),
        "name": c.get("name"),
        "description": c.get("description"),
        "node_id": c.get("node_id"),
    } for c in result.get("meta", {}).get("components", [])]

    print(json.dumps({"components": components, "count": len(components)}, indent=2))


def cmd_styles(args):
    result = api_request(f"/files/{args.file_key}/styles")

    if result.get("error"):
        print(json.dumps(result, indent=2))
        return

    styles = [{
        "key": s.get("key"),
        "name": s.get("name"),
        "style_type": s.get("style_type"),
        "description": s.get("description"),
    } for s in result.get("meta", {}).get("styles", [])]

    print(json.dumps({"styles": styles, "count": len(styles)}, indent=2))


def cmd_comments(args):
    result = api_request(f"/files/{args.file_key}/comments")

    if result.get("error"):
        print(json.dumps(result, indent=2))
        return

    comments = [{
        "id": c.get("id"),
        "message": c.get("message"),
        "user": c.get("user", {}).get("handle"),
        "created_at": c.get("created_at"),
        "resolved_at": c.get("resolved_at"),
        "order_id": c.get("order_id"),
    } for c in result.get("comments", [])]

    print(json.dumps({"comments": comments, "count": len(comments)}, indent=2))


def cmd_add_comment(args):
    data = {"message": args.message}

    if args.node_id:
        data["client_meta"] = {"node_id": args.node_id}
    elif args.x is not None and args.y is not None:
        data["client_meta"] = {"x": args.x, "y": args.y}

    result = api_request(f"/files/{args.file_key}/comments", method="POST", data=data)
    print(json.dumps(result, indent=2))


def cmd_projects(args):
    result = api_request(f"/teams/{args.team_id}/projects")
    print(json.dumps(result, indent=2))


def cmd_team_components(args):
    result = api_request(f"/teams/{args.team_id}/components")
    print(json.dumps(result, indent=2))


def cmd_versions(args):
    result = api_request(f"/files/{args.file_key}/versions")

    if result.get("error"):
        print(json.dumps(result, indent=2))
        return

    versions = [{
        "id": v.get("id"),
        "created_at": v.get("created_at"),
        "label": v.get("label"),
        "description": v.get("description"),
        "user": v.get("user", {}).get("handle"),
    } for v in result.get("versions", [])]

    print(json.dumps({"versions": versions}, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Figma Skill")
    subs = parser.add_subparsers(dest="command")

    subs.add_parser("me").set_defaults(func=cmd_me)

    files = subs.add_parser("files")
    files.add_argument("--project", "-p")
    files.set_defaults(func=cmd_files)

    get = subs.add_parser("get")
    get.add_argument("file_key")
    get.set_defaults(func=cmd_get)

    nodes = subs.add_parser("nodes")
    nodes.add_argument("file_key")
    nodes.add_argument("--ids", required=True)
    nodes.set_defaults(func=cmd_nodes)

    images = subs.add_parser("images")
    images.add_argument("file_key")
    images.add_argument("--ids", required=True)
    images.add_argument("--format", "-f", choices=["png", "jpg", "svg", "pdf"], default="png")
    images.add_argument("--scale", "-s", type=float, default=1)
    images.set_defaults(func=cmd_images)

    components = subs.add_parser("components")
    components.add_argument("file_key")
    components.set_defaults(func=cmd_components)

    styles = subs.add_parser("styles")
    styles.add_argument("file_key")
    styles.set_defaults(func=cmd_styles)

    comments = subs.add_parser("comments")
    comments.add_argument("file_key")
    comments.set_defaults(func=cmd_comments)

    add_comment = subs.add_parser("add-comment")
    add_comment.add_argument("file_key")
    add_comment.add_argument("--message", "-m", required=True)
    add_comment.add_argument("--x", type=float)
    add_comment.add_argument("--y", type=float)
    add_comment.add_argument("--node-id")
    add_comment.set_defaults(func=cmd_add_comment)

    projects = subs.add_parser("projects")
    projects.add_argument("team_id")
    projects.set_defaults(func=cmd_projects)

    team_comp = subs.add_parser("team-components")
    team_comp.add_argument("team_id")
    team_comp.set_defaults(func=cmd_team_components)

    versions = subs.add_parser("versions")
    versions.add_argument("file_key")
    versions.set_defaults(func=cmd_versions)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
