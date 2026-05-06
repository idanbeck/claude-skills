"""EKS operations: list clusters, write kubeconfig.

We don't wrap full cluster CRUD — those go through Terraform / eksctl.
"""
from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path
from typing import Any, Optional

import boto3
import yaml  # type: ignore

from ..tagging import tags_from_aws


def list_clusters(
    session: boto3.Session,
    *,
    customer: Optional[str] = None,
) -> list[dict[str, Any]]:
    eks = session.client("eks")
    out: list[dict[str, Any]] = []
    paginator = eks.get_paginator("list_clusters")
    for page in paginator.paginate():
        for name in page.get("clusters", []):
            cluster = eks.describe_cluster(name=name).get("cluster", {})
            tags = cluster.get("tags") or {}
            if customer and tags.get("Customer") != customer:
                continue
            out.append(
                {
                    "name": cluster.get("name"),
                    "status": cluster.get("status"),
                    "version": cluster.get("version"),
                    "endpoint": cluster.get("endpoint"),
                    "platform_version": cluster.get("platformVersion"),
                    "role_arn": cluster.get("roleArn"),
                    "created": cluster.get("createdAt"),
                    "tags": tags,
                }
            )
    return out


def write_kubeconfig(
    session: boto3.Session,
    cluster_name: str,
    *,
    kubeconfig_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Write a kubeconfig entry for the cluster.

    Tries `aws eks update-kubeconfig` first (the standard way). Falls back
    to writing a minimal config directly if the AWS CLI isn't available.
    """
    region = session.region_name
    profile = session.profile_name
    target = Path(kubeconfig_path or os.environ.get("KUBECONFIG") or "~/.kube/config")
    target = target.expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)

    # Prefer aws CLI when present — it's the canonical path.
    try:
        env = os.environ.copy()
        env["AWS_PROFILE"] = profile
        rc = subprocess.run(
            [
                "aws",
                "eks",
                "update-kubeconfig",
                "--name",
                cluster_name,
                "--region",
                region or "us-west-2",
                "--profile",
                profile,
            ],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        if rc.returncode == 0:
            return {
                "cluster": cluster_name,
                "kubeconfig_path": str(target),
                "method": "aws-cli",
                "stdout": rc.stdout.strip(),
            }
    except FileNotFoundError:
        pass

    # Fallback: write a minimal kubeconfig directly.
    eks = session.client("eks")
    cluster = eks.describe_cluster(name=cluster_name).get("cluster", {})
    endpoint = cluster.get("endpoint")
    ca = cluster.get("certificateAuthority", {}).get("data")
    if not (endpoint and ca):
        raise RuntimeError(
            "Could not retrieve cluster endpoint / CA. Ensure your role has "
            "eks:DescribeCluster permission."
        )

    config = {
        "apiVersion": "v1",
        "kind": "Config",
        "clusters": [
            {
                "name": cluster_name,
                "cluster": {"server": endpoint, "certificate-authority-data": ca},
            }
        ],
        "contexts": [
            {
                "name": cluster_name,
                "context": {"cluster": cluster_name, "user": cluster_name},
            }
        ],
        "current-context": cluster_name,
        "users": [
            {
                "name": cluster_name,
                "user": {
                    "exec": {
                        "apiVersion": "client.authentication.k8s.io/v1beta1",
                        "command": "aws",
                        "args": [
                            "--region",
                            region,
                            "eks",
                            "get-token",
                            "--cluster-name",
                            cluster_name,
                        ],
                        "env": [{"name": "AWS_PROFILE", "value": profile}],
                    }
                },
            }
        ],
    }
    target.write_text(yaml.safe_dump(config, sort_keys=False))
    target.chmod(0o600)
    return {
        "cluster": cluster_name,
        "kubeconfig_path": str(target),
        "method": "fallback",
        "warning": "Wrote a minimal config; aws-cli would have merged with existing.",
    }
