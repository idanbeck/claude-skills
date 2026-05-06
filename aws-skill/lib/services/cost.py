"""Cost Explorer operations.

Notes on Cost Explorer:
    - Endpoint is global; client must be in us-east-1.
    - Costs reported in UnblendedCost USD by default.
    - Granularity: DAILY (most useful for last-30-days), MONTHLY, HOURLY.
    - Tag-based grouping requires the tags to be activated as cost-allocation
      tags in the Billing console; otherwise GroupBy on tag returns nothing.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

import boto3


CE_REGION = "us-east-1"


def _ce_client(session: boto3.Session):
    return session.client("ce", region_name=CE_REGION)


def _date_window(days: int) -> tuple[str, str]:
    """Cost Explorer expects ISO date strings; end is exclusive."""
    end = date.today()
    start = end - timedelta(days=days)
    return start.isoformat(), end.isoformat()


def total_cost(
    session: boto3.Session, *, days: int = 30
) -> dict[str, Any]:
    """Return total UnblendedCost across the window."""
    ce = _ce_client(session)
    start, end = _date_window(days)
    resp = ce.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
    )
    total = 0.0
    unit = "USD"
    for r in resp.get("ResultsByTime", []):
        amount = r.get("Total", {}).get("UnblendedCost", {})
        try:
            total += float(amount.get("Amount", 0))
        except (TypeError, ValueError):
            pass
        unit = amount.get("Unit", unit)
    return {
        "window_days": days,
        "start": start,
        "end": end,
        "total": round(total, 2),
        "unit": unit,
    }


def by_service(
    session: boto3.Session, *, days: int = 30
) -> list[dict[str, Any]]:
    """Cost grouped by AWS service over the window."""
    ce = _ce_client(session)
    start, end = _date_window(days)
    resp = ce.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )
    totals: dict[str, float] = {}
    unit = "USD"
    for r in resp.get("ResultsByTime", []):
        for g in r.get("Groups", []):
            keys = g.get("Keys", [])
            if not keys:
                continue
            service = keys[0]
            amount = g.get("Metrics", {}).get("UnblendedCost", {})
            try:
                totals[service] = totals.get(service, 0.0) + float(
                    amount.get("Amount", 0)
                )
            except (TypeError, ValueError):
                continue
            unit = amount.get("Unit", unit)
    rows = [
        {"service": s, "amount": round(v, 2), "unit": unit}
        for s, v in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    ]
    return rows


def by_tag(
    session: boto3.Session, *, tag_key: str, days: int = 30
) -> list[dict[str, Any]]:
    """Cost grouped by a tag value (e.g. tag_key='Customer').

    NOTE: requires the tag to be activated as a cost-allocation tag in the
    Billing console — otherwise this returns empty.
    """
    ce = _ce_client(session)
    start, end = _date_window(days)
    resp = ce.get_cost_and_usage(
        TimePeriod={"Start": start, "End": end},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "TAG", "Key": tag_key}],
    )
    totals: dict[str, float] = {}
    unit = "USD"
    for r in resp.get("ResultsByTime", []):
        for g in r.get("Groups", []):
            keys = g.get("Keys", [])
            if not keys:
                continue
            # Cost Explorer returns "TagKey$TagValue"
            raw = keys[0]
            value = raw.split("$", 1)[1] if "$" in raw else raw
            value = value or "<untagged>"
            amount = g.get("Metrics", {}).get("UnblendedCost", {})
            try:
                totals[value] = totals.get(value, 0.0) + float(amount.get("Amount", 0))
            except (TypeError, ValueError):
                continue
            unit = amount.get("Unit", unit)
    return [
        {tag_key.lower(): v, "amount": round(amt, 2), "unit": unit}
        for v, amt in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    ]
