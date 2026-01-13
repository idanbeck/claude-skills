#!/usr/bin/env python3
"""
Linear Skill - Read and manage Linear issues, projects, and cycles.

Uses the Linear GraphQL API with personal API key authentication.

Usage:
    python linear_skill.py my-issues [--limit N] [--status STATUS]
    python linear_skill.py teams
    python linear_skill.py issues TEAM [--limit N] [--status STATUS] [--priority PRIORITY]
    python linear_skill.py issue ISSUE_ID
    python linear_skill.py cycle TEAM
    python linear_skill.py cycles TEAM [--limit N]
    python linear_skill.py search "query" [--limit N]
    python linear_skill.py create TEAM --title "Title" [--description "Desc"] [--priority P]
    python linear_skill.py update ISSUE_ID --status STATUS
    python linear_skill.py projects [TEAM]
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

# Linear API endpoint
API_URL = "https://api.linear.app/graphql"

# Priority mapping
PRIORITY_MAP = {
    "urgent": 1,
    "high": 2,
    "medium": 3,
    "low": 4,
    "none": 0,
}

PRIORITY_REVERSE = {v: k for k, v in PRIORITY_MAP.items()}


def load_config() -> Dict:
    """Load API key from config."""
    if not CONFIG_FILE.exists():
        print(json.dumps({
            "error": "No config file found",
            "setup_required": True,
            "instructions": [
                "1. Go to Linear Settings > Account > Security & Access",
                "2. Create a Personal API key",
                "3. Copy the key (starts with lin_api_)",
                f"4. Create config: echo '{{\"api_key\": \"lin_api_...\"}}' > {CONFIG_FILE}"
            ]
        }, indent=2))
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        return json.load(f)


def graphql_request(query: str, variables: Optional[Dict] = None) -> Dict:
    """Make a GraphQL request to Linear API."""
    config = load_config()
    api_key = config.get("api_key")

    if not api_key:
        print(json.dumps({"error": "No API key in config"}))
        sys.exit(1)

    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        API_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": api_key,
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode("utf-8"))
            if "errors" in result:
                print(json.dumps({"error": result["errors"]}))
                sys.exit(1)
            return result.get("data", {})
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else str(e)
        print(json.dumps({"error": f"HTTP {e.code}", "details": error_body}))
        sys.exit(1)
    except urllib.error.URLError as e:
        print(json.dumps({"error": f"Connection error: {e.reason}"}))
        sys.exit(1)


def format_issue(issue: Dict) -> Dict:
    """Format an issue for output."""
    assignee = issue.get("assignee")
    cycle = issue.get("cycle")
    state = issue.get("state", {})

    return {
        "id": issue.get("id"),
        "identifier": issue.get("identifier"),
        "title": issue.get("title"),
        "description": (issue.get("description") or "")[:200] + "..." if issue.get("description") and len(issue.get("description", "")) > 200 else issue.get("description"),
        "status": state.get("name"),
        "status_type": state.get("type"),
        "priority": PRIORITY_REVERSE.get(issue.get("priority", 0), "none"),
        "priority_num": issue.get("priority", 0),
        "assignee": assignee.get("name") if assignee else None,
        "assignee_email": assignee.get("email") if assignee else None,
        "cycle": cycle.get("name") if cycle else None,
        "estimate": issue.get("estimate"),
        "labels": [l.get("name") for l in issue.get("labels", {}).get("nodes", [])],
        "created_at": issue.get("createdAt"),
        "updated_at": issue.get("updatedAt"),
        "url": issue.get("url"),
    }


def get_team_id(team_key: str) -> Optional[str]:
    """Resolve team key/name to team ID."""
    query = """
    query Teams {
        teams {
            nodes {
                id
                key
                name
            }
        }
    }
    """
    data = graphql_request(query)
    teams = data.get("teams", {}).get("nodes", [])

    for team in teams:
        if team.get("key", "").lower() == team_key.lower() or \
           team.get("name", "").lower() == team_key.lower():
            return team.get("id")

    return None


def get_status_filter(status: str) -> Dict:
    """Convert status name to filter."""
    status_types = {
        "backlog": "backlog",
        "todo": "unstarted",
        "in_progress": "started",
        "in_review": "started",
        "done": "completed",
        "canceled": "canceled",
        "cancelled": "canceled",
    }

    status_type = status_types.get(status.lower())
    if status_type:
        return {"state": {"type": {"eq": status_type}}}
    return {}


# ============ Commands ============

def cmd_my_issues(args):
    """Get issues assigned to me."""
    filters = []

    if args.status:
        status_filter = get_status_filter(args.status)
        if status_filter:
            filters.append(status_filter)

    filter_str = ""
    if filters:
        # Build filter object
        filter_obj = filters[0] if len(filters) == 1 else {"and": filters}
        filter_str = f", filter: {json.dumps(filter_obj).replace('\"', '')}"
        # Fix the JSON to GraphQL conversion
        filter_str = f", filter: {{ state: {{ type: {{ eq: \"{get_status_filter(args.status).get('state', {}).get('type', {}).get('eq', '')}\" }} }} }}" if args.status else ""

    query = f"""
    query MyIssues {{
        viewer {{
            id
            name
            email
            assignedIssues(first: {args.limit or 20}{filter_str}) {{
                nodes {{
                    id
                    identifier
                    title
                    description
                    priority
                    estimate
                    url
                    createdAt
                    updatedAt
                    state {{
                        id
                        name
                        type
                    }}
                    assignee {{
                        id
                        name
                        email
                    }}
                    cycle {{
                        id
                        name
                        number
                    }}
                    labels {{
                        nodes {{
                            name
                        }}
                    }}
                }}
            }}
        }}
    }}
    """

    data = graphql_request(query)
    viewer = data.get("viewer", {})
    issues = viewer.get("assignedIssues", {}).get("nodes", [])

    print(json.dumps({
        "user": {
            "name": viewer.get("name"),
            "email": viewer.get("email"),
        },
        "issues": [format_issue(i) for i in issues],
        "total": len(issues),
    }, indent=2))


def cmd_teams(args):
    """List teams."""
    query = """
    query Teams {
        teams {
            nodes {
                id
                key
                name
                description
                issueCount
                activeCycle {
                    id
                    name
                    number
                    startsAt
                    endsAt
                }
            }
        }
    }
    """

    data = graphql_request(query)
    teams = data.get("teams", {}).get("nodes", [])

    formatted = []
    for team in teams:
        cycle = team.get("activeCycle")
        formatted.append({
            "id": team.get("id"),
            "key": team.get("key"),
            "name": team.get("name"),
            "description": team.get("description"),
            "issue_count": team.get("issueCount"),
            "active_cycle": cycle.get("name") if cycle else None,
        })

    print(json.dumps({
        "teams": formatted,
        "total": len(formatted),
    }, indent=2))


def cmd_issues(args):
    """List issues for a team."""
    team_id = get_team_id(args.team)
    if not team_id:
        print(json.dumps({"error": f"Team not found: {args.team}"}))
        return

    # Build filters
    filters = [f"team: {{ id: {{ eq: \"{team_id}\" }} }}"]

    if args.status:
        status_filter = get_status_filter(args.status)
        if status_filter:
            state_type = status_filter.get("state", {}).get("type", {}).get("eq")
            if state_type:
                filters.append(f"state: {{ type: {{ eq: \"{state_type}\" }} }}")

    if args.priority:
        priority_val = PRIORITY_MAP.get(args.priority.lower())
        if priority_val is not None:
            filters.append(f"priority: {{ eq: {priority_val} }}")

    filter_str = ", ".join(filters)

    query = f"""
    query TeamIssues {{
        issues(first: {args.limit or 20}, filter: {{ {filter_str} }}) {{
            nodes {{
                id
                identifier
                title
                description
                priority
                estimate
                url
                createdAt
                updatedAt
                state {{
                    id
                    name
                    type
                }}
                assignee {{
                    id
                    name
                    email
                }}
                cycle {{
                    id
                    name
                    number
                }}
                labels {{
                    nodes {{
                        name
                    }}
                }}
            }}
        }}
    }}
    """

    data = graphql_request(query)
    issues = data.get("issues", {}).get("nodes", [])

    print(json.dumps({
        "team": args.team,
        "issues": [format_issue(i) for i in issues],
        "total": len(issues),
    }, indent=2))


def cmd_issue(args):
    """Get single issue details."""
    # Try to find by identifier first
    query = f"""
    query Issue {{
        issue(id: "{args.issue_id}") {{
            id
            identifier
            title
            description
            priority
            estimate
            url
            createdAt
            updatedAt
            state {{
                id
                name
                type
            }}
            assignee {{
                id
                name
                email
            }}
            team {{
                id
                key
                name
            }}
            cycle {{
                id
                name
                number
            }}
            project {{
                id
                name
            }}
            labels {{
                nodes {{
                    name
                }}
            }}
            comments {{
                nodes {{
                    id
                    body
                    createdAt
                    user {{
                        name
                    }}
                }}
            }}
        }}
    }}
    """

    data = graphql_request(query)
    issue = data.get("issue")

    if not issue:
        # Try searching by identifier
        search_query = f"""
        query SearchIssue {{
            issueSearch(query: "{args.issue_id}", first: 1) {{
                nodes {{
                    id
                    identifier
                    title
                    description
                    priority
                    estimate
                    url
                    createdAt
                    updatedAt
                    state {{
                        id
                        name
                        type
                    }}
                    assignee {{
                        id
                        name
                        email
                    }}
                    team {{
                        id
                        key
                        name
                    }}
                    cycle {{
                        id
                        name
                        number
                    }}
                    labels {{
                        nodes {{
                            name
                        }}
                    }}
                }}
            }}
        }}
        """
        data = graphql_request(search_query)
        issues = data.get("issueSearch", {}).get("nodes", [])
        if issues:
            issue = issues[0]

    if not issue:
        print(json.dumps({"error": f"Issue not found: {args.issue_id}"}))
        return

    formatted = format_issue(issue)

    # Add extra details
    team = issue.get("team", {})
    project = issue.get("project")
    comments = issue.get("comments", {}).get("nodes", [])

    formatted["team"] = {"key": team.get("key"), "name": team.get("name")} if team else None
    formatted["project"] = project.get("name") if project else None
    formatted["comments"] = [
        {
            "author": c.get("user", {}).get("name"),
            "body": c.get("body"),
            "created_at": c.get("createdAt"),
        }
        for c in comments[:5]  # Last 5 comments
    ]

    print(json.dumps(formatted, indent=2))


def cmd_cycle(args):
    """Get current cycle for a team."""
    team_id = get_team_id(args.team)
    if not team_id:
        print(json.dumps({"error": f"Team not found: {args.team}"}))
        return

    query = f"""
    query TeamCycle {{
        team(id: "{team_id}") {{
            id
            key
            name
            activeCycle {{
                id
                name
                number
                startsAt
                endsAt
                progress
                scopeProgress
                issueCountHistory
                completedIssueCountHistory
                issues {{
                    nodes {{
                        id
                        identifier
                        title
                        priority
                        state {{
                            name
                            type
                        }}
                        assignee {{
                            name
                        }}
                    }}
                }}
            }}
        }}
    }}
    """

    data = graphql_request(query)
    team = data.get("team", {})
    cycle = team.get("activeCycle")

    if not cycle:
        print(json.dumps({
            "team": args.team,
            "cycle": None,
            "message": "No active cycle"
        }, indent=2))
        return

    issues = cycle.get("issues", {}).get("nodes", [])

    # Group by status
    by_status = {}
    for issue in issues:
        status = issue.get("state", {}).get("name", "Unknown")
        if status not in by_status:
            by_status[status] = []
        by_status[status].append({
            "identifier": issue.get("identifier"),
            "title": issue.get("title"),
            "assignee": issue.get("assignee", {}).get("name") if issue.get("assignee") else None,
            "priority": PRIORITY_REVERSE.get(issue.get("priority", 0), "none"),
        })

    print(json.dumps({
        "team": {"key": team.get("key"), "name": team.get("name")},
        "cycle": {
            "name": cycle.get("name"),
            "number": cycle.get("number"),
            "starts_at": cycle.get("startsAt"),
            "ends_at": cycle.get("endsAt"),
            "progress": cycle.get("progress"),
            "scope_progress": cycle.get("scopeProgress"),
        },
        "issues_by_status": by_status,
        "total_issues": len(issues),
    }, indent=2))


def cmd_cycles(args):
    """List cycles for a team."""
    team_id = get_team_id(args.team)
    if not team_id:
        print(json.dumps({"error": f"Team not found: {args.team}"}))
        return

    query = f"""
    query TeamCycles {{
        team(id: "{team_id}") {{
            id
            key
            name
            cycles(first: {args.limit or 10}) {{
                nodes {{
                    id
                    name
                    number
                    startsAt
                    endsAt
                    progress
                    completedScopeHistory
                }}
            }}
        }}
    }}
    """

    data = graphql_request(query)
    team = data.get("team", {})
    cycles = team.get("cycles", {}).get("nodes", [])

    formatted = []
    for cycle in cycles:
        formatted.append({
            "id": cycle.get("id"),
            "name": cycle.get("name"),
            "number": cycle.get("number"),
            "starts_at": cycle.get("startsAt"),
            "ends_at": cycle.get("endsAt"),
            "progress": cycle.get("progress"),
        })

    print(json.dumps({
        "team": {"key": team.get("key"), "name": team.get("name")},
        "cycles": formatted,
        "total": len(formatted),
    }, indent=2))


def cmd_search(args):
    """Search issues."""
    query = f"""
    query SearchIssues {{
        issueSearch(query: "{args.query}", first: {args.limit or 20}) {{
            nodes {{
                id
                identifier
                title
                description
                priority
                url
                state {{
                    name
                    type
                }}
                assignee {{
                    name
                }}
                team {{
                    key
                }}
            }}
        }}
    }}
    """

    data = graphql_request(query)
    issues = data.get("issueSearch", {}).get("nodes", [])

    formatted = []
    for issue in issues:
        formatted.append({
            "identifier": issue.get("identifier"),
            "title": issue.get("title"),
            "status": issue.get("state", {}).get("name"),
            "priority": PRIORITY_REVERSE.get(issue.get("priority", 0), "none"),
            "assignee": issue.get("assignee", {}).get("name") if issue.get("assignee") else None,
            "team": issue.get("team", {}).get("key"),
            "url": issue.get("url"),
        })

    print(json.dumps({
        "query": args.query,
        "issues": formatted,
        "total": len(formatted),
    }, indent=2))


def cmd_create(args):
    """Create a new issue."""
    team_id = get_team_id(args.team)
    if not team_id:
        print(json.dumps({"error": f"Team not found: {args.team}"}))
        return

    # Build input
    inputs = [f'teamId: "{team_id}"', f'title: "{args.title}"']

    if args.description:
        # Escape description for GraphQL
        desc = args.description.replace('"', '\\"').replace('\n', '\\n')
        inputs.append(f'description: "{desc}"')

    if args.priority:
        priority_val = PRIORITY_MAP.get(args.priority.lower())
        if priority_val is not None:
            inputs.append(f'priority: {priority_val}')

    input_str = ", ".join(inputs)

    query = f"""
    mutation CreateIssue {{
        issueCreate(input: {{ {input_str} }}) {{
            success
            issue {{
                id
                identifier
                title
                url
                state {{
                    name
                }}
            }}
        }}
    }}
    """

    data = graphql_request(query)
    result = data.get("issueCreate", {})

    if result.get("success"):
        issue = result.get("issue", {})
        print(json.dumps({
            "success": True,
            "issue": {
                "identifier": issue.get("identifier"),
                "title": issue.get("title"),
                "status": issue.get("state", {}).get("name"),
                "url": issue.get("url"),
            }
        }, indent=2))
    else:
        print(json.dumps({"success": False, "error": "Failed to create issue"}))


def cmd_update(args):
    """Update an issue."""
    # First find the issue
    search_query = f"""
    query FindIssue {{
        issueSearch(query: "{args.issue_id}", first: 1) {{
            nodes {{
                id
                identifier
                team {{
                    id
                    states {{
                        nodes {{
                            id
                            name
                            type
                        }}
                    }}
                }}
            }}
        }}
    }}
    """

    data = graphql_request(search_query)
    issues = data.get("issueSearch", {}).get("nodes", [])

    if not issues:
        print(json.dumps({"error": f"Issue not found: {args.issue_id}"}))
        return

    issue = issues[0]
    issue_id = issue.get("id")

    # Build update input
    inputs = []

    if args.status:
        # Find the state ID
        states = issue.get("team", {}).get("states", {}).get("nodes", [])
        status_filter = get_status_filter(args.status)
        target_type = status_filter.get("state", {}).get("type", {}).get("eq")

        state_id = None
        for state in states:
            if state.get("type") == target_type or state.get("name", "").lower() == args.status.lower():
                state_id = state.get("id")
                break

        if state_id:
            inputs.append(f'stateId: "{state_id}"')
        else:
            print(json.dumps({"error": f"Status not found: {args.status}"}))
            return

    if not inputs:
        print(json.dumps({"error": "No updates specified"}))
        return

    input_str = ", ".join(inputs)

    update_query = f"""
    mutation UpdateIssue {{
        issueUpdate(id: "{issue_id}", input: {{ {input_str} }}) {{
            success
            issue {{
                id
                identifier
                title
                state {{
                    name
                }}
                url
            }}
        }}
    }}
    """

    data = graphql_request(update_query)
    result = data.get("issueUpdate", {})

    if result.get("success"):
        updated = result.get("issue", {})
        print(json.dumps({
            "success": True,
            "issue": {
                "identifier": updated.get("identifier"),
                "title": updated.get("title"),
                "status": updated.get("state", {}).get("name"),
                "url": updated.get("url"),
            }
        }, indent=2))
    else:
        print(json.dumps({"success": False, "error": "Failed to update issue"}))


def cmd_projects(args):
    """List projects."""
    if args.team:
        team_id = get_team_id(args.team)
        if not team_id:
            print(json.dumps({"error": f"Team not found: {args.team}"}))
            return

        query = f"""
        query TeamProjects {{
            team(id: "{team_id}") {{
                projects {{
                    nodes {{
                        id
                        name
                        description
                        state
                        progress
                        targetDate
                    }}
                }}
            }}
        }}
        """
        data = graphql_request(query)
        projects = data.get("team", {}).get("projects", {}).get("nodes", [])
    else:
        query = """
        query Projects {
            projects {
                nodes {
                    id
                    name
                    description
                    state
                    progress
                    targetDate
                    teams {
                        nodes {
                            key
                        }
                    }
                }
            }
        }
        """
        data = graphql_request(query)
        projects = data.get("projects", {}).get("nodes", [])

    formatted = []
    for project in projects:
        teams = project.get("teams", {}).get("nodes", [])
        formatted.append({
            "id": project.get("id"),
            "name": project.get("name"),
            "description": project.get("description"),
            "state": project.get("state"),
            "progress": project.get("progress"),
            "target_date": project.get("targetDate"),
            "teams": [t.get("key") for t in teams] if teams else None,
        })

    print(json.dumps({
        "team": args.team if args.team else "all",
        "projects": formatted,
        "total": len(formatted),
    }, indent=2))


# ============ Main ============

def main():
    parser = argparse.ArgumentParser(
        description="Linear Skill - Read and manage Linear issues"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # My Issues
    sub = subparsers.add_parser("my-issues", help="Get issues assigned to me")
    sub.add_argument("-l", "--limit", type=int, default=20, help="Number of issues")
    sub.add_argument("-s", "--status", help="Filter by status")
    sub.set_defaults(func=cmd_my_issues)

    # Teams
    sub = subparsers.add_parser("teams", help="List teams")
    sub.set_defaults(func=cmd_teams)

    # Issues
    sub = subparsers.add_parser("issues", help="List team issues")
    sub.add_argument("team", help="Team key or name")
    sub.add_argument("-l", "--limit", type=int, default=20, help="Number of issues")
    sub.add_argument("-s", "--status", help="Filter by status")
    sub.add_argument("-p", "--priority", help="Filter by priority")
    sub.set_defaults(func=cmd_issues)

    # Issue
    sub = subparsers.add_parser("issue", help="Get issue details")
    sub.add_argument("issue_id", help="Issue identifier (e.g., EPO-123) or ID")
    sub.set_defaults(func=cmd_issue)

    # Cycle
    sub = subparsers.add_parser("cycle", help="Get current cycle")
    sub.add_argument("team", help="Team key or name")
    sub.set_defaults(func=cmd_cycle)

    # Cycles
    sub = subparsers.add_parser("cycles", help="List cycles")
    sub.add_argument("team", help="Team key or name")
    sub.add_argument("-l", "--limit", type=int, default=10, help="Number of cycles")
    sub.set_defaults(func=cmd_cycles)

    # Search
    sub = subparsers.add_parser("search", help="Search issues")
    sub.add_argument("query", help="Search query")
    sub.add_argument("-l", "--limit", type=int, default=20, help="Number of results")
    sub.set_defaults(func=cmd_search)

    # Create
    sub = subparsers.add_parser("create", help="Create an issue")
    sub.add_argument("team", help="Team key or name")
    sub.add_argument("-t", "--title", required=True, help="Issue title")
    sub.add_argument("-d", "--description", help="Issue description")
    sub.add_argument("-p", "--priority", help="Priority: urgent, high, medium, low, none")
    sub.set_defaults(func=cmd_create)

    # Update
    sub = subparsers.add_parser("update", help="Update an issue")
    sub.add_argument("issue_id", help="Issue identifier (e.g., EPO-123)")
    sub.add_argument("-s", "--status", help="New status")
    sub.set_defaults(func=cmd_update)

    # Projects
    sub = subparsers.add_parser("projects", help="List projects")
    sub.add_argument("team", nargs="?", help="Team key or name (optional)")
    sub.set_defaults(func=cmd_projects)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
