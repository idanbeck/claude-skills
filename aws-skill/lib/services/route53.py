"""Route 53 service operations.

DNS zones and records. Route 53 doesn't expose tags via standard
filtering; tags fetched separately via list_tags_for_resource.
"""
from __future__ import annotations

from typing import Any, Optional

import boto3

from ..tagging import tags_from_aws


def list_zones(session: boto3.Session) -> list[dict[str, Any]]:
    r53 = session.client("route53")
    paginator = r53.get_paginator("list_hosted_zones")
    out: list[dict[str, Any]] = []
    for page in paginator.paginate():
        for z in page.get("HostedZones", []):
            zone_id = (z.get("Id") or "").split("/")[-1]
            tags = _zone_tags(r53, zone_id)
            out.append(
                {
                    "zone_id": zone_id,
                    "name": z.get("Name"),
                    "private": z.get("Config", {}).get("PrivateZone"),
                    "record_count": z.get("ResourceRecordSetCount"),
                    "comment": z.get("Config", {}).get("Comment"),
                    "tags": tags,
                }
            )
    return out


def list_records(
    session: boto3.Session, zone_id: str
) -> list[dict[str, Any]]:
    r53 = session.client("route53")
    paginator = r53.get_paginator("list_resource_record_sets")
    out: list[dict[str, Any]] = []
    for page in paginator.paginate(HostedZoneId=zone_id):
        for r in page.get("ResourceRecordSets", []):
            out.append(
                {
                    "name": r.get("Name"),
                    "type": r.get("Type"),
                    "ttl": r.get("TTL"),
                    "values": [
                        rr.get("Value") for rr in r.get("ResourceRecords", []) or []
                    ],
                    "alias_target": r.get("AliasTarget"),
                    "set_identifier": r.get("SetIdentifier"),
                    "weight": r.get("Weight"),
                }
            )
    return out


def upsert_record(
    session: boto3.Session,
    *,
    zone_id: str,
    name: str,
    type: str,
    values: list[str],
    ttl: int = 300,
) -> dict[str, Any]:
    """Create-or-update a simple record. For aliases / weighted records use
    the AWS Console / Terraform — they're edge cases not worth wrapping."""
    r53 = session.client("route53")
    resp = r53.change_resource_record_sets(
        HostedZoneId=zone_id,
        ChangeBatch={
            "Changes": [
                {
                    "Action": "UPSERT",
                    "ResourceRecordSet": {
                        "Name": name,
                        "Type": type,
                        "TTL": ttl,
                        "ResourceRecords": [{"Value": v} for v in values],
                    },
                }
            ]
        },
    )
    return {
        "change_id": resp.get("ChangeInfo", {}).get("Id"),
        "status": resp.get("ChangeInfo", {}).get("Status"),
        "submitted": resp.get("ChangeInfo", {}).get("SubmittedAt"),
        "name": name,
        "type": type,
        "values": values,
    }


def delete_record(
    session: boto3.Session,
    *,
    zone_id: str,
    name: str,
    type: str,
    values: list[str],
    ttl: int = 300,
) -> dict[str, Any]:
    r53 = session.client("route53")
    resp = r53.change_resource_record_sets(
        HostedZoneId=zone_id,
        ChangeBatch={
            "Changes": [
                {
                    "Action": "DELETE",
                    "ResourceRecordSet": {
                        "Name": name,
                        "Type": type,
                        "TTL": ttl,
                        "ResourceRecords": [{"Value": v} for v in values],
                    },
                }
            ]
        },
    )
    return {
        "change_id": resp.get("ChangeInfo", {}).get("Id"),
        "status": resp.get("ChangeInfo", {}).get("Status"),
        "deleted": True,
        "name": name,
        "type": type,
    }


def _zone_tags(r53_client, zone_id: str) -> dict[str, str]:
    try:
        resp = r53_client.list_tags_for_resource(
            ResourceType="hostedzone", ResourceId=zone_id
        )
        return tags_from_aws(resp.get("ResourceTagSet", {}).get("Tags"))
    except Exception:
        return {}
