"""ECR operations: repos, images, login helper."""
from __future__ import annotations

import base64
from typing import Any, Optional

import boto3

from ..tagging import tags_from_aws


def list_repos(session: boto3.Session) -> list[dict[str, Any]]:
    ecr = session.client("ecr")
    paginator = ecr.get_paginator("describe_repositories")
    out: list[dict[str, Any]] = []
    for page in paginator.paginate():
        for r in page.get("repositories", []):
            out.append(
                {
                    "name": r.get("repositoryName"),
                    "arn": r.get("repositoryArn"),
                    "uri": r.get("repositoryUri"),
                    "created": r.get("createdAt"),
                    "image_tag_mutability": r.get("imageTagMutability"),
                    "scan_on_push": r.get("imageScanningConfiguration", {}).get(
                        "scanOnPush"
                    ),
                    "tags": _repo_tags(ecr, r.get("repositoryArn")),
                }
            )
    return out


def list_images(
    session: boto3.Session,
    repo: str,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    ecr = session.client("ecr")
    paginator = ecr.get_paginator("describe_images")
    out: list[dict[str, Any]] = []
    for page in paginator.paginate(repositoryName=repo):
        for img in page.get("imageDetails", []):
            out.append(
                {
                    "tags": img.get("imageTags") or [],
                    "digest": img.get("imageDigest"),
                    "pushed": img.get("imagePushedAt"),
                    "size_mb": (
                        round(img.get("imageSizeInBytes", 0) / (1024 * 1024), 2)
                        if img.get("imageSizeInBytes")
                        else None
                    ),
                    "scan_findings_severity_counts": (
                        img.get("imageScanFindingsSummary", {}).get(
                            "findingSeverityCounts"
                        )
                        if img.get("imageScanFindingsSummary")
                        else None
                    ),
                }
            )
            if len(out) >= limit:
                return out
    return out


def login_command(session: boto3.Session) -> dict[str, Any]:
    """Return a docker login command + token. Token expires in 12 hours."""
    ecr = session.client("ecr")
    resp = ecr.get_authorization_token()
    auth = (resp.get("authorizationData") or [{}])[0]
    raw = auth.get("authorizationToken", "")
    decoded = base64.b64decode(raw).decode("utf-8") if raw else ""
    user, _, password = decoded.partition(":")
    endpoint = auth.get("proxyEndpoint", "")
    return {
        "registry": endpoint,
        "username": user,
        "expires_at": auth.get("expiresAt"),
        "docker_login_command": (
            f"echo '{password}' | docker login --username {user} "
            f"--password-stdin {endpoint}"
        ),
    }


def _repo_tags(ecr_client, arn: Optional[str]) -> dict[str, str]:
    if not arn:
        return {}
    try:
        resp = ecr_client.list_tags_for_resource(resourceArn=arn)
        return tags_from_aws(resp.get("tags"))
    except Exception:
        return {}
