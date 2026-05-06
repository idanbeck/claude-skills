"""IAM service operations.

Read-only in v1. Writes are deliberately not exposed (IAM mistakes are
high-cost; do those in console or via Terraform).
"""
from __future__ import annotations

from typing import Any

import boto3

from ..auth import whoami as _whoami


def who_am_i(session: boto3.Session) -> dict[str, Any]:
    """STS GetCallerIdentity + account alias if available."""
    return _whoami(session)


def list_users(session: boto3.Session) -> list[dict]:
    iam = session.client("iam")
    out: list[dict] = []
    paginator = iam.get_paginator("list_users")
    for page in paginator.paginate():
        for u in page.get("Users", []):
            out.append(
                {
                    "user_name": u.get("UserName"),
                    "user_id": u.get("UserId"),
                    "arn": u.get("Arn"),
                    "created": u.get("CreateDate"),
                    "password_last_used": u.get("PasswordLastUsed"),
                }
            )
    return out


def list_roles(session: boto3.Session) -> list[dict]:
    iam = session.client("iam")
    out: list[dict] = []
    paginator = iam.get_paginator("list_roles")
    for page in paginator.paginate():
        for r in page.get("Roles", []):
            out.append(
                {
                    "role_name": r.get("RoleName"),
                    "role_id": r.get("RoleId"),
                    "arn": r.get("Arn"),
                    "created": r.get("CreateDate"),
                    "path": r.get("Path"),
                }
            )
    return out


def list_policies(
    session: boto3.Session, *, scope: str = "Local"
) -> list[dict]:
    """List managed policies. scope='Local' = customer-managed (default);
    scope='AWS' = AWS-managed; scope='All' = both."""
    iam = session.client("iam")
    out: list[dict] = []
    paginator = iam.get_paginator("list_policies")
    for page in paginator.paginate(Scope=scope):
        for p in page.get("Policies", []):
            out.append(
                {
                    "policy_name": p.get("PolicyName"),
                    "arn": p.get("Arn"),
                    "attachment_count": p.get("AttachmentCount"),
                    "created": p.get("CreateDate"),
                    "updated": p.get("UpdateDate"),
                }
            )
    return out
