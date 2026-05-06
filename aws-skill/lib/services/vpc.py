"""VPC service operations.

VPCs / subnets / route tables / NAT gateways. Security groups already
covered by ec2.py (they're EC2-flavored APIs).
"""
from __future__ import annotations

from typing import Any, Optional

import boto3

from ..tagging import tag_filters, tags_from_aws


def list_vpcs(
    session: boto3.Session,
    *,
    customer: Optional[str] = None,
) -> list[dict[str, Any]]:
    ec2 = session.client("ec2")
    filters = tag_filters(customer=customer)
    kwargs = {"Filters": filters} if filters else {}
    resp = ec2.describe_vpcs(**kwargs)
    return [
        {
            "vpc_id": v.get("VpcId"),
            "cidr": v.get("CidrBlock"),
            "is_default": v.get("IsDefault"),
            "state": v.get("State"),
            "tags": tags_from_aws(v.get("Tags")),
        }
        for v in resp.get("Vpcs", [])
    ]


def list_subnets(
    session: boto3.Session,
    *,
    vpc_id: Optional[str] = None,
    customer: Optional[str] = None,
) -> list[dict[str, Any]]:
    ec2 = session.client("ec2")
    filters = tag_filters(customer=customer)
    if vpc_id:
        filters.append({"Name": "vpc-id", "Values": [vpc_id]})
    kwargs = {"Filters": filters} if filters else {}
    resp = ec2.describe_subnets(**kwargs)
    return [
        {
            "subnet_id": s.get("SubnetId"),
            "vpc_id": s.get("VpcId"),
            "cidr": s.get("CidrBlock"),
            "az": s.get("AvailabilityZone"),
            "available_ips": s.get("AvailableIpAddressCount"),
            "map_public_ip_on_launch": s.get("MapPublicIpOnLaunch"),
            "tags": tags_from_aws(s.get("Tags")),
        }
        for s in resp.get("Subnets", [])
    ]


def list_route_tables(
    session: boto3.Session,
    *,
    vpc_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    ec2 = session.client("ec2")
    filters = []
    if vpc_id:
        filters.append({"Name": "vpc-id", "Values": [vpc_id]})
    kwargs = {"Filters": filters} if filters else {}
    resp = ec2.describe_route_tables(**kwargs)
    return [
        {
            "route_table_id": rt.get("RouteTableId"),
            "vpc_id": rt.get("VpcId"),
            "associations": [
                {
                    "id": a.get("RouteTableAssociationId"),
                    "subnet_id": a.get("SubnetId"),
                    "main": a.get("Main"),
                }
                for a in rt.get("Associations", [])
            ],
            "routes": [
                {
                    "destination": r.get("DestinationCidrBlock")
                    or r.get("DestinationIpv6CidrBlock"),
                    "target": _route_target(r),
                    "state": r.get("State"),
                }
                for r in rt.get("Routes", [])
            ],
            "tags": tags_from_aws(rt.get("Tags")),
        }
        for rt in resp.get("RouteTables", [])
    ]


def list_nat_gateways(
    session: boto3.Session,
    *,
    vpc_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    ec2 = session.client("ec2")
    filters = []
    if vpc_id:
        filters.append({"Name": "vpc-id", "Values": [vpc_id]})
    kwargs = {"Filter": filters} if filters else {}
    resp = ec2.describe_nat_gateways(**kwargs)
    return [
        {
            "nat_id": n.get("NatGatewayId"),
            "vpc_id": n.get("VpcId"),
            "subnet_id": n.get("SubnetId"),
            "state": n.get("State"),
            "public_ip": (n.get("NatGatewayAddresses") or [{}])[0].get("PublicIp"),
            "private_ip": (n.get("NatGatewayAddresses") or [{}])[0].get("PrivateIp"),
            "created": n.get("CreateTime"),
            "tags": tags_from_aws(n.get("Tags")),
        }
        for n in resp.get("NatGateways", [])
    ]


def _route_target(r: dict) -> Optional[str]:
    for k in (
        "GatewayId",
        "NatGatewayId",
        "TransitGatewayId",
        "VpcPeeringConnectionId",
        "NetworkInterfaceId",
        "InstanceId",
    ):
        if r.get(k):
            return r.get(k)
    return None
