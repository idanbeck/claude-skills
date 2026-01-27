#!/usr/bin/env python3
"""GitHub Skill - PR and issue management via gh CLI."""

import subprocess
import json
import argparse
import re
import sys
from pathlib import Path
from typing import Optional, Union, List, Dict, Any

SKILL_DIR = Path(__file__).parent
CONFIG_FILE = SKILL_DIR / "config.json"


def load_config() -> dict:
    """Load config file if it exists."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def run_gh(args: list, raw: bool = False) -> Union[dict, list, str]:
    """Run gh command and return output."""
    result = subprocess.run(
        ["gh"] + args,
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        return {"error": result.stderr.strip()}
    if raw:
        return result.stdout.strip()
    if not result.stdout.strip():
        return []
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"error": f"Failed to parse JSON: {result.stdout[:200]}"}


def extract_linear_id(title: str) -> Optional[str]:
    """Extract Linear issue ID from PR title (e.g., EPO-123)."""
    match = re.search(r'\b([A-Z]+-\d+)\b', title)
    return match.group(1) if match else None


def format_review_decision(decision: Optional[str]) -> str:
    """Format review decision for display."""
    mapping = {
        "APPROVED": "Approved",
        "CHANGES_REQUESTED": "Changes Requested",
        "REVIEW_REQUIRED": "Review Required",
        None: "No reviews"
    }
    return mapping.get(decision, decision or "Unknown")


def format_check_status(checks: Optional[list]) -> str:
    """Summarize check statuses."""
    if not checks:
        return "No checks"

    statuses = {}
    for check in checks:
        conclusion = check.get("conclusion") or check.get("status", "pending")
        statuses[conclusion.lower()] = statuses.get(conclusion.lower(), 0) + 1

    parts = []
    if "success" in statuses:
        parts.append(f"{statuses['success']} passed")
    if "failure" in statuses:
        parts.append(f"{statuses['failure']} failed")
    if "pending" in statuses or "in_progress" in statuses:
        pending = statuses.get("pending", 0) + statuses.get("in_progress", 0)
        parts.append(f"{pending} pending")

    return ", ".join(parts) if parts else "Unknown"


def format_vault_pr(pr: dict, reviews: list = None, comments: list = None) -> str:
    """Format PR as markdown for vault notes."""
    lines = []

    # Header
    linear_id = extract_linear_id(pr.get("title", ""))
    title = pr.get("title", "Unknown")
    number = pr.get("number", "?")

    lines.append(f"## PR #{number}: {title}")
    lines.append("")

    # Metadata
    author = pr.get("author", {}).get("login", "unknown")
    state = pr.get("state", "UNKNOWN")
    review_decision = format_review_decision(pr.get("reviewDecision"))
    url = pr.get("url", "")

    lines.append(f"**Status:** {state}, {review_decision}")
    lines.append(f"**Author:** @{author}")
    if linear_id:
        lines.append(f"**Linear:** {linear_id}")
    lines.append(f"**Link:** [{url.split('/')[-3]}/{url.split('/')[-2]}#{number}]({url})")
    lines.append("")

    # Checks
    checks = pr.get("statusCheckRollup", [])
    if checks:
        lines.append("### Checks")
        for check in checks[:10]:  # Limit to 10
            name = check.get("name", "Unknown")
            conclusion = check.get("conclusion") or check.get("status", "pending")
            icon = {"success": "OK", "failure": "FAIL", "pending": "..."}
            status_icon = icon.get(conclusion.lower(), conclusion)
            lines.append(f"- {name}: {status_icon}")
        lines.append("")

    # Reviews
    if reviews:
        lines.append("### Reviews")
        for review in reviews:
            reviewer = review.get("author", {}).get("login", "unknown")
            state = review.get("state", "UNKNOWN")
            body = review.get("body", "")[:100]
            if body:
                lines.append(f"- @{reviewer}: {state} - \"{body}\"")
            else:
                lines.append(f"- @{reviewer}: {state}")
        lines.append("")

    return "\n".join(lines)


# Command handlers

def cmd_prs(args):
    """List open PRs."""
    gh_args = ["pr", "list", "--json",
               "number,title,author,state,createdAt,url,reviewDecision,statusCheckRollup,additions,deletions"]

    if args.mine:
        gh_args.extend(["--author", "@me"])
    if args.repo:
        gh_args.extend(["--repo", args.repo])
    if args.limit:
        gh_args.extend(["--limit", str(args.limit)])
    if args.state:
        gh_args.extend(["--state", args.state])

    result = run_gh(gh_args)

    if isinstance(result, dict) and "error" in result:
        return result

    # Enrich with Linear IDs
    for pr in result:
        pr["linear_id"] = extract_linear_id(pr.get("title", ""))
        pr["checks_summary"] = format_check_status(pr.get("statusCheckRollup"))

    return result


def cmd_pr(args):
    """Get PR details."""
    gh_args = ["pr", "view", str(args.number), "--json",
               "number,title,author,state,body,createdAt,url,reviewDecision,"
               "statusCheckRollup,additions,deletions,changedFiles,commits,comments,"
               "headRefName,baseRefName,mergeable,isDraft"]

    if args.repo:
        gh_args.extend(["--repo", args.repo])

    result = run_gh(gh_args)

    if isinstance(result, dict) and "error" not in result:
        result["linear_id"] = extract_linear_id(result.get("title", ""))
        result["checks_summary"] = format_check_status(result.get("statusCheckRollup"))

    if args.format == "vault":
        return format_vault_pr(result)

    return result


def cmd_pr_comments(args):
    """Get PR review comments."""
    gh_args = ["pr", "view", str(args.number), "--json", "comments"]

    if args.repo:
        gh_args.extend(["--repo", args.repo])

    result = run_gh(gh_args)

    if isinstance(result, dict) and "error" not in result:
        return result.get("comments", [])

    return result


def cmd_pr_reviews(args):
    """Get PR reviews."""
    gh_args = ["pr", "view", str(args.number), "--json", "reviews"]

    if args.repo:
        gh_args.extend(["--repo", args.repo])

    result = run_gh(gh_args)

    if isinstance(result, dict) and "error" not in result:
        return result.get("reviews", [])

    return result


def cmd_review_requests(args):
    """List PRs where your review is requested."""
    gh_args = ["pr", "list", "--search", "review-requested:@me", "--json",
               "number,title,author,state,createdAt,url,reviewDecision,statusCheckRollup"]

    if args.repo:
        gh_args.extend(["--repo", args.repo])
    if args.limit:
        gh_args.extend(["--limit", str(args.limit)])

    result = run_gh(gh_args)

    if isinstance(result, dict) and "error" in result:
        return result

    # Enrich with Linear IDs
    for pr in result:
        pr["linear_id"] = extract_linear_id(pr.get("title", ""))
        pr["checks_summary"] = format_check_status(pr.get("statusCheckRollup"))

    return result


def cmd_issues(args):
    """List issues."""
    gh_args = ["issue", "list", "--json",
               "number,title,author,state,createdAt,url,labels,assignees"]

    if args.mine:
        gh_args.extend(["--author", "@me"])
    if args.repo:
        gh_args.extend(["--repo", args.repo])
    if args.limit:
        gh_args.extend(["--limit", str(args.limit)])
    if args.state:
        gh_args.extend(["--state", args.state])

    return run_gh(gh_args)


def cmd_issue(args):
    """Get issue details."""
    gh_args = ["issue", "view", str(args.number), "--json",
               "number,title,author,state,body,createdAt,url,labels,assignees,comments"]

    if args.repo:
        gh_args.extend(["--repo", args.repo])

    return run_gh(gh_args)


def cmd_repos(args):
    """List your repos."""
    gh_args = ["repo", "list", "--json", "name,url,description,isPrivate,updatedAt"]

    if args.limit:
        gh_args.extend(["--limit", str(args.limit)])

    return run_gh(gh_args)


def cmd_notifications(args):
    """List unread notifications."""
    # gh doesn't have great JSON support for notifications, use API
    gh_args = ["api", "notifications", "--jq",
               "[.[] | {id: .id, reason: .reason, title: .subject.title, type: .subject.type, url: .subject.url, updated_at: .updated_at}]"]

    result = run_gh(gh_args)

    if isinstance(result, dict) and "error" in result:
        return result

    # Limit results
    if args.limit and isinstance(result, list):
        result = result[:args.limit]

    return result


def main():
    parser = argparse.ArgumentParser(description="GitHub Skill - PR and issue management")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Common arguments
    def add_common_args(p, with_mine=False):
        p.add_argument("--repo", "-r", help="Repository (owner/repo)")
        p.add_argument("--limit", "-l", type=int, default=20, help="Number of results")
        if with_mine:
            p.add_argument("--mine", "-m", action="store_true", help="Only your items")

    # prs
    p_prs = subparsers.add_parser("prs", help="List open PRs")
    add_common_args(p_prs, with_mine=True)
    p_prs.add_argument("--state", "-s", choices=["open", "closed", "merged", "all"], default="open")
    p_prs.set_defaults(func=cmd_prs)

    # pr
    p_pr = subparsers.add_parser("pr", help="Get PR details")
    p_pr.add_argument("number", type=int, help="PR number")
    p_pr.add_argument("--repo", "-r", help="Repository (owner/repo)")
    p_pr.add_argument("--format", "-f", choices=["json", "vault"], default="json")
    p_pr.set_defaults(func=cmd_pr)

    # pr-comments
    p_comments = subparsers.add_parser("pr-comments", help="Get PR review comments")
    p_comments.add_argument("number", type=int, help="PR number")
    p_comments.add_argument("--repo", "-r", help="Repository (owner/repo)")
    p_comments.set_defaults(func=cmd_pr_comments)

    # pr-reviews
    p_reviews = subparsers.add_parser("pr-reviews", help="Get PR reviews")
    p_reviews.add_argument("number", type=int, help="PR number")
    p_reviews.add_argument("--repo", "-r", help="Repository (owner/repo)")
    p_reviews.set_defaults(func=cmd_pr_reviews)

    # review-requests
    p_rr = subparsers.add_parser("review-requests", help="PRs awaiting your review")
    add_common_args(p_rr)
    p_rr.set_defaults(func=cmd_review_requests)

    # issues
    p_issues = subparsers.add_parser("issues", help="List issues")
    add_common_args(p_issues, with_mine=True)
    p_issues.add_argument("--state", "-s", choices=["open", "closed", "all"], default="open")
    p_issues.set_defaults(func=cmd_issues)

    # issue
    p_issue = subparsers.add_parser("issue", help="Get issue details")
    p_issue.add_argument("number", type=int, help="Issue number")
    p_issue.add_argument("--repo", "-r", help="Repository (owner/repo)")
    p_issue.set_defaults(func=cmd_issue)

    # repos
    p_repos = subparsers.add_parser("repos", help="List your repos")
    p_repos.add_argument("--limit", "-l", type=int, default=30, help="Number of results")
    p_repos.set_defaults(func=cmd_repos)

    # notifications
    p_notif = subparsers.add_parser("notifications", help="Unread notifications")
    p_notif.add_argument("--limit", "-l", type=int, default=20, help="Number of results")
    p_notif.set_defaults(func=cmd_notifications)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    result = args.func(args)

    if isinstance(result, str):
        # Vault format or raw string
        print(result)
    else:
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
