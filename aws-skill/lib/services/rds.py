"""RDS service operations.

Read-heavy. The one write exposed in v2 is `snapshot` — clean, safe, easy
to undo. Engine creation / deletion stays out of scope (use console or
Terraform).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import boto3

from ..tagging import tags_from_aws


def list_instances(
    session: boto3.Session,
    *,
    customer: Optional[str] = None,
) -> list[dict[str, Any]]:
    rds = session.client("rds")
    paginator = rds.get_paginator("describe_db_instances")
    out: list[dict[str, Any]] = []
    for page in paginator.paginate():
        for inst in page.get("DBInstances", []):
            tags = _instance_tags(rds, inst.get("DBInstanceArn"))
            if customer and tags.get("Customer") != customer:
                continue
            out.append(
                {
                    "id": inst.get("DBInstanceIdentifier"),
                    "engine": inst.get("Engine"),
                    "engine_version": inst.get("EngineVersion"),
                    "status": inst.get("DBInstanceStatus"),
                    "class": inst.get("DBInstanceClass"),
                    "endpoint": (
                        inst.get("Endpoint", {}).get("Address")
                        if inst.get("Endpoint")
                        else None
                    ),
                    "port": (
                        inst.get("Endpoint", {}).get("Port")
                        if inst.get("Endpoint")
                        else None
                    ),
                    "publicly_accessible": inst.get("PubliclyAccessible"),
                    "storage_gb": inst.get("AllocatedStorage"),
                    "multi_az": inst.get("MultiAZ"),
                    "tags": tags,
                }
            )
    return out


def describe_instance(
    session: boto3.Session, instance_id: str
) -> dict[str, Any]:
    rds = session.client("rds")
    resp = rds.describe_db_instances(DBInstanceIdentifier=instance_id)
    instances = resp.get("DBInstances", [])
    if not instances:
        raise ValueError(f"No RDS instance with ID {instance_id}")
    inst = instances[0]
    tags = _instance_tags(rds, inst.get("DBInstanceArn"))
    return {
        "id": inst.get("DBInstanceIdentifier"),
        "arn": inst.get("DBInstanceArn"),
        "engine": inst.get("Engine"),
        "engine_version": inst.get("EngineVersion"),
        "status": inst.get("DBInstanceStatus"),
        "class": inst.get("DBInstanceClass"),
        "endpoint": inst.get("Endpoint"),
        "vpc_security_groups": inst.get("VpcSecurityGroups", []),
        "subnet_group": (
            inst.get("DBSubnetGroup", {}).get("DBSubnetGroupName")
            if inst.get("DBSubnetGroup")
            else None
        ),
        "publicly_accessible": inst.get("PubliclyAccessible"),
        "storage_gb": inst.get("AllocatedStorage"),
        "storage_encrypted": inst.get("StorageEncrypted"),
        "multi_az": inst.get("MultiAZ"),
        "backup_retention_period": inst.get("BackupRetentionPeriod"),
        "preferred_backup_window": inst.get("PreferredBackupWindow"),
        "tags": tags,
    }


def list_snapshots(
    session: boto3.Session, *, instance_id: Optional[str] = None
) -> list[dict[str, Any]]:
    rds = session.client("rds")
    kwargs: dict[str, Any] = {}
    if instance_id:
        kwargs["DBInstanceIdentifier"] = instance_id
    paginator = rds.get_paginator("describe_db_snapshots")
    out: list[dict[str, Any]] = []
    for page in paginator.paginate(**kwargs):
        for snap in page.get("DBSnapshots", []):
            out.append(
                {
                    "id": snap.get("DBSnapshotIdentifier"),
                    "instance_id": snap.get("DBInstanceIdentifier"),
                    "type": snap.get("SnapshotType"),
                    "status": snap.get("Status"),
                    "created": snap.get("SnapshotCreateTime"),
                    "engine": snap.get("Engine"),
                    "storage_gb": snap.get("AllocatedStorage"),
                    "encrypted": snap.get("Encrypted"),
                }
            )
    return out


def create_snapshot(
    session: boto3.Session,
    *,
    instance_id: str,
    snapshot_id: Optional[str] = None,
) -> dict[str, Any]:
    """Create a manual snapshot. Default name: <instance>-<utc-timestamp>."""
    rds = session.client("rds")
    if not snapshot_id:
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        snapshot_id = f"{instance_id}-{ts}".lower()
    resp = rds.create_db_snapshot(
        DBSnapshotIdentifier=snapshot_id,
        DBInstanceIdentifier=instance_id,
    )
    snap = resp.get("DBSnapshot", {})
    return {
        "snapshot_id": snap.get("DBSnapshotIdentifier"),
        "instance_id": snap.get("DBInstanceIdentifier"),
        "status": snap.get("Status"),
        "created": snap.get("SnapshotCreateTime"),
    }


def _instance_tags(rds_client, arn: Optional[str]) -> dict[str, str]:
    if not arn:
        return {}
    try:
        resp = rds_client.list_tags_for_resource(ResourceName=arn)
        return tags_from_aws(resp.get("TagList"))
    except Exception:
        return {}
