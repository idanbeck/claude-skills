"""CloudWatch operations: log tailing + simple metric queries."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

import boto3


def list_log_groups(
    session: boto3.Session,
    *,
    name_prefix: Optional[str] = None,
) -> list[dict[str, Any]]:
    cw = session.client("logs")
    paginator = cw.get_paginator("describe_log_groups")
    kwargs: dict[str, Any] = {}
    if name_prefix:
        kwargs["logGroupNamePrefix"] = name_prefix
    out: list[dict[str, Any]] = []
    for page in paginator.paginate(**kwargs):
        for g in page.get("logGroups", []):
            out.append(
                {
                    "name": g.get("logGroupName"),
                    "stored_bytes": g.get("storedBytes"),
                    "retention_days": g.get("retentionInDays"),
                    "created": (
                        datetime.utcfromtimestamp(g.get("creationTime", 0) / 1000)
                        if g.get("creationTime")
                        else None
                    ),
                }
            )
    return out


def tail_logs(
    session: boto3.Session,
    log_group: str,
    *,
    since: str = "1h",
    limit: int = 500,
    filter_pattern: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Tail a log group. since='1h', '30m', '2d' supported."""
    cw = session.client("logs")
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
        if filter_pattern:
            kwargs["filterPattern"] = filter_pattern
        if next_token:
            kwargs["nextToken"] = next_token
        resp = cw.filter_log_events(**kwargs)
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


def metric_statistics(
    session: boto3.Session,
    *,
    namespace: str,
    metric_name: str,
    dimensions: Optional[list[dict[str, str]]] = None,
    days: int = 1,
    period_seconds: int = 300,
    statistics: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """Pull GetMetricStatistics datapoints. Statistics defaults to ['Average']."""
    cw = session.client("cloudwatch")
    end = datetime.utcnow()
    start = end - timedelta(days=days)
    resp = cw.get_metric_statistics(
        Namespace=namespace,
        MetricName=metric_name,
        Dimensions=dimensions or [],
        StartTime=start,
        EndTime=end,
        Period=period_seconds,
        Statistics=statistics or ["Average"],
    )
    points = sorted(
        resp.get("Datapoints", []), key=lambda p: p.get("Timestamp")
    )
    return [
        {
            "timestamp": p.get("Timestamp"),
            **{
                k.lower(): p.get(k)
                for k in ("Average", "Sum", "Maximum", "Minimum", "SampleCount")
                if k in p
            },
            "unit": p.get("Unit"),
        }
        for p in points
    ]


def _parse_since(s: str) -> int:
    if not s:
        return 3600
    unit = s[-1].lower()
    try:
        n = int(s[:-1])
    except ValueError:
        return 3600
    return {"s": n, "m": n * 60, "h": n * 3600, "d": n * 86400}.get(unit, 3600)
