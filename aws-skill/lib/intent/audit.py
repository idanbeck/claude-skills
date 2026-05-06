"""Security audit intent.

Looks for common AWS misconfigurations:
    - Security groups with 0.0.0.0/0 ingress on non-web ports
    - Public S3 buckets (per get_public_access_block + ACL)
    - IAM access keys older than N days (default 90)
    - IAM users without MFA
    - RDS instances with publicly accessible = true
    - Untagged resources (delegates to cleanup.find_untagged for the count)

Returns a structured report with severities. No mutating operations —
this is observability only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

from ..services import s3 as s3_svc
from .cleanup import find_untagged


# Web-style ports that 0.0.0.0/0 ingress is usually intentional on
WEB_PORTS = {80, 443}


def run(session: boto3.Session, *, key_age_days: int = 90) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    findings.extend(_audit_security_groups(session))
    findings.extend(_audit_s3_buckets(session))
    findings.extend(_audit_iam_keys(session, age_days=key_age_days))
    findings.extend(_audit_iam_mfa(session))
    findings.extend(_audit_rds_public(session))

    # Tag cleanliness summary (don't enumerate; just count)
    try:
        untagged = find_untagged(session)
        if any(untagged["summary"].values()):
            findings.append(
                {
                    "severity": "low",
                    "category": "tagging",
                    "title": "Resources missing required tags",
                    "detail": untagged["summary"],
                    "recommendation": (
                        "Run `aws_skill.py cleanup untagged` for full list."
                    ),
                }
            )
    except ClientError:
        pass

    return {
        "checked_at": datetime.utcnow().isoformat() + "Z",
        "summary": _severity_counts(findings),
        "findings": findings,
    }


# ---- Security groups -------------------------------------------------------


def _audit_security_groups(session: boto3.Session) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    ec2 = session.client("ec2")
    for sg in ec2.describe_security_groups().get("SecurityGroups", []):
        for perm in sg.get("IpPermissions", []) or []:
            from_p = perm.get("FromPort")
            to_p = perm.get("ToPort")
            for r in perm.get("IpRanges", []) or []:
                if r.get("CidrIp") == "0.0.0.0/0":
                    # All-port ranges (None or 0–65535) are always severe
                    if from_p is None or (from_p == 0 and to_p == 65535):
                        sev = "high"
                    elif from_p in WEB_PORTS and to_p in WEB_PORTS:
                        sev = "info"
                    elif from_p == 22:
                        sev = "high"
                    else:
                        sev = "medium"
                    findings.append(
                        {
                            "severity": sev,
                            "category": "security_group",
                            "title": "Open ingress from 0.0.0.0/0",
                            "resource": sg.get("GroupId"),
                            "name": sg.get("GroupName"),
                            "vpc_id": sg.get("VpcId"),
                            "port_range": (
                                f"{from_p}-{to_p}" if from_p is not None else "all"
                            ),
                            "protocol": perm.get("IpProtocol"),
                            "recommendation": (
                                "Restrict CIDR to a known IP range or remove "
                                "the rule if unintended."
                            ),
                        }
                    )
    return findings


# ---- S3 --------------------------------------------------------------------


def _audit_s3_buckets(session: boto3.Session) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    s3 = session.client("s3")
    for b in s3.list_buckets().get("Buckets", []):
        name = b.get("Name")
        try:
            status = s3_svc.public_access_status(session, name)
        except ClientError as e:
            findings.append(
                {
                    "severity": "low",
                    "category": "s3",
                    "title": "Could not assess bucket public-access",
                    "resource": name,
                    "detail": str(e),
                }
            )
            continue
        if status.get("acl_public_grants"):
            findings.append(
                {
                    "severity": "high",
                    "category": "s3",
                    "title": "Bucket ACL grants public access",
                    "resource": name,
                    "grants": status.get("acl_public_grants"),
                    "recommendation": (
                        "Apply a public access block; review whether the "
                        "public grant is intentional (CDN-fronted asset bucket?)."
                    ),
                }
            )
        elif status.get("public_access_block") is None:
            findings.append(
                {
                    "severity": "medium",
                    "category": "s3",
                    "title": "Bucket has no public-access-block configuration",
                    "resource": name,
                    "recommendation": (
                        "Apply BlockPublicAcls / IgnorePublicAcls / "
                        "BlockPublicPolicy / RestrictPublicBuckets all = true."
                    ),
                }
            )
    return findings


# ---- IAM --------------------------------------------------------------------


def _audit_iam_keys(
    session: boto3.Session, *, age_days: int = 90
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    iam = session.client("iam")
    cutoff = datetime.now(timezone.utc) - timedelta(days=age_days)
    for u in iam.list_users().get("Users", []):
        try:
            keys = iam.list_access_keys(UserName=u["UserName"]).get(
                "AccessKeyMetadata", []
            )
        except ClientError:
            continue
        for k in keys:
            if k.get("Status") != "Active":
                continue
            created = k.get("CreateDate")
            if not created:
                continue
            if created < cutoff:
                age_d = (datetime.now(timezone.utc) - created).days
                findings.append(
                    {
                        "severity": "medium" if age_d < 365 else "high",
                        "category": "iam_key",
                        "title": f"Access key older than {age_days} days",
                        "resource": k.get("AccessKeyId"),
                        "user": u.get("UserName"),
                        "age_days": age_d,
                        "recommendation": (
                            "Rotate the key. If unused, deactivate or delete."
                        ),
                    }
                )
    return findings


def _audit_iam_mfa(session: boto3.Session) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    iam = session.client("iam")
    for u in iam.list_users().get("Users", []):
        try:
            devices = iam.list_mfa_devices(UserName=u["UserName"]).get(
                "MFADevices", []
            )
        except ClientError:
            continue
        if not devices:
            # Check if user can log in with a password (no password = no MFA needed)
            try:
                iam.get_login_profile(UserName=u["UserName"])
                has_password = True
            except ClientError as e:
                if e.response.get("Error", {}).get("Code") == "NoSuchEntity":
                    has_password = False
                else:
                    has_password = True
            if has_password:
                findings.append(
                    {
                        "severity": "high",
                        "category": "iam_mfa",
                        "title": "IAM user has password but no MFA",
                        "resource": u.get("UserName"),
                        "recommendation": "Enable MFA or remove the password.",
                    }
                )
    return findings


# ---- RDS -------------------------------------------------------------------


def _audit_rds_public(session: boto3.Session) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    rds = session.client("rds")
    paginator = rds.get_paginator("describe_db_instances")
    for page in paginator.paginate():
        for inst in page.get("DBInstances", []):
            if inst.get("PubliclyAccessible"):
                findings.append(
                    {
                        "severity": "high",
                        "category": "rds",
                        "title": "RDS instance is publicly accessible",
                        "resource": inst.get("DBInstanceIdentifier"),
                        "engine": inst.get("Engine"),
                        "endpoint": (
                            inst.get("Endpoint", {}).get("Address")
                            if inst.get("Endpoint")
                            else None
                        ),
                        "recommendation": (
                            "Set PubliclyAccessible=false and restrict access "
                            "via security group / VPC peering / private link."
                        ),
                    }
                )
    return findings


def _severity_counts(findings: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"high": 0, "medium": 0, "low": 0, "info": 0, "total": len(findings)}
    for f in findings:
        sev = f.get("severity", "info")
        counts[sev] = counts.get(sev, 0) + 1
    return counts
