"""EC2 service operations.

Includes everything needed for the v1 jumphost intent: instance lifecycle,
EIPs, key pairs, security groups, AMI lookup. All writes require explicit
confirmation upstream (handled in CLI dispatcher via lib.confirm).
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

from ..tagging import (
    tag_filters,
    tags_from_aws,
    to_aws_tag_specifications,
)


# ---- Reads -----------------------------------------------------------------


def list_instances(
    session: boto3.Session,
    *,
    customer: Optional[str] = None,
    project: Optional[str] = None,
    states: Optional[list[str]] = None,
    show_all: bool = False,
) -> list[dict[str, Any]]:
    """List EC2 instances with optional tag filters.

    Default: only show running instances. Pass show_all=True for everything.
    """
    ec2 = session.client("ec2")

    filters = tag_filters(customer=customer, project=project)
    if not show_all:
        # Default to running + pending — what an operator usually cares about.
        filters.append(
            {
                "Name": "instance-state-name",
                "Values": states or ["running", "pending"],
            }
        )
    elif states:
        filters.append({"Name": "instance-state-name", "Values": states})

    out: list[dict[str, Any]] = []
    paginator = ec2.get_paginator("describe_instances")
    kwargs: dict[str, Any] = {"Filters": filters} if filters else {}
    for page in paginator.paginate(**kwargs):
        for reservation in page.get("Reservations", []):
            for inst in reservation.get("Instances", []):
                out.append(_summarize_instance(inst))
    return out


def describe_instance(session: boto3.Session, instance_id: str) -> dict[str, Any]:
    ec2 = session.client("ec2")
    resp = ec2.describe_instances(InstanceIds=[instance_id])
    for reservation in resp.get("Reservations", []):
        for inst in reservation.get("Instances", []):
            return _summarize_instance(inst, full=True)
    raise ValueError(f"No instance found with ID {instance_id}")


def list_addresses(
    session: boto3.Session,
    *,
    customer: Optional[str] = None,
    project: Optional[str] = None,
) -> list[dict[str, Any]]:
    ec2 = session.client("ec2")
    filters = tag_filters(customer=customer, project=project)
    kwargs = {"Filters": filters} if filters else {}
    resp = ec2.describe_addresses(**kwargs)
    return [_summarize_address(a) for a in resp.get("Addresses", [])]


# ---- Writes (must be guarded by --confirm upstream) ------------------------


def start_instance(session: boto3.Session, instance_id: str) -> dict[str, Any]:
    ec2 = session.client("ec2")
    resp = ec2.start_instances(InstanceIds=[instance_id])
    return {"changes": resp.get("StartingInstances", [])}


def stop_instance(session: boto3.Session, instance_id: str) -> dict[str, Any]:
    ec2 = session.client("ec2")
    resp = ec2.stop_instances(InstanceIds=[instance_id])
    return {"changes": resp.get("StoppingInstances", [])}


def terminate_instance(session: boto3.Session, instance_id: str) -> dict[str, Any]:
    ec2 = session.client("ec2")
    resp = ec2.terminate_instances(InstanceIds=[instance_id])
    return {"changes": resp.get("TerminatingInstances", [])}


def resize_instance(
    session: boto3.Session,
    instance_id: str,
    *,
    instance_type: str,
) -> dict[str, Any]:
    """Change an instance's type. Requires the instance to be stopped.

    Stops it if needed, modifies the type, restarts. EIP / SG / key pair /
    EBS / private IP all survive. Public EIP-associated IP is unchanged.
    """
    ec2 = session.client("ec2")

    # 1) Find current state + type.
    desc = ec2.describe_instances(InstanceIds=[instance_id])
    inst = desc["Reservations"][0]["Instances"][0]
    state = inst["State"]["Name"]
    old_type = inst["InstanceType"]

    actions: list[dict[str, Any]] = [
        {"current_type": old_type, "current_state": state, "target_type": instance_type}
    ]

    if old_type == instance_type:
        actions.append({"noop": "instance is already this type"})
        return {"instance_id": instance_id, "actions": actions}

    # 2) Stop if running.
    was_running = state in {"running", "pending"}
    if was_running:
        ec2.stop_instances(InstanceIds=[instance_id])
        ec2.get_waiter("instance_stopped").wait(InstanceIds=[instance_id])
        actions.append({"stopped": instance_id})

    # 3) Modify instance type.
    ec2.modify_instance_attribute(
        InstanceId=instance_id,
        InstanceType={"Value": instance_type},
    )
    actions.append({"resized_to": instance_type})

    # 4) Restart if it had been running.
    if was_running:
        ec2.start_instances(InstanceIds=[instance_id])
        ec2.get_waiter("instance_running").wait(InstanceIds=[instance_id])
        actions.append({"started": instance_id})

    return {
        "instance_id": instance_id,
        "old_type": old_type,
        "new_type": instance_type,
        "actions": actions,
    }


def allocate_eip(
    session: boto3.Session, *, tags: Optional[dict[str, str]] = None
) -> dict[str, Any]:
    ec2 = session.client("ec2")
    kwargs: dict[str, Any] = {"Domain": "vpc"}
    if tags:
        kwargs["TagSpecifications"] = to_aws_tag_specifications(["elastic-ip"], tags)
    resp = ec2.allocate_address(**kwargs)
    return {
        "allocation_id": resp.get("AllocationId"),
        "public_ip": resp.get("PublicIp"),
        "domain": resp.get("Domain"),
    }


def release_eip(session: boto3.Session, allocation_id: str) -> dict[str, Any]:
    ec2 = session.client("ec2")
    ec2.release_address(AllocationId=allocation_id)
    return {"released": allocation_id}


def associate_eip(
    session: boto3.Session, *, allocation_id: str, instance_id: str
) -> dict[str, Any]:
    ec2 = session.client("ec2")
    resp = ec2.associate_address(
        AllocationId=allocation_id, InstanceId=instance_id, AllowReassociation=False
    )
    return {
        "association_id": resp.get("AssociationId"),
        "allocation_id": allocation_id,
        "instance_id": instance_id,
    }


def disassociate_eip(session: boto3.Session, association_id: str) -> dict[str, Any]:
    ec2 = session.client("ec2")
    ec2.disassociate_address(AssociationId=association_id)
    return {"disassociated": association_id}


# ---- Key pairs -------------------------------------------------------------


def create_key_pair(
    session: boto3.Session,
    *,
    key_name: str,
    save_path: Optional[Path] = None,
    tags: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Create an EC2 key pair and optionally save the private material to disk."""
    ec2 = session.client("ec2")
    kwargs: dict[str, Any] = {"KeyName": key_name, "KeyType": "ed25519"}
    if tags:
        kwargs["TagSpecifications"] = to_aws_tag_specifications(["key-pair"], tags)

    resp = ec2.create_key_pair(**kwargs)
    out: dict[str, Any] = {
        "key_name": resp.get("KeyName"),
        "key_pair_id": resp.get("KeyPairId"),
        "key_fingerprint": resp.get("KeyFingerprint"),
    }
    material = resp.get("KeyMaterial")
    if save_path and material:
        save_path = Path(save_path).expanduser()
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(material)
        save_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
        out["private_key_path"] = str(save_path)
    elif material:
        # No save path — return material in response so the caller can stash it.
        out["private_key_material"] = material
    return out


def delete_key_pair(session: boto3.Session, key_name: str) -> dict[str, Any]:
    ec2 = session.client("ec2")
    ec2.delete_key_pair(KeyName=key_name)
    return {"deleted_key_name": key_name}


# ---- Security groups -------------------------------------------------------


def create_security_group(
    session: boto3.Session,
    *,
    name: str,
    description: str,
    vpc_id: Optional[str] = None,
    tags: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    ec2 = session.client("ec2")
    kwargs: dict[str, Any] = {"GroupName": name, "Description": description}
    if vpc_id:
        kwargs["VpcId"] = vpc_id
    else:
        # Use the default VPC if no VPC ID provided.
        default_vpc = _default_vpc_id(session)
        if default_vpc:
            kwargs["VpcId"] = default_vpc
    if tags:
        kwargs["TagSpecifications"] = to_aws_tag_specifications(
            ["security-group"], tags
        )
    resp = ec2.create_security_group(**kwargs)
    return {
        "group_id": resp.get("GroupId"),
        "vpc_id": kwargs.get("VpcId"),
        "name": name,
    }


def authorize_ingress(
    session: boto3.Session,
    *,
    group_id: str,
    cidr: str,
    port: int,
    protocol: str = "tcp",
) -> dict[str, Any]:
    ec2 = session.client("ec2")
    ec2.authorize_security_group_ingress(
        GroupId=group_id,
        IpPermissions=[
            {
                "IpProtocol": protocol,
                "FromPort": port,
                "ToPort": port,
                "IpRanges": [{"CidrIp": cidr, "Description": "aws-skill ingress"}],
            }
        ],
    )
    return {
        "group_id": group_id,
        "added": {"cidr": cidr, "port": port, "protocol": protocol},
    }


def delete_security_group(session: boto3.Session, group_id: str) -> dict[str, Any]:
    ec2 = session.client("ec2")
    ec2.delete_security_group(GroupId=group_id)
    return {"deleted_group_id": group_id}


def list_security_groups(
    session: boto3.Session,
    *,
    customer: Optional[str] = None,
    project: Optional[str] = None,
) -> list[dict[str, Any]]:
    ec2 = session.client("ec2")
    filters = tag_filters(customer=customer, project=project)
    kwargs = {"Filters": filters} if filters else {}
    resp = ec2.describe_security_groups(**kwargs)
    return [
        {
            "group_id": g.get("GroupId"),
            "name": g.get("GroupName"),
            "description": g.get("Description"),
            "vpc_id": g.get("VpcId"),
            "tags": tags_from_aws(g.get("Tags")),
        }
        for g in resp.get("SecurityGroups", [])
    ]


# ---- AMI lookup ------------------------------------------------------------


def latest_ubuntu_lts_ami(session: boto3.Session) -> str:
    """Find the latest Ubuntu 22.04 LTS Jammy ARM64 AMI in the session's region.

    Returns AMI ID. Falls back to x86_64 if ARM isn't found.
    """
    ec2 = session.client("ec2")
    # Canonical's owner ID is 099720109477.
    for arch, name in (
        ("arm64", "ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-arm64-server-*"),
        ("x86_64", "ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"),
    ):
        try:
            resp = ec2.describe_images(
                Owners=["099720109477"],
                Filters=[
                    {"Name": "name", "Values": [name]},
                    {"Name": "state", "Values": ["available"]},
                    {"Name": "architecture", "Values": [arch]},
                ],
            )
            images = sorted(
                resp.get("Images", []),
                key=lambda i: i.get("CreationDate", ""),
                reverse=True,
            )
            if images:
                return images[0]["ImageId"]
        except ClientError:
            continue
    raise RuntimeError("Could not find a Ubuntu 22.04 LTS AMI in this region.")


# ---- Run instance (used by jumphost intent) --------------------------------


def run_instance(
    session: boto3.Session,
    *,
    image_id: str,
    instance_type: str,
    key_name: str,
    security_group_ids: list[str],
    user_data: Optional[str] = None,
    subnet_id: Optional[str] = None,
    tags: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    ec2 = session.client("ec2")
    kwargs: dict[str, Any] = {
        "ImageId": image_id,
        "InstanceType": instance_type,
        "KeyName": key_name,
        "SecurityGroupIds": security_group_ids,
        "MinCount": 1,
        "MaxCount": 1,
        "MetadataOptions": {
            "HttpTokens": "required",
            "HttpEndpoint": "enabled",
            "InstanceMetadataTags": "enabled",
        },
        "BlockDeviceMappings": [
            {
                "DeviceName": "/dev/sda1",
                "Ebs": {
                    "VolumeSize": 20,
                    "VolumeType": "gp3",
                    "Encrypted": True,
                    "DeleteOnTermination": True,
                },
            }
        ],
    }
    if user_data:
        kwargs["UserData"] = user_data
    if subnet_id:
        kwargs["SubnetId"] = subnet_id
    if tags:
        kwargs["TagSpecifications"] = to_aws_tag_specifications(
            ["instance", "volume"], tags
        )
    resp = ec2.run_instances(**kwargs)
    instances = resp.get("Instances", [])
    if not instances:
        raise RuntimeError("run_instances returned no instances.")
    inst = instances[0]
    return {
        "instance_id": inst.get("InstanceId"),
        "state": inst.get("State", {}).get("Name"),
        "private_ip": inst.get("PrivateIpAddress"),
        "subnet_id": inst.get("SubnetId"),
        "vpc_id": inst.get("VpcId"),
    }


def wait_for_instance_running(session: boto3.Session, instance_id: str) -> None:
    ec2 = session.client("ec2")
    waiter = ec2.get_waiter("instance_running")
    waiter.wait(InstanceIds=[instance_id])


# ---- Internals -------------------------------------------------------------


def _summarize_instance(inst: dict, *, full: bool = False) -> dict:
    out = {
        "instance_id": inst.get("InstanceId"),
        "state": inst.get("State", {}).get("Name"),
        "instance_type": inst.get("InstanceType"),
        "public_ip": inst.get("PublicIpAddress"),
        "private_ip": inst.get("PrivateIpAddress"),
        "key_name": inst.get("KeyName"),
        "launch_time": inst.get("LaunchTime"),
        "tags": tags_from_aws(inst.get("Tags")),
    }
    if full:
        out.update(
            {
                "vpc_id": inst.get("VpcId"),
                "subnet_id": inst.get("SubnetId"),
                "image_id": inst.get("ImageId"),
                "security_groups": [
                    {"id": sg.get("GroupId"), "name": sg.get("GroupName")}
                    for sg in inst.get("SecurityGroups", [])
                ],
                "iam_instance_profile": (
                    inst.get("IamInstanceProfile", {}).get("Arn")
                    if inst.get("IamInstanceProfile")
                    else None
                ),
                "architecture": inst.get("Architecture"),
                "platform_details": inst.get("PlatformDetails"),
            }
        )
    return out


def _summarize_address(addr: dict) -> dict:
    return {
        "allocation_id": addr.get("AllocationId"),
        "public_ip": addr.get("PublicIp"),
        "association_id": addr.get("AssociationId"),
        "instance_id": addr.get("InstanceId"),
        "domain": addr.get("Domain"),
        "tags": tags_from_aws(addr.get("Tags")),
    }


def _default_vpc_id(session: boto3.Session) -> Optional[str]:
    ec2 = session.client("ec2")
    resp = ec2.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])
    vpcs = resp.get("Vpcs", [])
    return vpcs[0].get("VpcId") if vpcs else None
