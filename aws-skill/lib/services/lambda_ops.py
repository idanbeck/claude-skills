"""Lambda service operations.

`lambda` is a Python reserved word, hence `lambda_ops`.
"""
from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timedelta
from typing import Any, Optional

import boto3

from ..tagging import tags_from_aws


def list_functions(
    session: boto3.Session,
    *,
    customer: Optional[str] = None,
) -> list[dict[str, Any]]:
    lam = session.client("lambda")
    paginator = lam.get_paginator("list_functions")
    out: list[dict[str, Any]] = []
    for page in paginator.paginate():
        for fn in page.get("Functions", []):
            tags = _function_tags(lam, fn.get("FunctionArn"))
            if customer and tags.get("Customer") != customer:
                continue
            out.append(
                {
                    "name": fn.get("FunctionName"),
                    "runtime": fn.get("Runtime"),
                    "memory_mb": fn.get("MemorySize"),
                    "timeout_s": fn.get("Timeout"),
                    "handler": fn.get("Handler"),
                    "last_modified": fn.get("LastModified"),
                    "code_size": fn.get("CodeSize"),
                    "package_type": fn.get("PackageType"),
                    "arn": fn.get("FunctionArn"),
                    "tags": tags,
                }
            )
    return out


def get_function(session: boto3.Session, name: str) -> dict[str, Any]:
    lam = session.client("lambda")
    resp = lam.get_function(FunctionName=name)
    cfg = resp.get("Configuration", {})
    return {
        "name": cfg.get("FunctionName"),
        "arn": cfg.get("FunctionArn"),
        "runtime": cfg.get("Runtime"),
        "memory_mb": cfg.get("MemorySize"),
        "timeout_s": cfg.get("Timeout"),
        "handler": cfg.get("Handler"),
        "role": cfg.get("Role"),
        "environment": cfg.get("Environment", {}).get("Variables", {}),
        "vpc_config": cfg.get("VpcConfig"),
        "tracing_config": cfg.get("TracingConfig"),
        "tags": tags_from_aws(
            [
                {"Key": k, "Value": v}
                for k, v in (resp.get("Tags") or {}).items()
            ]
        ),
    }


def invoke(
    session: boto3.Session,
    name: str,
    *,
    payload: Optional[Any] = None,
    invocation_type: str = "RequestResponse",
) -> dict[str, Any]:
    lam = session.client("lambda")
    kwargs: dict[str, Any] = {"FunctionName": name, "InvocationType": invocation_type}
    if payload is not None:
        kwargs["Payload"] = (
            json.dumps(payload).encode() if not isinstance(payload, bytes) else payload
        )
    if invocation_type == "RequestResponse":
        kwargs["LogType"] = "Tail"
    resp = lam.invoke(**kwargs)
    out: dict[str, Any] = {
        "name": name,
        "status_code": resp.get("StatusCode"),
        "function_error": resp.get("FunctionError"),
        "executed_version": resp.get("ExecutedVersion"),
    }
    if resp.get("LogResult"):
        out["log_tail"] = base64.b64decode(resp["LogResult"]).decode(
            "utf-8", errors="replace"
        )
    payload_stream = resp.get("Payload")
    if payload_stream is not None:
        try:
            raw = payload_stream.read()
            try:
                out["response"] = json.loads(raw)
            except json.JSONDecodeError:
                out["response_raw"] = raw.decode("utf-8", errors="replace")
        except Exception:
            pass
    return out


def get_logs(
    session: boto3.Session,
    name: str,
    *,
    since: str = "1h",
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Tail CloudWatch logs for a function. `since` is e.g. '1h', '30m', '2d'."""
    cw_logs = session.client("logs")
    log_group = f"/aws/lambda/{name}"

    seconds = _parse_since(since)
    start_ms = int((datetime.utcnow() - timedelta(seconds=seconds)).timestamp() * 1000)

    out: list[dict[str, Any]] = []
    next_token: Optional[str] = None
    while True:
        kwargs: dict[str, Any] = {
            "logGroupName": log_group,
            "startTime": start_ms,
            "limit": min(10000, limit - len(out)) or 1,
        }
        if next_token:
            kwargs["nextToken"] = next_token
        resp = cw_logs.filter_log_events(**kwargs)
        for ev in resp.get("events", []):
            out.append(
                {
                    "timestamp": datetime.utcfromtimestamp(
                        ev.get("timestamp", 0) / 1000
                    ),
                    "stream": ev.get("logStreamName"),
                    "message": ev.get("message", "").rstrip(),
                }
            )
            if len(out) >= limit:
                return out
        next_token = resp.get("nextToken")
        if not next_token:
            break
    return out


def _function_tags(lam_client, arn: Optional[str]) -> dict[str, str]:
    if not arn:
        return {}
    try:
        resp = lam_client.list_tags(Resource=arn)
        return resp.get("Tags", {}) or {}
    except Exception:
        return {}


def _parse_since(s: str) -> int:
    """Parse '1h', '30m', '2d', '90s' into seconds."""
    if not s:
        return 3600
    unit = s[-1].lower()
    try:
        n = int(s[:-1])
    except ValueError:
        return 3600
    return {"s": n, "m": n * 60, "h": n * 3600, "d": n * 86400}.get(unit, 3600)
