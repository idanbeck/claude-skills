"""S3 service operations.

Read + minimal write. Bucket policies / ACLs / replication left for v3.
Object operations are intentionally limited (head/get/put/rm); for bulk
moves prefer `aws s3 cp/sync` directly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

from ..tagging import tags_from_aws


def list_buckets(session: boto3.Session) -> list[dict[str, Any]]:
    s3 = session.client("s3")
    resp = s3.list_buckets()
    out = []
    for b in resp.get("Buckets", []):
        name = b.get("Name")
        item: dict[str, Any] = {
            "name": name,
            "created": b.get("CreationDate"),
        }
        # Region (LocationConstraint) and tags are per-bucket; keep cheap.
        try:
            loc = s3.get_bucket_location(Bucket=name).get("LocationConstraint")
            item["region"] = loc or "us-east-1"
        except ClientError:
            item["region"] = "<unknown>"
        try:
            tag_resp = s3.get_bucket_tagging(Bucket=name)
            item["tags"] = tags_from_aws(tag_resp.get("TagSet"))
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in {
                "NoSuchTagSet",
                "NoSuchTagSetError",
            }:
                item["tags"] = {}
            else:
                item["tags_error"] = str(e)
        out.append(item)
    return out


def list_objects(
    session: boto3.Session,
    bucket: str,
    *,
    prefix: Optional[str] = None,
    max_items: int = 1000,
) -> list[dict[str, Any]]:
    s3 = session.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    kwargs: dict[str, Any] = {"Bucket": bucket}
    if prefix:
        kwargs["Prefix"] = prefix
    out: list[dict[str, Any]] = []
    for page in paginator.paginate(**kwargs):
        for o in page.get("Contents", []) or []:
            out.append(
                {
                    "key": o.get("Key"),
                    "size": o.get("Size"),
                    "last_modified": o.get("LastModified"),
                    "storage_class": o.get("StorageClass"),
                    "etag": o.get("ETag", "").strip('"'),
                }
            )
            if len(out) >= max_items:
                return out
    return out


def head_object(
    session: boto3.Session, bucket: str, key: str
) -> dict[str, Any]:
    s3 = session.client("s3")
    resp = s3.head_object(Bucket=bucket, Key=key)
    return {
        "bucket": bucket,
        "key": key,
        "size": resp.get("ContentLength"),
        "etag": resp.get("ETag", "").strip('"'),
        "content_type": resp.get("ContentType"),
        "last_modified": resp.get("LastModified"),
        "metadata": resp.get("Metadata", {}),
        "server_side_encryption": resp.get("ServerSideEncryption"),
    }


def get_object(
    session: boto3.Session, bucket: str, key: str, *, out_path: Path
) -> dict[str, Any]:
    s3 = session.client("s3")
    out_path = Path(out_path).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    s3.download_file(bucket, key, str(out_path))
    return {
        "bucket": bucket,
        "key": key,
        "downloaded_to": str(out_path),
        "size": out_path.stat().st_size,
    }


def put_object(
    session: boto3.Session, bucket: str, key: str, *, src_path: Path
) -> dict[str, Any]:
    s3 = session.client("s3")
    src_path = Path(src_path).expanduser()
    s3.upload_file(str(src_path), bucket, key)
    return {
        "bucket": bucket,
        "key": key,
        "uploaded_from": str(src_path),
        "size": src_path.stat().st_size,
    }


def delete_object(
    session: boto3.Session, bucket: str, key: str
) -> dict[str, Any]:
    s3 = session.client("s3")
    s3.delete_object(Bucket=bucket, Key=key)
    return {"bucket": bucket, "key": key, "deleted": True}


def public_access_status(session: boto3.Session, bucket: str) -> dict[str, Any]:
    """Combine BucketPublicAccessBlock + BucketAcl to assess exposure."""
    s3 = session.client("s3")
    out: dict[str, Any] = {"bucket": bucket}
    try:
        pab = s3.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"]
        out["public_access_block"] = pab
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code == "NoSuchPublicAccessBlockConfiguration":
            out["public_access_block"] = None
        else:
            out["public_access_block_error"] = str(e)
    try:
        acl = s3.get_bucket_acl(Bucket=bucket)
        public_grants = []
        for g in acl.get("Grants", []):
            grantee = g.get("Grantee", {})
            uri = grantee.get("URI", "")
            if "AllUsers" in uri or "AuthenticatedUsers" in uri:
                public_grants.append(
                    {"permission": g.get("Permission"), "grantee_uri": uri}
                )
        out["acl_public_grants"] = public_grants
    except ClientError as e:
        out["acl_error"] = str(e)
    out["likely_public"] = bool(out.get("acl_public_grants")) or (
        out.get("public_access_block") is None
    )
    return out
