"""Cleanup intent: find resources missing required tags.

Walks common services looking for resources that don't carry our required
tag set (Customer/Project/Owner/Environment/ManagedBy). Reports them by
default; --confirm-delete actually terminates (only safe types).

What "safe to auto-delete" means here:
    - Stopped EC2 instances older than 7 days, untagged
    - Unattached Elastic IPs (cost real money), untagged
    - Empty security groups (not 'default'), untagged

Everything else is reported, not auto-acted-on.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import boto3

from ..tagging import REQUIRED_TAG_KEYS, missing_required_tags, tags_from_aws


def find_untagged(session: boto3.Session) -> dict[str, Any]:
    """Find resources missing one or more required tags."""
    ec2 = session.client("ec2")

    # EC2 instances
    instances_missing: list[dict[str, Any]] = []
    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate():
        for reservation in page.get("Reservations", []):
            for inst in reservation.get("Instances", []):
                missing = missing_required_tags(inst.get("Tags"))
                if missing:
                    instances_missing.append(
                        {
                            "type": "ec2_instance",
                            "id": inst.get("InstanceId"),
                            "state": inst.get("State", {}).get("Name"),
                            "launch_time": inst.get("LaunchTime"),
                            "missing_tags": missing,
                        }
                    )

    # Elastic IPs
    eips_missing: list[dict[str, Any]] = []
    for a in ec2.describe_addresses().get("Addresses", []):
        missing = missing_required_tags(a.get("Tags"))
        if missing:
            eips_missing.append(
                {
                    "type": "elastic_ip",
                    "id": a.get("AllocationId"),
                    "public_ip": a.get("PublicIp"),
                    "association_id": a.get("AssociationId"),
                    "missing_tags": missing,
                }
            )

    # Security groups (skip default; you can't tag the default SG meaningfully)
    sgs_missing: list[dict[str, Any]] = []
    for sg in ec2.describe_security_groups().get("SecurityGroups", []):
        if sg.get("GroupName") == "default":
            continue
        missing = missing_required_tags(sg.get("Tags"))
        if missing:
            sgs_missing.append(
                {
                    "type": "security_group",
                    "id": sg.get("GroupId"),
                    "name": sg.get("GroupName"),
                    "vpc_id": sg.get("VpcId"),
                    "missing_tags": missing,
                }
            )

    # Key pairs
    kps_missing: list[dict[str, Any]] = []
    for k in ec2.describe_key_pairs().get("KeyPairs", []):
        missing = missing_required_tags(k.get("Tags"))
        if missing:
            kps_missing.append(
                {
                    "type": "key_pair",
                    "id": k.get("KeyPairId"),
                    "name": k.get("KeyName"),
                    "missing_tags": missing,
                }
            )

    # EBS volumes (often forgotten — and they cost money)
    vols_missing: list[dict[str, Any]] = []
    for v in ec2.describe_volumes().get("Volumes", []):
        missing = missing_required_tags(v.get("Tags"))
        if missing:
            vols_missing.append(
                {
                    "type": "ebs_volume",
                    "id": v.get("VolumeId"),
                    "size_gb": v.get("Size"),
                    "state": v.get("State"),
                    "attachments": [
                        a.get("InstanceId") for a in v.get("Attachments", [])
                    ],
                    "missing_tags": missing,
                }
            )

    return {
        "required_tag_keys": list(REQUIRED_TAG_KEYS),
        "summary": {
            "ec2_instances": len(instances_missing),
            "elastic_ips": len(eips_missing),
            "security_groups": len(sgs_missing),
            "key_pairs": len(kps_missing),
            "ebs_volumes": len(vols_missing),
        },
        "ec2_instances": instances_missing,
        "elastic_ips": eips_missing,
        "security_groups": sgs_missing,
        "key_pairs": kps_missing,
        "ebs_volumes": vols_missing,
    }


def auto_delete_untagged(
    session: boto3.Session,
    *,
    older_than_days: int = 7,
) -> dict[str, Any]:
    """Delete the categorically-safe untagged resources.

    Only acts on:
      - Unattached Elastic IPs (any age — they cost money idle)
      - Stopped EC2 instances older than `older_than_days`

    Does NOT touch security groups, key pairs, EBS volumes, or running
    instances. Use the report-only `find_untagged()` and act manually for
    those.
    """
    ec2 = session.client("ec2")
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    actions: list[dict[str, Any]] = []

    # Unattached EIPs
    for a in ec2.describe_addresses().get("Addresses", []):
        if missing_required_tags(a.get("Tags")) and not a.get("AssociationId"):
            try:
                ec2.release_address(AllocationId=a["AllocationId"])
                actions.append(
                    {
                        "released_eip": a["AllocationId"],
                        "public_ip": a.get("PublicIp"),
                    }
                )
            except Exception as e:
                actions.append(
                    {"warn": f"release_eip {a['AllocationId']}: {e}"}
                )

    # Stopped, untagged, old instances
    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate(
        Filters=[{"Name": "instance-state-name", "Values": ["stopped"]}]
    ):
        for reservation in page.get("Reservations", []):
            for inst in reservation.get("Instances", []):
                if not missing_required_tags(inst.get("Tags")):
                    continue
                lt = inst.get("LaunchTime")
                if lt and lt > cutoff:
                    continue
                try:
                    ec2.terminate_instances(InstanceIds=[inst["InstanceId"]])
                    actions.append(
                        {
                            "terminated_instance": inst["InstanceId"],
                            "launch_time": lt,
                        }
                    )
                except Exception as e:
                    actions.append(
                        {"warn": f"terminate {inst['InstanceId']}: {e}"}
                    )

    return {
        "policy": {
            "older_than_days": older_than_days,
            "rules": [
                "Release unattached, untagged Elastic IPs",
                f"Terminate stopped, untagged EC2 instances older than {older_than_days} days",
            ],
        },
        "actions": actions,
        "actions_count": len(actions),
    }
