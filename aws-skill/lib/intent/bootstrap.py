"""Bootstrap intent: create the right IAM identity off root.

Use case: you authenticated as the AWS account root (e.g. via
`aws login`) and want to move to a proper IAM user for ongoing skill use.
This intent creates an admin user, attaches AdministratorAccess, generates
access keys, and (optionally) writes them into ~/.aws/credentials as a
named profile.

After running, the recommended next step is to:
    1. Verify the new profile works: `aws_skill.py iam who-am-i --profile <name>`
    2. Sign out of root in the AWS Console
    3. Add MFA to the new IAM user (console or `aws iam enable-mfa-device`)
"""
from __future__ import annotations

import configparser
from pathlib import Path
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

from ..auth import AWS_CREDENTIALS, AWS_DIR, AWS_CONFIG


ADMIN_POLICY_ARN = "arn:aws:iam::aws:policy/AdministratorAccess"


def create_admin_user(
    session: boto3.Session,
    *,
    username: str,
    update_profile: Optional[str] = None,
    region: Optional[str] = None,
    create_console_password: bool = False,
) -> dict[str, Any]:
    """Create an IAM user with AdministratorAccess and a fresh access key.

    Args:
        session: boto3 session (must have iam:* — typically root on first
            bootstrap).
        username: IAM user name to create.
        update_profile: if provided, write the new keys into ~/.aws/credentials
            under this profile name. The profile entry replaces any existing
            entry of the same name.
        region: default region to associate with the profile (only used if
            update_profile is set).
        create_console_password: if True, generate a console login password
            and return it. The user must change it on first sign-in.

    Returns: created identity, access keys, and (if update_profile) the
        path of the credentials file we updated.
    """
    iam = session.client("iam")

    # 1) Create user (idempotent-ish: if it exists, that's fine, we'll just
    #    add the policy and a new key).
    user_existed = False
    try:
        iam.create_user(UserName=username)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "EntityAlreadyExists":
            user_existed = True
        else:
            raise

    user_arn = iam.get_user(UserName=username)["User"]["Arn"]

    # 2) Attach AdministratorAccess (idempotent — attach is a no-op if already
    #    attached).
    iam.attach_user_policy(UserName=username, PolicyArn=ADMIN_POLICY_ARN)

    # 3) Create access key
    key_resp = iam.create_access_key(UserName=username)
    key = key_resp.get("AccessKey", {})
    access_key_id = key.get("AccessKeyId")
    secret_access_key = key.get("SecretAccessKey")

    # 4) Optionally create console login profile
    console_password: Optional[str] = None
    if create_console_password:
        import secrets

        console_password = secrets.token_urlsafe(20)
        try:
            iam.create_login_profile(
                UserName=username,
                Password=console_password,
                PasswordResetRequired=True,
            )
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "EntityAlreadyExists":
                console_password = None  # don't shout a stale password
            else:
                raise

    out: dict[str, Any] = {
        "user_name": username,
        "user_arn": user_arn,
        "user_existed_before": user_existed,
        "policy_attached": ADMIN_POLICY_ARN,
        "access_key_id": access_key_id,
        "secret_access_key": secret_access_key,
        "key_displayed_once": (
            "AWS only shows the secret access key on creation. Save it now."
        ),
    }
    if console_password:
        out["console_password"] = console_password
        out["console_password_reset_required"] = True

    if update_profile:
        path = _write_profile(
            profile=update_profile,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            region=region or session.region_name,
        )
        out["credentials_file_updated"] = str(path)
        out["next_step"] = (
            f"Re-run any aws-skill command with `--profile {update_profile}` "
            "to use the new identity, or set AWS_PROFILE."
        )
    else:
        out["next_step"] = (
            "Run `aws configure --profile <name>` and paste the access key "
            "above, or pass --update-profile NAME on the bootstrap command "
            "to do this automatically."
        )

    out["recommended_followups"] = [
        f"Verify the new profile works: aws_skill.py iam who-am-i "
        f"--profile {update_profile or '<name>'}",
        "Add MFA to the new user via the AWS Console (Security credentials → "
        "Assigned MFA device → Assign).",
        "Sign out of the AWS Console as root and stop using root creds for "
        "day-to-day work.",
    ]
    return out


def _write_profile(
    *,
    profile: str,
    access_key_id: str,
    secret_access_key: str,
    region: Optional[str],
) -> Path:
    """Write/update the credentials and config files for a profile.

    Replaces an existing profile in place.
    """
    AWS_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)

    # ~/.aws/credentials
    creds = configparser.ConfigParser()
    if AWS_CREDENTIALS.exists():
        creds.read(AWS_CREDENTIALS)
    if profile in creds:
        creds.remove_section(profile)
    creds[profile] = {
        "aws_access_key_id": access_key_id,
        "aws_secret_access_key": secret_access_key,
    }
    with AWS_CREDENTIALS.open("w") as f:
        creds.write(f)
    AWS_CREDENTIALS.chmod(0o600)

    # ~/.aws/config (region + output for the named profile)
    if region:
        cfg = configparser.ConfigParser()
        if AWS_CONFIG.exists():
            cfg.read(AWS_CONFIG)
        section = "default" if profile == "default" else f"profile {profile}"
        if section in cfg:
            cfg.remove_section(section)
        cfg[section] = {
            "region": region,
            "output": "json",
        }
        with AWS_CONFIG.open("w") as f:
            cfg.write(f)
        AWS_CONFIG.chmod(0o600)

    return AWS_CREDENTIALS
