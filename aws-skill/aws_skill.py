#!/usr/bin/env python3
"""aws-skill: a customer-tagged, opinionated CLI over boto3.

Conventions:
    - Reads are free.
    - Writes require --confirm.
    - Deletes require --confirm-delete (separate flag, intentional).
    - Default profile is `epoch` (overridable via --profile or AWS_PROFILE env).
    - Default output is JSON; --format table|markdown|ids overrides.

Run `python3 aws_skill.py setup` first if `~/.aws/` isn't configured yet.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

# Allow running as script (`python3 aws_skill.py ...`) without install.
import os as _os
import sys as _sys
_SKILL_DIR = _os.path.dirname(_os.path.abspath(__file__))
if _SKILL_DIR not in _sys.path:
    _sys.path.insert(0, _SKILL_DIR)

from lib import auth  # noqa: E402
from lib.confirm import (  # noqa: E402
    ConfirmationRequired,
    is_dry_run,
    require_confirm,
    require_confirm_delete,
)
from lib.output import emit, emit_error  # noqa: E402
from lib.services import cost as cost_svc  # noqa: E402
from lib.services import ec2 as ec2_svc  # noqa: E402
from lib.services import iam as iam_svc  # noqa: E402
from lib.intent import jumphost as jumphost_intent  # noqa: E402
from lib.intent import inventory as inventory_intent  # noqa: E402


# ---- Top-level argparse ----------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aws-skill",
        description="Customer-tagged, opinionated CLI over boto3.",
    )
    p.add_argument(
        "--profile",
        default=None,
        help="AWS profile name (default: $AWS_PROFILE or 'epoch').",
    )
    p.add_argument(
        "--region",
        default=None,
        help="AWS region (default: profile region).",
    )
    p.add_argument(
        "--format",
        default="json",
        choices=["json", "table", "markdown", "ids"],
        help="Output format (default: json).",
    )
    p.add_argument(
        "--confirm",
        action="store_true",
        help="Required for write operations.",
    )
    p.add_argument(
        "--confirm-delete",
        action="store_true",
        dest="confirm_delete",
        help="Required for destructive operations.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Preview the operation without executing.",
    )

    sub = p.add_subparsers(dest="command", required=True)

    # setup
    sub.add_parser("setup", help="Initialize ~/.aws/ profile interactively.")

    # iam
    iam = sub.add_parser("iam", help="IAM read operations.").add_subparsers(
        dest="iam_op", required=True
    )
    iam.add_parser("who-am-i", help="STS GetCallerIdentity.")
    iam.add_parser("list-users", help="List IAM users.")
    iam.add_parser("list-roles", help="List IAM roles.")
    p_pol = iam.add_parser("list-policies", help="List managed policies.")
    p_pol.add_argument("--scope", default="Local", choices=["Local", "AWS", "All"])

    # ec2
    ec2 = sub.add_parser("ec2", help="EC2 operations.").add_subparsers(
        dest="ec2_op", required=True
    )
    p_list = ec2.add_parser("list", help="List EC2 instances.")
    p_list.add_argument("--customer", default=None)
    p_list.add_argument("--project", default=None)
    p_list.add_argument(
        "--all", action="store_true", dest="show_all",
        help="Include stopped/terminated instances."
    )
    p_desc = ec2.add_parser("describe", help="Describe a single instance.")
    p_desc.add_argument("instance_id")
    for op in ("start", "stop", "terminate"):
        p_op = ec2.add_parser(op, help=f"{op} an instance.")
        p_op.add_argument("instance_id")
    p_alloc = ec2.add_parser("alloc-eip", help="Allocate an Elastic IP.")
    p_alloc.add_argument("--customer", default=None)
    p_alloc.add_argument("--project", default=None)
    p_assoc = ec2.add_parser("associate-eip", help="Associate EIP with instance.")
    p_assoc.add_argument("--allocation-id", required=True, dest="allocation_id")
    p_assoc.add_argument("--instance-id", required=True, dest="instance_id")
    p_release = ec2.add_parser("release-eip", help="Release an Elastic IP.")
    p_release.add_argument("allocation_id")
    p_addrs = ec2.add_parser("addresses", help="List Elastic IPs.")
    p_addrs.add_argument("--customer", default=None)
    p_addrs.add_argument("--project", default=None)

    # cost
    cost = sub.add_parser("cost", help="Cost Explorer operations.").add_subparsers(
        dest="cost_op", required=True
    )
    p_l30 = cost.add_parser("last-30d", help="Total cost over the last 30 days.")
    p_l30.add_argument("--days", type=int, default=30)
    p_bs = cost.add_parser("by-service", help="Cost grouped by AWS service.")
    p_bs.add_argument("--days", type=int, default=30)
    p_bt = cost.add_parser("by-tag", help="Cost grouped by tag value.")
    p_bt.add_argument("--key", required=True, help="Tag key (e.g. Customer).")
    p_bt.add_argument("--days", type=int, default=30)

    # jumphost
    jh = sub.add_parser(
        "jumphost", help="Customer jump-host provision/teardown."
    ).add_subparsers(dest="jh_op", required=True)
    p_prov = jh.add_parser("provision", help="Provision a jump host for a customer.")
    p_prov.add_argument("--customer", required=True)
    p_prov.add_argument(
        "--allowed-ip", default=None, dest="allowed_ip",
        help="CIDR allowed to SSH (overrides customer config)."
    )
    p_prov.add_argument("--instance-type", default=None, dest="instance_type")
    p_prov.add_argument("--environment", default="dev")
    p_td = jh.add_parser("teardown", help="Tear down a customer's jump host.")
    p_td.add_argument("--customer", required=True)

    # inventory
    inv = sub.add_parser("inventory", help="Tag-based resource listing.")
    inv.add_argument("--customer", default=None)
    inv.add_argument(
        "--tag-key", default=None, dest="tag_key",
        help="Generic tag key for inventory (used with --tag-value)."
    )
    inv.add_argument("--tag-value", default=None, dest="tag_value")

    return p


# ---- Dispatcher ------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # `setup` is special — runs before we attempt to authenticate.
    if args.command == "setup":
        return auth.setup_wizard()

    # All other commands need a session.
    try:
        session = auth.get_session(profile=args.profile, region=args.region)
    except auth.AuthError as e:
        emit_error(str(e), exit_code=2)
        return 2

    try:
        result = _dispatch(session, args)
    except ConfirmationRequired as e:
        emit_error(str(e), exit_code=3)
        return 3
    except FileExistsError as e:
        emit_error(str(e), exit_code=4)
        return 4
    except ValueError as e:
        emit_error(str(e), exit_code=5)
        return 5
    except Exception as e:  # boto3 ClientError, NotImplementedError, etc.
        emit_error(f"{type(e).__name__}: {e}", exit_code=10)
        return 10

    # Output
    columns = _columns_for(args)
    id_key = _id_key_for(args)
    emit(result, fmt=args.format, columns=columns, id_key=id_key)
    return 0


def _dispatch(session, args) -> Any:
    cmd = args.command

    # IAM
    if cmd == "iam":
        if args.iam_op == "who-am-i":
            return iam_svc.who_am_i(session)
        if args.iam_op == "list-users":
            return iam_svc.list_users(session)
        if args.iam_op == "list-roles":
            return iam_svc.list_roles(session)
        if args.iam_op == "list-policies":
            return iam_svc.list_policies(session, scope=args.scope)

    # EC2
    if cmd == "ec2":
        if args.ec2_op == "list":
            return ec2_svc.list_instances(
                session,
                customer=args.customer,
                project=args.project,
                show_all=args.show_all,
            )
        if args.ec2_op == "describe":
            return ec2_svc.describe_instance(session, args.instance_id)
        if args.ec2_op == "addresses":
            return ec2_svc.list_addresses(
                session, customer=args.customer, project=args.project
            )
        if args.ec2_op == "start":
            require_confirm(args, "ec2 start")
            if is_dry_run(args):
                return {"would_start": args.instance_id}
            return ec2_svc.start_instance(session, args.instance_id)
        if args.ec2_op == "stop":
            require_confirm(args, "ec2 stop")
            if is_dry_run(args):
                return {"would_stop": args.instance_id}
            return ec2_svc.stop_instance(session, args.instance_id)
        if args.ec2_op == "terminate":
            require_confirm_delete(args, "ec2 terminate")
            if is_dry_run(args):
                return {"would_terminate": args.instance_id}
            return ec2_svc.terminate_instance(session, args.instance_id)
        if args.ec2_op == "alloc-eip":
            require_confirm(args, "ec2 alloc-eip")
            if is_dry_run(args):
                return {"would_allocate_eip": True}
            return ec2_svc.allocate_eip(session)
        if args.ec2_op == "associate-eip":
            require_confirm(args, "ec2 associate-eip")
            if is_dry_run(args):
                return {
                    "would_associate": {
                        "allocation_id": args.allocation_id,
                        "instance_id": args.instance_id,
                    }
                }
            return ec2_svc.associate_eip(
                session,
                allocation_id=args.allocation_id,
                instance_id=args.instance_id,
            )
        if args.ec2_op == "release-eip":
            require_confirm_delete(args, "ec2 release-eip")
            if is_dry_run(args):
                return {"would_release_eip": args.allocation_id}
            return ec2_svc.release_eip(session, args.allocation_id)

    # Cost
    if cmd == "cost":
        if args.cost_op == "last-30d":
            return cost_svc.total_cost(session, days=args.days)
        if args.cost_op == "by-service":
            return cost_svc.by_service(session, days=args.days)
        if args.cost_op == "by-tag":
            return cost_svc.by_tag(session, tag_key=args.key, days=args.days)

    # Jumphost
    if cmd == "jumphost":
        if args.jh_op == "provision":
            if not is_dry_run(args):
                require_confirm(args, "jumphost provision")
            return jumphost_intent.provision(
                session,
                customer=args.customer,
                allowed_ip=args.allowed_ip,
                instance_type=args.instance_type,
                environment=args.environment,
                dry_run=is_dry_run(args),
            )
        if args.jh_op == "teardown":
            if not is_dry_run(args):
                require_confirm_delete(args, "jumphost teardown")
            return jumphost_intent.teardown(
                session, customer=args.customer, dry_run=is_dry_run(args)
            )

    # Inventory
    if cmd == "inventory":
        if args.customer:
            return inventory_intent.by_customer(session, customer=args.customer)
        if args.tag_key and args.tag_value:
            return inventory_intent.by_tag_value(
                session, tag_key=args.tag_key, tag_value=args.tag_value
            )
        raise ValueError(
            "inventory: pass --customer NAME or --tag-key KEY --tag-value VALUE"
        )

    raise NotImplementedError(f"Unhandled command: {cmd}")


# ---- Output column hints ---------------------------------------------------


def _columns_for(args) -> list[str] | None:
    """Pick columns for table/markdown output. None lets the formatter pick."""
    cmd = args.command
    if cmd == "ec2" and getattr(args, "ec2_op", None) == "list":
        return ["instance_id", "state", "instance_type", "public_ip", "private_ip", "key_name"]
    if cmd == "ec2" and getattr(args, "ec2_op", None) == "addresses":
        return ["allocation_id", "public_ip", "association_id", "instance_id"]
    if cmd == "iam" and getattr(args, "iam_op", None) == "list-users":
        return ["user_name", "user_id", "arn", "created"]
    if cmd == "iam" and getattr(args, "iam_op", None) == "list-roles":
        return ["role_name", "role_id", "arn", "created"]
    if cmd == "iam" and getattr(args, "iam_op", None) == "list-policies":
        return ["policy_name", "arn", "attachment_count"]
    if cmd == "cost" and getattr(args, "cost_op", None) == "by-service":
        return ["service", "amount", "unit"]
    return None


def _id_key_for(args) -> str:
    """Pick the field to use for --format ids."""
    cmd = args.command
    if cmd == "ec2" and getattr(args, "ec2_op", None) == "list":
        return "instance_id"
    if cmd == "ec2" and getattr(args, "ec2_op", None) == "addresses":
        return "allocation_id"
    return "id"


if __name__ == "__main__":
    sys.exit(main())
