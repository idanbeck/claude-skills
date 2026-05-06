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
from pathlib import Path
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

from lib.services import cloudwatch as cloudwatch_svc  # noqa: E402
from lib.services import cost as cost_svc  # noqa: E402
from lib.services import ec2 as ec2_svc  # noqa: E402
from lib.services import ecr as ecr_svc  # noqa: E402
from lib.services import eks as eks_svc  # noqa: E402
from lib.services import iam as iam_svc  # noqa: E402
from lib.services import lambda_ops as lambda_svc  # noqa: E402
from lib.services import rds as rds_svc  # noqa: E402
from lib.services import route53 as route53_svc  # noqa: E402
from lib.services import s3 as s3_svc  # noqa: E402
from lib.services import vpc as vpc_svc  # noqa: E402

from lib.intent import audit as audit_intent  # noqa: E402
from lib.intent import cleanup as cleanup_intent  # noqa: E402
from lib.intent import cost_report as cost_report_intent  # noqa: E402
from lib.intent import inventory as inventory_intent  # noqa: E402
from lib.intent import jumphost as jumphost_intent  # noqa: E402
from lib.intent import terraform as terraform_intent  # noqa: E402


# ---- Top-level argparse ----------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aws-skill",
        description="Customer-tagged, opinionated CLI over boto3.",
    )
    p.add_argument("--profile", default=None,
                   help="AWS profile name (default: $AWS_PROFILE or 'epoch').")
    p.add_argument("--region", default=None,
                   help="AWS region (default: profile region).")
    p.add_argument("--format", default="json",
                   choices=["json", "table", "markdown", "ids"],
                   help="Output format (default: json).")
    p.add_argument("--confirm", action="store_true",
                   help="Required for write operations.")
    p.add_argument("--confirm-delete", action="store_true", dest="confirm_delete",
                   help="Required for destructive operations.")
    p.add_argument("--dry-run", action="store_true", dest="dry_run",
                   help="Preview the operation without executing.")

    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="Initialize ~/.aws/ profile interactively.")

    _build_iam(sub)
    _build_ec2(sub)
    _build_s3(sub)
    _build_rds(sub)
    _build_lambda(sub)
    _build_vpc(sub)
    _build_route53(sub)
    _build_cloudwatch(sub)
    _build_ecr(sub)
    _build_eks(sub)
    _build_cost(sub)
    _build_jumphost(sub)
    _build_inventory(sub)
    _build_cleanup(sub)
    _build_audit(sub)
    _build_terraform(sub)

    return p


# ---- Subparser builders (one per service / intent) -------------------------


def _build_iam(sub) -> None:
    iam = sub.add_parser("iam", help="IAM read operations.").add_subparsers(
        dest="iam_op", required=True
    )
    iam.add_parser("who-am-i", help="STS GetCallerIdentity.")
    iam.add_parser("list-users", help="List IAM users.")
    iam.add_parser("list-roles", help="List IAM roles.")
    p_pol = iam.add_parser("list-policies", help="List managed policies.")
    p_pol.add_argument("--scope", default="Local", choices=["Local", "AWS", "All"])


def _build_ec2(sub) -> None:
    ec2 = sub.add_parser("ec2", help="EC2 operations.").add_subparsers(
        dest="ec2_op", required=True
    )
    p_list = ec2.add_parser("list", help="List EC2 instances.")
    p_list.add_argument("--customer", default=None)
    p_list.add_argument("--project", default=None)
    p_list.add_argument("--all", action="store_true", dest="show_all",
                        help="Include stopped/terminated instances.")
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


def _build_s3(sub) -> None:
    s3 = sub.add_parser("s3", help="S3 operations.").add_subparsers(
        dest="s3_op", required=True
    )
    s3.add_parser("ls-buckets", help="List buckets.")
    p_ls = s3.add_parser("ls", help="List objects in a bucket.")
    p_ls.add_argument("bucket")
    p_ls.add_argument("--prefix", default=None)
    p_ls.add_argument("--max", type=int, default=1000, dest="max_items")
    p_head = s3.add_parser("head", help="Head object metadata.")
    p_head.add_argument("bucket")
    p_head.add_argument("key")
    p_get = s3.add_parser("get", help="Download an object.")
    p_get.add_argument("bucket")
    p_get.add_argument("key")
    p_get.add_argument("--out", required=True, dest="out_path")
    p_put = s3.add_parser("put", help="Upload a file.")
    p_put.add_argument("bucket")
    p_put.add_argument("key")
    p_put.add_argument("src_path")
    p_rm = s3.add_parser("rm", help="Delete an object.")
    p_rm.add_argument("bucket")
    p_rm.add_argument("key")
    p_pub = s3.add_parser("public-status", help="Assess bucket public-access exposure.")
    p_pub.add_argument("bucket")


def _build_rds(sub) -> None:
    rds = sub.add_parser("rds", help="RDS operations.").add_subparsers(
        dest="rds_op", required=True
    )
    p_list = rds.add_parser("list", help="List RDS instances.")
    p_list.add_argument("--customer", default=None)
    p_desc = rds.add_parser("describe", help="Describe an RDS instance.")
    p_desc.add_argument("instance_id")
    p_snap = rds.add_parser("snapshot", help="Create a manual snapshot.")
    p_snap.add_argument("instance_id")
    p_snap.add_argument("--name", default=None, dest="snapshot_id")
    p_snaps = rds.add_parser("list-snapshots", help="List snapshots.")
    p_snaps.add_argument("--instance-id", default=None, dest="instance_id")


def _build_lambda(sub) -> None:
    lam = sub.add_parser("lambda", help="Lambda operations.").add_subparsers(
        dest="lambda_op", required=True
    )
    p_list = lam.add_parser("list", help="List functions.")
    p_list.add_argument("--customer", default=None)
    p_get = lam.add_parser("get", help="Describe a function.")
    p_get.add_argument("name")
    p_inv = lam.add_parser("invoke", help="Invoke a function.")
    p_inv.add_argument("name")
    p_inv.add_argument("--payload", default=None,
                       help="JSON payload (string or @path).")
    p_inv.add_argument("--invocation-type", default="RequestResponse",
                       choices=["RequestResponse", "Event", "DryRun"],
                       dest="invocation_type")
    p_logs = lam.add_parser("logs", help="Tail recent logs.")
    p_logs.add_argument("name")
    p_logs.add_argument("--since", default="1h")
    p_logs.add_argument("--limit", type=int, default=200)


def _build_vpc(sub) -> None:
    vpc = sub.add_parser("vpc", help="VPC operations.").add_subparsers(
        dest="vpc_op", required=True
    )
    p_list = vpc.add_parser("list", help="List VPCs.")
    p_list.add_argument("--customer", default=None)
    p_subs = vpc.add_parser("subnets", help="List subnets.")
    p_subs.add_argument("--vpc-id", default=None, dest="vpc_id")
    p_subs.add_argument("--customer", default=None)
    p_rt = vpc.add_parser("route-tables", help="List route tables.")
    p_rt.add_argument("--vpc-id", default=None, dest="vpc_id")
    p_nat = vpc.add_parser("nat", help="List NAT gateways.")
    p_nat.add_argument("--vpc-id", default=None, dest="vpc_id")


def _build_route53(sub) -> None:
    r53 = sub.add_parser("route53", help="Route 53 operations.").add_subparsers(
        dest="r53_op", required=True
    )
    r53.add_parser("zones", help="List hosted zones.")
    p_recs = r53.add_parser("records", help="List records in a zone.")
    p_recs.add_argument("--zone-id", required=True, dest="zone_id")
    p_up = r53.add_parser("upsert", help="Create or update a record.")
    p_up.add_argument("--zone-id", required=True, dest="zone_id")
    p_up.add_argument("--name", required=True)
    p_up.add_argument("--type", required=True)
    p_up.add_argument("--value", action="append", required=True, dest="values")
    p_up.add_argument("--ttl", type=int, default=300)
    p_del = r53.add_parser("delete", help="Delete a record.")
    p_del.add_argument("--zone-id", required=True, dest="zone_id")
    p_del.add_argument("--name", required=True)
    p_del.add_argument("--type", required=True)
    p_del.add_argument("--value", action="append", required=True, dest="values")
    p_del.add_argument("--ttl", type=int, default=300)


def _build_cloudwatch(sub) -> None:
    cw = sub.add_parser("cloudwatch", help="CloudWatch operations.").add_subparsers(
        dest="cw_op", required=True
    )
    p_lg = cw.add_parser("log-groups", help="List log groups.")
    p_lg.add_argument("--prefix", default=None, dest="name_prefix")
    p_logs = cw.add_parser("logs", help="Tail a log group.")
    p_logs.add_argument("log_group")
    p_logs.add_argument("--since", default="1h")
    p_logs.add_argument("--limit", type=int, default=500)
    p_logs.add_argument("--filter", default=None, dest="filter_pattern")
    p_metric = cw.add_parser("metric", help="Get metric statistics.")
    p_metric.add_argument("--namespace", required=True)
    p_metric.add_argument("--name", required=True, dest="metric_name")
    p_metric.add_argument("--days", type=int, default=1)
    p_metric.add_argument("--period", type=int, default=300, dest="period_seconds")


def _build_ecr(sub) -> None:
    ecr = sub.add_parser("ecr", help="ECR operations.").add_subparsers(
        dest="ecr_op", required=True
    )
    ecr.add_parser("list", help="List repositories.")
    p_imgs = ecr.add_parser("images", help="List images in a repo.")
    p_imgs.add_argument("repo")
    p_imgs.add_argument("--limit", type=int, default=50)
    ecr.add_parser("login", help="Get docker login command (12h token).")


def _build_eks(sub) -> None:
    eks = sub.add_parser("eks", help="EKS operations.").add_subparsers(
        dest="eks_op", required=True
    )
    p_list = eks.add_parser("list", help="List EKS clusters.")
    p_list.add_argument("--customer", default=None)
    p_kc = eks.add_parser("kubeconfig", help="Write kubeconfig for a cluster.")
    p_kc.add_argument("cluster_name")
    p_kc.add_argument("--out", default=None, dest="kubeconfig_path")


def _build_cost(sub) -> None:
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
    p_rep = cost.add_parser("report", help="Per-customer cost report (intent).")
    p_rep.add_argument("--customer", required=True)
    p_rep.add_argument("--days", type=int, default=30)


def _build_jumphost(sub) -> None:
    jh = sub.add_parser("jumphost",
                        help="Customer jump-host provision/teardown.").add_subparsers(
        dest="jh_op", required=True
    )
    p_prov = jh.add_parser("provision", help="Provision a jump host.")
    p_prov.add_argument("--customer", required=True)
    p_prov.add_argument("--allowed-ip", default=None, dest="allowed_ip")
    p_prov.add_argument("--instance-type", default=None, dest="instance_type")
    p_prov.add_argument("--environment", default="dev")
    p_td = jh.add_parser("teardown", help="Tear down a jump host.")
    p_td.add_argument("--customer", required=True)
    p_tf = jh.add_parser("terraform",
                         help="Render the jumphost as Terraform instead of executing.")
    p_tf.add_argument("--customer", required=True)
    p_tf.add_argument("--allowed-ip", default=None, dest="allowed_ip")
    p_tf.add_argument("--instance-type", default=None, dest="instance_type")
    p_tf.add_argument("--environment", default="dev")
    p_tf.add_argument("--out-dir", default=None, dest="out_dir",
                      help="Override default terraform/<customer>/ directory.")


def _build_inventory(sub) -> None:
    inv = sub.add_parser("inventory", help="Tag-based resource listing.")
    inv.add_argument("--customer", default=None)
    inv.add_argument("--tag-key", default=None, dest="tag_key")
    inv.add_argument("--tag-value", default=None, dest="tag_value")


def _build_cleanup(sub) -> None:
    cl = sub.add_parser("cleanup",
                        help="Find / remove untagged resources.").add_subparsers(
        dest="cleanup_op", required=True
    )
    cl.add_parser("untagged",
                  help="Report resources missing required tags (read-only).")
    p_auto = cl.add_parser("auto",
                           help="Auto-delete safe untagged resources (EIPs + old stopped EC2).")
    p_auto.add_argument("--older-than-days", type=int, default=7,
                        dest="older_than_days")


def _build_audit(sub) -> None:
    a = sub.add_parser("audit", help="Run security / hygiene audit.")
    a.add_argument("--key-age-days", type=int, default=90, dest="key_age_days")


def _build_terraform(sub) -> None:
    """Standalone `terraform` subcommand (also reachable as `jumphost terraform`)."""
    tf = sub.add_parser("terraform",
                        help="Render intent operations as Terraform.").add_subparsers(
        dest="tf_op", required=True
    )
    p_jh = tf.add_parser("jumphost", help="Render a jumphost as .tf files.")
    p_jh.add_argument("--customer", required=True)
    p_jh.add_argument("--allowed-ip", default=None, dest="allowed_ip")
    p_jh.add_argument("--instance-type", default=None, dest="instance_type")
    p_jh.add_argument("--environment", default="dev")
    p_jh.add_argument("--out-dir", default=None, dest="out_dir")


# ---- Dispatcher ------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "setup":
        return auth.setup_wizard()

    # `terraform` only renders local files; doesn't need an AWS session.
    if args.command == "terraform":
        try:
            result = _dispatch_terraform(args)
        except ValueError as e:
            emit_error(str(e), exit_code=5)
            return 5
        except Exception as e:
            emit_error(f"{type(e).__name__}: {e}", exit_code=10)
            return 10
        emit(result, fmt=args.format)
        return 0

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
    except Exception as e:
        emit_error(f"{type(e).__name__}: {e}", exit_code=10)
        return 10

    columns = _columns_for(args)
    id_key = _id_key_for(args)
    emit(result, fmt=args.format, columns=columns, id_key=id_key)
    return 0


def _dispatch(session, args) -> Any:
    cmd = args.command

    if cmd == "iam":
        return _dispatch_iam(session, args)
    if cmd == "ec2":
        return _dispatch_ec2(session, args)
    if cmd == "s3":
        return _dispatch_s3(session, args)
    if cmd == "rds":
        return _dispatch_rds(session, args)
    if cmd == "lambda":
        return _dispatch_lambda(session, args)
    if cmd == "vpc":
        return _dispatch_vpc(session, args)
    if cmd == "route53":
        return _dispatch_route53(session, args)
    if cmd == "cloudwatch":
        return _dispatch_cloudwatch(session, args)
    if cmd == "ecr":
        return _dispatch_ecr(session, args)
    if cmd == "eks":
        return _dispatch_eks(session, args)
    if cmd == "cost":
        return _dispatch_cost(session, args)
    if cmd == "jumphost":
        return _dispatch_jumphost(session, args)
    if cmd == "inventory":
        return _dispatch_inventory(session, args)
    if cmd == "cleanup":
        return _dispatch_cleanup(session, args)
    if cmd == "audit":
        return audit_intent.run(session, key_age_days=args.key_age_days)
    if cmd == "terraform":
        return _dispatch_terraform(args)

    raise NotImplementedError(f"Unhandled command: {cmd}")


def _dispatch_iam(session, args):
    op = args.iam_op
    if op == "who-am-i":
        return iam_svc.who_am_i(session)
    if op == "list-users":
        return iam_svc.list_users(session)
    if op == "list-roles":
        return iam_svc.list_roles(session)
    if op == "list-policies":
        return iam_svc.list_policies(session, scope=args.scope)


def _dispatch_ec2(session, args):
    op = args.ec2_op
    if op == "list":
        return ec2_svc.list_instances(
            session, customer=args.customer, project=args.project,
            show_all=args.show_all,
        )
    if op == "describe":
        return ec2_svc.describe_instance(session, args.instance_id)
    if op == "addresses":
        return ec2_svc.list_addresses(
            session, customer=args.customer, project=args.project
        )
    if op == "start":
        require_confirm(args, "ec2 start")
        if is_dry_run(args):
            return {"would_start": args.instance_id}
        return ec2_svc.start_instance(session, args.instance_id)
    if op == "stop":
        require_confirm(args, "ec2 stop")
        if is_dry_run(args):
            return {"would_stop": args.instance_id}
        return ec2_svc.stop_instance(session, args.instance_id)
    if op == "terminate":
        require_confirm_delete(args, "ec2 terminate")
        if is_dry_run(args):
            return {"would_terminate": args.instance_id}
        return ec2_svc.terminate_instance(session, args.instance_id)
    if op == "alloc-eip":
        require_confirm(args, "ec2 alloc-eip")
        if is_dry_run(args):
            return {"would_allocate_eip": True}
        return ec2_svc.allocate_eip(session)
    if op == "associate-eip":
        require_confirm(args, "ec2 associate-eip")
        if is_dry_run(args):
            return {"would_associate": {"allocation_id": args.allocation_id,
                                        "instance_id": args.instance_id}}
        return ec2_svc.associate_eip(
            session, allocation_id=args.allocation_id, instance_id=args.instance_id,
        )
    if op == "release-eip":
        require_confirm_delete(args, "ec2 release-eip")
        if is_dry_run(args):
            return {"would_release_eip": args.allocation_id}
        return ec2_svc.release_eip(session, args.allocation_id)


def _dispatch_s3(session, args):
    op = args.s3_op
    if op == "ls-buckets":
        return s3_svc.list_buckets(session)
    if op == "ls":
        return s3_svc.list_objects(
            session, args.bucket, prefix=args.prefix, max_items=args.max_items
        )
    if op == "head":
        return s3_svc.head_object(session, args.bucket, args.key)
    if op == "get":
        return s3_svc.get_object(
            session, args.bucket, args.key, out_path=Path(args.out_path)
        )
    if op == "put":
        require_confirm(args, "s3 put")
        if is_dry_run(args):
            return {"would_upload": args.src_path, "to": f"s3://{args.bucket}/{args.key}"}
        return s3_svc.put_object(
            session, args.bucket, args.key, src_path=Path(args.src_path)
        )
    if op == "rm":
        require_confirm_delete(args, "s3 rm")
        if is_dry_run(args):
            return {"would_delete": f"s3://{args.bucket}/{args.key}"}
        return s3_svc.delete_object(session, args.bucket, args.key)
    if op == "public-status":
        return s3_svc.public_access_status(session, args.bucket)


def _dispatch_rds(session, args):
    op = args.rds_op
    if op == "list":
        return rds_svc.list_instances(session, customer=args.customer)
    if op == "describe":
        return rds_svc.describe_instance(session, args.instance_id)
    if op == "snapshot":
        require_confirm(args, "rds snapshot")
        if is_dry_run(args):
            return {"would_snapshot": args.instance_id, "name": args.snapshot_id}
        return rds_svc.create_snapshot(
            session, instance_id=args.instance_id, snapshot_id=args.snapshot_id
        )
    if op == "list-snapshots":
        return rds_svc.list_snapshots(session, instance_id=args.instance_id)


def _dispatch_lambda(session, args):
    op = args.lambda_op
    if op == "list":
        return lambda_svc.list_functions(session, customer=args.customer)
    if op == "get":
        return lambda_svc.get_function(session, args.name)
    if op == "invoke":
        require_confirm(args, "lambda invoke")
        if is_dry_run(args):
            return {"would_invoke": args.name}
        payload = _parse_payload_arg(args.payload)
        return lambda_svc.invoke(
            session, args.name, payload=payload, invocation_type=args.invocation_type
        )
    if op == "logs":
        return lambda_svc.get_logs(
            session, args.name, since=args.since, limit=args.limit
        )


def _dispatch_vpc(session, args):
    op = args.vpc_op
    if op == "list":
        return vpc_svc.list_vpcs(session, customer=args.customer)
    if op == "subnets":
        return vpc_svc.list_subnets(
            session, vpc_id=args.vpc_id, customer=args.customer
        )
    if op == "route-tables":
        return vpc_svc.list_route_tables(session, vpc_id=args.vpc_id)
    if op == "nat":
        return vpc_svc.list_nat_gateways(session, vpc_id=args.vpc_id)


def _dispatch_route53(session, args):
    op = args.r53_op
    if op == "zones":
        return route53_svc.list_zones(session)
    if op == "records":
        return route53_svc.list_records(session, args.zone_id)
    if op == "upsert":
        require_confirm(args, "route53 upsert")
        if is_dry_run(args):
            return {"would_upsert": {"zone_id": args.zone_id, "name": args.name,
                                     "type": args.type, "values": args.values}}
        return route53_svc.upsert_record(
            session, zone_id=args.zone_id, name=args.name, type=args.type,
            values=args.values, ttl=args.ttl,
        )
    if op == "delete":
        require_confirm_delete(args, "route53 delete")
        if is_dry_run(args):
            return {"would_delete": {"zone_id": args.zone_id, "name": args.name,
                                     "type": args.type, "values": args.values}}
        return route53_svc.delete_record(
            session, zone_id=args.zone_id, name=args.name, type=args.type,
            values=args.values, ttl=args.ttl,
        )


def _dispatch_cloudwatch(session, args):
    op = args.cw_op
    if op == "log-groups":
        return cloudwatch_svc.list_log_groups(session, name_prefix=args.name_prefix)
    if op == "logs":
        return cloudwatch_svc.tail_logs(
            session, args.log_group, since=args.since, limit=args.limit,
            filter_pattern=args.filter_pattern,
        )
    if op == "metric":
        return cloudwatch_svc.metric_statistics(
            session, namespace=args.namespace, metric_name=args.metric_name,
            days=args.days, period_seconds=args.period_seconds,
        )


def _dispatch_ecr(session, args):
    op = args.ecr_op
    if op == "list":
        return ecr_svc.list_repos(session)
    if op == "images":
        return ecr_svc.list_images(session, args.repo, limit=args.limit)
    if op == "login":
        return ecr_svc.login_command(session)


def _dispatch_eks(session, args):
    op = args.eks_op
    if op == "list":
        return eks_svc.list_clusters(session, customer=args.customer)
    if op == "kubeconfig":
        require_confirm(args, "eks kubeconfig (writes file)")
        if is_dry_run(args):
            return {"would_write_kubeconfig_for": args.cluster_name}
        path = Path(args.kubeconfig_path) if args.kubeconfig_path else None
        return eks_svc.write_kubeconfig(session, args.cluster_name, kubeconfig_path=path)


def _dispatch_cost(session, args):
    op = args.cost_op
    if op == "last-30d":
        return cost_svc.total_cost(session, days=args.days)
    if op == "by-service":
        return cost_svc.by_service(session, days=args.days)
    if op == "by-tag":
        return cost_svc.by_tag(session, tag_key=args.key, days=args.days)
    if op == "report":
        return cost_report_intent.per_customer(
            session, customer=args.customer, days=args.days
        )


def _dispatch_jumphost(session, args):
    op = args.jh_op
    if op == "provision":
        if not is_dry_run(args):
            require_confirm(args, "jumphost provision")
        return jumphost_intent.provision(
            session, customer=args.customer, allowed_ip=args.allowed_ip,
            instance_type=args.instance_type, environment=args.environment,
            dry_run=is_dry_run(args),
        )
    if op == "teardown":
        if not is_dry_run(args):
            require_confirm_delete(args, "jumphost teardown")
        return jumphost_intent.teardown(
            session, customer=args.customer, dry_run=is_dry_run(args)
        )
    if op == "terraform":
        return terraform_intent.render_jumphost(
            customer=args.customer, allowed_ip=args.allowed_ip,
            instance_type=args.instance_type, environment=args.environment,
            out_dir=Path(args.out_dir) if args.out_dir else None,
        )


def _dispatch_inventory(session, args):
    if args.customer:
        return inventory_intent.by_customer(session, customer=args.customer)
    if args.tag_key and args.tag_value:
        return inventory_intent.by_tag_value(
            session, tag_key=args.tag_key, tag_value=args.tag_value
        )
    raise ValueError(
        "inventory: pass --customer NAME or --tag-key KEY --tag-value VALUE"
    )


def _dispatch_cleanup(session, args):
    op = args.cleanup_op
    if op == "untagged":
        return cleanup_intent.find_untagged(session)
    if op == "auto":
        require_confirm_delete(args, "cleanup auto")
        if is_dry_run(args):
            preview = cleanup_intent.find_untagged(session)
            preview["dry_run"] = True
            return preview
        return cleanup_intent.auto_delete_untagged(
            session, older_than_days=args.older_than_days
        )


def _dispatch_terraform(args):
    op = args.tf_op
    if op == "jumphost":
        return terraform_intent.render_jumphost(
            customer=args.customer, allowed_ip=args.allowed_ip,
            instance_type=args.instance_type, environment=args.environment,
            out_dir=Path(args.out_dir) if args.out_dir else None,
        )


# ---- Helpers ---------------------------------------------------------------


def _parse_payload_arg(payload: str | None) -> Any:
    if payload is None:
        return None
    if payload.startswith("@"):
        path = Path(payload[1:]).expanduser()
        return json.loads(path.read_text())
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return payload  # raw string


def _columns_for(args):
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
    if cmd == "s3" and getattr(args, "s3_op", None) == "ls-buckets":
        return ["name", "region", "created"]
    if cmd == "s3" and getattr(args, "s3_op", None) == "ls":
        return ["key", "size", "last_modified", "storage_class"]
    if cmd == "rds" and getattr(args, "rds_op", None) == "list":
        return ["id", "engine", "engine_version", "status", "class", "endpoint"]
    if cmd == "lambda" and getattr(args, "lambda_op", None) == "list":
        return ["name", "runtime", "memory_mb", "timeout_s", "last_modified"]
    if cmd == "vpc" and getattr(args, "vpc_op", None) == "list":
        return ["vpc_id", "cidr", "is_default", "state"]
    if cmd == "vpc" and getattr(args, "vpc_op", None) == "subnets":
        return ["subnet_id", "vpc_id", "cidr", "az", "available_ips"]
    if cmd == "route53" and getattr(args, "r53_op", None) == "zones":
        return ["zone_id", "name", "private", "record_count"]
    if cmd == "ecr" and getattr(args, "ecr_op", None) == "list":
        return ["name", "uri", "image_tag_mutability", "scan_on_push"]
    if cmd == "ecr" and getattr(args, "ecr_op", None) == "images":
        return ["tags", "pushed", "size_mb", "digest"]
    if cmd == "eks" and getattr(args, "eks_op", None) == "list":
        return ["name", "status", "version", "endpoint"]
    return None


def _id_key_for(args):
    cmd = args.command
    if cmd == "ec2" and getattr(args, "ec2_op", None) == "list":
        return "instance_id"
    if cmd == "ec2" and getattr(args, "ec2_op", None) == "addresses":
        return "allocation_id"
    if cmd == "s3" and getattr(args, "s3_op", None) == "ls-buckets":
        return "name"
    if cmd == "s3" and getattr(args, "s3_op", None) == "ls":
        return "key"
    if cmd == "rds" and getattr(args, "rds_op", None) == "list":
        return "id"
    if cmd == "lambda" and getattr(args, "lambda_op", None) == "list":
        return "name"
    if cmd == "ecr" and getattr(args, "ecr_op", None) == "list":
        return "name"
    if cmd == "eks" and getattr(args, "eks_op", None) == "list":
        return "name"
    return "id"


if __name__ == "__main__":
    sys.exit(main())
