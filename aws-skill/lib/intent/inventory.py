"""Inventory intent: list everything tagged for a Customer / Owner.

v1: covers EC2 instances, Elastic IPs, security groups, key pairs.
v2: extends to S3, RDS, Lambda, etc.
"""
from __future__ import annotations

from typing import Any, Optional

import boto3

from ..services import ec2 as ec2_svc
from ..tagging import tags_from_aws


def by_customer(
    session: boto3.Session,
    *,
    customer: str,
) -> dict[str, Any]:
    """All resources tagged Customer=<name>, grouped by service."""
    instances = ec2_svc.list_instances(session, customer=customer, show_all=True)
    addresses = ec2_svc.list_addresses(session, customer=customer)
    security_groups = ec2_svc.list_security_groups(session, customer=customer)

    return {
        "customer": customer,
        "region": session.region_name,
        "summary": {
            "ec2_instances": len(instances),
            "elastic_ips": len(addresses),
            "security_groups": len(security_groups),
        },
        "ec2_instances": instances,
        "elastic_ips": addresses,
        "security_groups": security_groups,
    }


def by_tag_value(
    session: boto3.Session,
    *,
    tag_key: str,
    tag_value: str,
) -> list[dict[str, Any]]:
    """Generic tag-based listing using EC2-flavored Filters.

    Note: this only covers services whose APIs support tag:KEY filters.
    Some services (Lambda, RDS) use list_tags_for_resource and need separate
    handling — added in v2.
    """
    ec2_client = session.client("ec2")
    filters = [{"Name": f"tag:{tag_key}", "Values": [tag_value]}]

    out: list[dict[str, Any]] = []

    # EC2 instances
    paginator = ec2_client.get_paginator("describe_instances")
    for page in paginator.paginate(Filters=filters):
        for reservation in page.get("Reservations", []):
            for inst in reservation.get("Instances", []):
                out.append(
                    {
                        "type": "ec2_instance",
                        "id": inst.get("InstanceId"),
                        "state": inst.get("State", {}).get("Name"),
                        "public_ip": inst.get("PublicIpAddress"),
                        "tags": tags_from_aws(inst.get("Tags")),
                    }
                )

    # Elastic IPs
    addrs = ec2_client.describe_addresses(Filters=filters)
    for a in addrs.get("Addresses", []):
        out.append(
            {
                "type": "elastic_ip",
                "id": a.get("AllocationId"),
                "public_ip": a.get("PublicIp"),
                "association_id": a.get("AssociationId"),
                "tags": tags_from_aws(a.get("Tags")),
            }
        )

    # Security groups
    sgs = ec2_client.describe_security_groups(Filters=filters)
    for s in sgs.get("SecurityGroups", []):
        out.append(
            {
                "type": "security_group",
                "id": s.get("GroupId"),
                "name": s.get("GroupName"),
                "vpc_id": s.get("VpcId"),
                "tags": tags_from_aws(s.get("Tags")),
            }
        )

    # Key pairs (describe_key_pairs supports tag filters)
    kps = ec2_client.describe_key_pairs(Filters=filters)
    for k in kps.get("KeyPairs", []):
        out.append(
            {
                "type": "key_pair",
                "id": k.get("KeyPairId"),
                "name": k.get("KeyName"),
                "tags": tags_from_aws(k.get("Tags")),
            }
        )

    return out
