"""Jumphost intent: provision and teardown a customer-tagged jump host.

Composes EC2 primitives (key pair + security group + run-instance + EIP +
associate-EIP) into a single idempotent verb. Every resource carries the
required-tag set (Customer / Project / Owner / Environment / ManagedBy).

Convention: Project tag is always 'jumphost' for these resources, so
teardown can reliably find them via tag filter.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

from .. import tagging
from ..services import ec2

JUMPHOST_PROJECT = "jumphost"


def _customer_cfg(customer: str) -> dict[str, Any]:
    cfg = tagging.load_customer_config(customer)
    if not cfg:
        raise ValueError(
            f"No customer config found at customers/{customer}.json. "
            f"Copy templates/customer-config.example.json and edit."
        )
    return cfg


def _resource_name(prefix: str, suffix: str) -> str:
    return f"{prefix}-jumphost-{suffix}"


def provision(
    session: boto3.Session,
    *,
    customer: str,
    allowed_ip: Optional[str] = None,
    instance_type: Optional[str] = None,
    environment: str = "dev",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Provision a complete jump host. Idempotent in the sense that it tags
    everything; re-running creates a NEW set unless you teardown first.

    Returns a dict with the created resource IDs and an SSH connection hint.
    """
    cfg = _customer_cfg(customer)
    region = cfg.get("region")
    naming_prefix = cfg.get("naming_prefix", customer)
    jh_cfg = cfg.get("jumphost", {})
    instance_type = (
        instance_type or jh_cfg.get("instance_type") or "t4g.small"
    )
    allowed = allowed_ip or (jh_cfg.get("allowed_ingress") or [None])[0]
    if not allowed:
        raise ValueError(
            "No allowed-ingress CIDR. Pass --allowed-ip or set "
            f"customers/{customer}.json jumphost.allowed_ingress."
        )
    ssh_key_path = Path(
        jh_cfg.get("ssh_key_path", f"~/.ssh/aws-skill-{customer}-jumphost")
    ).expanduser()

    tags = tagging.build_tags(
        customer=customer,
        project=JUMPHOST_PROJECT,
        environment=environment,
    )

    plan = {
        "customer": customer,
        "region": region or session.region_name,
        "instance_type": instance_type,
        "allowed_ip": allowed,
        "tags": tags,
        "ssh_key_path": str(ssh_key_path),
        "naming_prefix": naming_prefix,
        "actions": [
            "create EC2 key pair",
            "create security group + ingress rule (port 22 from allowed IP)",
            "look up latest Ubuntu 22.04 LTS AMI",
            "render cloud-init from templates/jumphost-userdata.sh",
            "run EC2 instance",
            "wait for running state",
            "allocate Elastic IP",
            "associate EIP to instance",
        ],
    }
    if dry_run:
        plan["dry_run"] = True
        return plan

    # If the session region isn't set but customer config has one, build a
    # new session in the right region.
    if region and (session.region_name != region):
        session = boto3.Session(profile_name=session.profile_name, region_name=region)

    created: dict[str, Any] = {"customer": customer, "region": session.region_name}

    # 1) key pair
    if ssh_key_path.exists():
        raise FileExistsError(
            f"SSH key already exists at {ssh_key_path}. Refusing to overwrite. "
            f"Either pass a different path or delete the existing file."
        )
    key_name = _resource_name(naming_prefix, "key")
    kp = ec2.create_key_pair(
        session, key_name=key_name, save_path=ssh_key_path, tags=tags
    )
    created["key_pair"] = kp

    # 2) security group + ingress
    sg_name = _resource_name(naming_prefix, "sg")
    sg = ec2.create_security_group(
        session,
        name=sg_name,
        description=f"aws-skill jumphost SG for {customer}",
        tags=tags,
    )
    created["security_group"] = sg
    ec2.authorize_ingress(
        session, group_id=sg["group_id"], cidr=allowed, port=22, protocol="tcp"
    )
    created["ingress"] = {"cidr": allowed, "port": 22}

    # 3) AMI
    image_id = ec2.latest_ubuntu_lts_ami(session)
    created["ami_id"] = image_id

    # 4) user-data
    user_data = _render_user_data(
        hostname=_resource_name(naming_prefix, "host"),
        allowed_ip=allowed,
    )

    # 5) run instance
    inst = ec2.run_instance(
        session,
        image_id=image_id,
        instance_type=instance_type,
        key_name=key_name,
        security_group_ids=[sg["group_id"]],
        user_data=user_data,
        tags=tags,
    )
    created["instance"] = inst

    # 6) wait for running
    ec2.wait_for_instance_running(session, inst["instance_id"])

    # 7) allocate + associate EIP
    eip = ec2.allocate_eip(session, tags=tags)
    created["eip"] = eip
    assoc = ec2.associate_eip(
        session,
        allocation_id=eip["allocation_id"],
        instance_id=inst["instance_id"],
    )
    created["association"] = assoc

    # SSH hint
    created["ssh_hint"] = (
        f"ssh -i {ssh_key_path} ubuntu@{eip['public_ip']}"
    )
    created["next_steps"] = [
        f"Verify SSH connectivity: {created['ssh_hint']}",
        f"Expect ~60-120s for cloud-init (apt + fail2ban + ufw) to finish.",
        f"Marker file on host: /var/log/aws-skill-jumphost-ready",
    ]
    return created


def teardown(
    session: boto3.Session,
    *,
    customer: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Tear down everything tagged Customer=<name> Project=jumphost.

    Order matters: disassociate + release EIP first, terminate instance,
    delete SG, delete key pair.
    """
    cfg = _customer_cfg(customer)
    region = cfg.get("region")
    if region and (session.region_name != region):
        session = boto3.Session(profile_name=session.profile_name, region_name=region)

    instances = ec2.list_instances(
        session, customer=customer, project=JUMPHOST_PROJECT, show_all=True
    )
    addresses = ec2.list_addresses(
        session, customer=customer, project=JUMPHOST_PROJECT
    )
    sgs = ec2.list_security_groups(
        session, customer=customer, project=JUMPHOST_PROJECT
    )

    plan = {
        "customer": customer,
        "region": session.region_name,
        "instances_to_terminate": [i["instance_id"] for i in instances],
        "eips_to_release": [a["allocation_id"] for a in addresses],
        "security_groups_to_delete": [s["group_id"] for s in sgs],
        "key_pairs_referenced": sorted({i.get("key_name") for i in instances if i.get("key_name")}),
    }
    if dry_run:
        plan["dry_run"] = True
        return plan

    actions: list[dict[str, Any]] = []

    # 1) disassociate + release EIPs
    ec2_client = session.client("ec2")
    for addr in addresses:
        if addr.get("association_id"):
            try:
                ec2.disassociate_eip(session, addr["association_id"])
                actions.append(
                    {"disassociated": addr["association_id"]}
                )
            except ClientError as e:
                actions.append(
                    {"warn": f"disassociate {addr['association_id']}: {e}"}
                )
        if addr.get("allocation_id"):
            try:
                ec2.release_eip(session, addr["allocation_id"])
                actions.append({"released_eip": addr["allocation_id"]})
            except ClientError as e:
                actions.append({"warn": f"release {addr['allocation_id']}: {e}"})

    # 2) terminate instances
    for inst in instances:
        if inst["state"] in {"terminated", "shutting-down"}:
            continue
        try:
            ec2.terminate_instance(session, inst["instance_id"])
            actions.append({"terminating": inst["instance_id"]})
        except ClientError as e:
            actions.append({"warn": f"terminate {inst['instance_id']}: {e}"})

    # Wait for instances to terminate before deleting SGs (SGs can't be
    # deleted while attached).
    if instances:
        try:
            waiter = ec2_client.get_waiter("instance_terminated")
            waiter.wait(InstanceIds=[i["instance_id"] for i in instances])
            actions.append({"all_instances_terminated": True})
        except ClientError as e:
            actions.append({"warn": f"wait_for_terminated: {e}"})

    # 3) delete security groups
    for sg in sgs:
        try:
            ec2.delete_security_group(session, sg["group_id"])
            actions.append({"deleted_sg": sg["group_id"]})
        except ClientError as e:
            actions.append({"warn": f"delete sg {sg['group_id']}: {e}"})

    # 4) delete key pairs (the ones referenced by torn-down instances)
    for key_name in {i.get("key_name") for i in instances if i.get("key_name")}:
        try:
            ec2.delete_key_pair(session, key_name)
            actions.append({"deleted_key_pair": key_name})
        except ClientError as e:
            actions.append({"warn": f"delete key {key_name}: {e}"})

    return {
        "customer": customer,
        "region": session.region_name,
        "plan": plan,
        "actions": actions,
        "ssh_key_files_local": (
            "Local SSH private key files were NOT deleted. "
            "Remove manually if appropriate: "
            f"~/.ssh/aws-skill-{customer}-jumphost"
        ),
    }


def _render_user_data(*, hostname: str, allowed_ip: str) -> str:
    template_path = (
        Path(__file__).resolve().parents[2]
        / "templates"
        / "jumphost-userdata.sh"
    )
    text = template_path.read_text()
    return (
        text.replace("{{HOSTNAME}}", hostname)
        .replace("{{ALLOWED_IP}}", allowed_ip)
    )
