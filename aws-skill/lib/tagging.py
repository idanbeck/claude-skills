"""Required-tag policy and tag-based filtering helpers.

Every resource the skill creates carries:
    Customer     — e.g. dmatrix, cesium
    Project      — e.g. jumphost, poc, dev
    Owner        — e.g. idan@zergai.com
    Environment  — e.g. dev, staging, prod
    ManagedBy    — always 'zerg-aws-skill'

This is single-source-of-truth for the tag schema. Service modules call
`build_tags()` to construct the tag dict for any resource they create, and
`tag_filter()` to filter results by Customer/Project/Owner.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

REQUIRED_TAG_KEYS = ("Customer", "Project", "Owner", "Environment", "ManagedBy")
SKILL_TAG_VALUE = "zerg-aws-skill"

DEFAULT_OWNER = os.environ.get("AWS_SKILL_OWNER", "idan@zergai.com")

SKILL_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = SKILL_ROOT / "templates"
CUSTOMERS_DIR = SKILL_ROOT / "customers"


def build_tags(
    customer: str,
    project: str,
    *,
    environment: str = "dev",
    owner: Optional[str] = None,
    extra: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """Construct the required-tag dict for a new resource.

    Returns a plain {key: value} dict. Convert to AWS list-of-dicts via
    `to_aws_tags()` when calling boto3.
    """
    tags: dict[str, str] = {
        "Customer": customer,
        "Project": project,
        "Owner": owner or DEFAULT_OWNER,
        "Environment": environment,
        "ManagedBy": SKILL_TAG_VALUE,
    }
    if extra:
        tags.update(extra)
    return tags


def to_aws_tags(tags: dict[str, str]) -> list[dict[str, str]]:
    """Convert {key: value} dict to AWS list-of-dicts format."""
    return [{"Key": k, "Value": v} for k, v in tags.items()]


def to_aws_tag_specifications(
    resource_types: list[str],
    tags: dict[str, str],
) -> list[dict[str, Any]]:
    """Build TagSpecifications for ec2.run_instances / allocate_address / etc."""
    aws_tags = to_aws_tags(tags)
    return [{"ResourceType": rt, "Tags": aws_tags} for rt in resource_types]


def tags_from_aws(aws_tags: Optional[list[dict[str, str]]]) -> dict[str, str]:
    """Flatten AWS list-of-dicts tags into a plain dict."""
    if not aws_tags:
        return {}
    return {t["Key"]: t["Value"] for t in aws_tags}


def tag_filters(
    customer: Optional[str] = None,
    project: Optional[str] = None,
    owner: Optional[str] = None,
    environment: Optional[str] = None,
    managed_by_skill: bool = False,
) -> list[dict[str, Any]]:
    """EC2-style Filters list keyed on tag values.

    Use with ec2.describe_instances(Filters=...), describe_addresses, etc.
    """
    out: list[dict[str, Any]] = []

    def add(key: str, value: str) -> None:
        out.append({"Name": f"tag:{key}", "Values": [value]})

    if customer:
        add("Customer", customer)
    if project:
        add("Project", project)
    if owner:
        add("Owner", owner)
    if environment:
        add("Environment", environment)
    if managed_by_skill:
        add("ManagedBy", SKILL_TAG_VALUE)
    return out


def missing_required_tags(aws_tags: Optional[list[dict[str, str]]]) -> list[str]:
    """Return required keys that aren't present (for cleanup/audit)."""
    have = tags_from_aws(aws_tags)
    return [k for k in REQUIRED_TAG_KEYS if k not in have]


def load_default_tags() -> dict[str, Any]:
    """Read templates/default-tags.json (descriptive only; not authoritative)."""
    path = TEMPLATES_DIR / "default-tags.json"
    if path.exists():
        return json.loads(path.read_text())
    return {"required_keys": list(REQUIRED_TAG_KEYS), "skill_value": SKILL_TAG_VALUE}


def load_customer_config(customer: str) -> dict[str, Any]:
    """Read customers/<name>.json if present. Empty dict if not."""
    path = CUSTOMERS_DIR / f"{customer}.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}
