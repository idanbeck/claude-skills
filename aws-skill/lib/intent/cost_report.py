"""Per-customer cost report intent.

Cost broken down by Customer tag, with per-service detail and a simple
month-over-month comparison.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

import boto3

from ..services.cost import CE_REGION


def _ce(session: boto3.Session):
    return session.client("ce", region_name=CE_REGION)


def _last_n_months_window(months: int) -> tuple[str, str]:
    today = date.today()
    start = (today.replace(day=1)) - timedelta(days=months * 31)
    start = start.replace(day=1)
    return start.isoformat(), today.isoformat()


def per_customer(
    session: boto3.Session,
    *,
    customer: str,
    days: int = 30,
) -> dict[str, Any]:
    """Cost detail for a single Customer tag value over the window.

    Reports:
      - total over the window
      - breakdown by AWS service (within this customer)
      - month-over-month total trend (last 6 months)
    """
    ce = _ce(session)
    end = date.today()
    start = end - timedelta(days=days)

    # Total across the window, filtered to this customer's tag
    tag_filter = {
        "Tags": {"Key": "Customer", "Values": [customer], "MatchOptions": ["EQUALS"]}
    }
    total_resp = ce.get_cost_and_usage(
        TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        Filter=tag_filter,
    )
    total = 0.0
    unit = "USD"
    for r in total_resp.get("ResultsByTime", []):
        amount = r.get("Total", {}).get("UnblendedCost", {})
        try:
            total += float(amount.get("Amount", 0))
        except (TypeError, ValueError):
            pass
        unit = amount.get("Unit", unit)

    # By-service within this customer
    svc_resp = ce.get_cost_and_usage(
        TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        Filter=tag_filter,
    )
    svc_totals: dict[str, float] = {}
    for r in svc_resp.get("ResultsByTime", []):
        for g in r.get("Groups", []):
            keys = g.get("Keys", [])
            if not keys:
                continue
            service = keys[0]
            try:
                svc_totals[service] = svc_totals.get(service, 0.0) + float(
                    g.get("Metrics", {}).get("UnblendedCost", {}).get("Amount", 0)
                )
            except (TypeError, ValueError):
                continue
    service_breakdown = [
        {"service": s, "amount": round(v, 2), "unit": unit}
        for s, v in sorted(svc_totals.items(), key=lambda kv: kv[1], reverse=True)
    ]

    # Month-over-month last 6 months
    mom_start_iso, mom_end_iso = _last_n_months_window(6)
    mom_resp = ce.get_cost_and_usage(
        TimePeriod={"Start": mom_start_iso, "End": mom_end_iso},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        Filter=tag_filter,
    )
    monthly: list[dict[str, Any]] = []
    for r in mom_resp.get("ResultsByTime", []):
        amount = r.get("Total", {}).get("UnblendedCost", {})
        try:
            value = float(amount.get("Amount", 0))
        except (TypeError, ValueError):
            value = 0.0
        monthly.append(
            {
                "period_start": r.get("TimePeriod", {}).get("Start"),
                "period_end": r.get("TimePeriod", {}).get("End"),
                "amount": round(value, 2),
                "unit": amount.get("Unit", unit),
            }
        )

    return {
        "customer": customer,
        "window_days": days,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "total": round(total, 2),
        "unit": unit,
        "service_breakdown": service_breakdown,
        "monthly_last_6": monthly,
        "notes": (
            "Requires the 'Customer' tag to be activated as a cost-allocation "
            "tag in AWS Billing. If totals are zero, that's the likely cause."
        ),
    }
