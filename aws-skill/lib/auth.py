"""AWS profile + session resolution.

Honors AWS-native conventions: ~/.aws/credentials, ~/.aws/config, env vars,
IAM Identity Center / SSO. The skill is a thin layer above boto3; we don't
store credentials ourselves.

Profile naming convention for this skill:
    - "epoch"     : default Epoch AWS account (single-account model)
    - "<customer>": optional customer-specific profile (cross-account, future)
"""
from __future__ import annotations

import configparser
import os
import sys
from pathlib import Path
from typing import Optional

import boto3
from botocore.exceptions import (
    ClientError,
    NoCredentialsError,
    ProfileNotFound,
    SSOTokenLoadError,
)

# Default profile for this skill. Can be overridden by --profile or AWS_PROFILE.
DEFAULT_PROFILE = "epoch"

AWS_DIR = Path.home() / ".aws"
AWS_CREDENTIALS = AWS_DIR / "credentials"
AWS_CONFIG = AWS_DIR / "config"


class AuthError(RuntimeError):
    """Raised when auth setup is missing or invalid. Caller should print
    the message and suggest `aws_skill.py setup`."""


def resolve_profile(profile: Optional[str]) -> str:
    """Pick the profile to use. Precedence:
        1. explicit arg
        2. AWS_PROFILE env
        3. DEFAULT_PROFILE if it exists locally
        4. 'default' if it exists locally
        5. DEFAULT_PROFILE (caller will get a useful error if missing)
    """
    if profile:
        return profile
    env = os.environ.get("AWS_PROFILE")
    if env:
        return env
    local = set(list_local_profiles())
    if DEFAULT_PROFILE in local:
        return DEFAULT_PROFILE
    if "default" in local:
        return "default"
    return DEFAULT_PROFILE


def list_local_profiles() -> list[str]:
    """Profiles configured in ~/.aws/credentials and ~/.aws/config."""
    profiles: set[str] = set()
    if AWS_CREDENTIALS.exists():
        cfg = configparser.ConfigParser()
        cfg.read(AWS_CREDENTIALS)
        profiles.update(cfg.sections())
    if AWS_CONFIG.exists():
        cfg = configparser.ConfigParser()
        cfg.read(AWS_CONFIG)
        for section in cfg.sections():
            # ~/.aws/config uses "[profile NAME]" except for [default]
            if section == "default":
                profiles.add("default")
            elif section.startswith("profile "):
                profiles.add(section[len("profile ") :])
    return sorted(profiles)


def profile_exists(profile: str) -> bool:
    return profile in list_local_profiles()


def get_session(
    profile: Optional[str] = None,
    region: Optional[str] = None,
) -> boto3.Session:
    """Build a boto3 Session for the requested profile + region.

    Raises AuthError with a helpful message if the profile isn't configured
    or credentials can't be resolved.
    """
    chosen = resolve_profile(profile)

    if not profile_exists(chosen):
        local = list_local_profiles()
        if not local:
            raise AuthError(
                "No AWS profiles configured on this machine. "
                "Run `python3 ~/.claude/skills/aws-skill/aws_skill.py setup` "
                "to initialize the Epoch profile."
            )
        raise AuthError(
            f"AWS profile '{chosen}' not found. "
            f"Available: {', '.join(local)}. "
            f"Either pass `--profile <name>` or run "
            f"`python3 ~/.claude/skills/aws-skill/aws_skill.py setup` "
            f"to add the '{chosen}' profile."
        )

    try:
        session = boto3.Session(profile_name=chosen, region_name=region)
    except ProfileNotFound as e:
        raise AuthError(str(e)) from e

    # Eagerly resolve credentials so failures surface here, not at first API call.
    try:
        creds = session.get_credentials()
        if creds is None:
            raise AuthError(
                f"AWS profile '{chosen}' is configured but resolved to no "
                "credentials. Likely an expired SSO token — try "
                "`aws sso login --profile " + chosen + "`."
            )
    except SSOTokenLoadError as e:
        raise AuthError(
            f"SSO token expired or missing for profile '{chosen}'. "
            f"Run `aws sso login --profile {chosen}`."
        ) from e
    except NoCredentialsError as e:
        raise AuthError(
            f"No credentials resolvable for profile '{chosen}'. "
            "Check ~/.aws/credentials and ~/.aws/config."
        ) from e

    return session


def get_account_id(session: boto3.Session) -> str:
    """Return the 12-digit account ID for the session's caller identity."""
    sts = session.client("sts")
    return sts.get_caller_identity()["Account"]


def whoami(session: boto3.Session) -> dict:
    """STS GetCallerIdentity result, with account alias if available."""
    sts = session.client("sts")
    identity = sts.get_caller_identity()
    out = {
        "account": identity["Account"],
        "arn": identity["Arn"],
        "user_id": identity["UserId"],
    }
    # Try for account alias (informational; requires iam:ListAccountAliases).
    try:
        iam = session.client("iam")
        aliases = iam.list_account_aliases().get("AccountAliases", [])
        if aliases:
            out["account_alias"] = aliases[0]
    except ClientError:
        pass
    out["region"] = session.region_name or "<unset>"
    out["profile"] = session.profile_name
    return out


def setup_wizard() -> int:
    """Interactive setup. Offers three auth methods:

        1. `aws login` — browser-based AWS Console session (easiest, AWS CLI v2.13+).
        2. `aws configure sso` — IAM Identity Center / SSO flow.
        3. `aws configure` — manual access key entry.

    Returns process exit code: 0 on success, non-zero on failure.
    """
    import subprocess

    print("=" * 64)
    print(" AWS Skill — Setup Wizard")
    print("=" * 64)
    print()
    if not AWS_DIR.exists():
        print(f"Creating {AWS_DIR}/ ...")
        AWS_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)

    existing = list_local_profiles()
    if existing:
        print(f"Existing profiles found: {', '.join(existing)}")
    else:
        print("No existing AWS profiles found.")
    print()

    default_name = DEFAULT_PROFILE
    suggestion = (
        f"[{default_name}]"
        if default_name not in existing
        else f"[reconfigure {default_name}]"
    )
    name = input(f"Profile name to configure {suggestion}: ").strip() or default_name
    if not name:
        print("Aborted: empty profile name.")
        return 1

    if name in existing:
        confirm = input(
            f"Profile '{name}' already exists — overwrite? [y/N] "
        ).strip().lower()
        if confirm != "y":
            print("Aborted.")
            return 0

    print()
    print("Pick an auth method:")
    print("  [1] aws login         (browser flow, easiest; AWS CLI v2.13+)")
    print("  [2] aws configure sso (IAM Identity Center / SSO)")
    print("  [3] aws configure     (manual access key entry)")
    print()
    choice = input("Choice [1]: ").strip() or "1"
    print()

    if choice == "1":
        cmd = ["aws", "login", "--profile", name]
        method = "aws login"
    elif choice == "2":
        cmd = ["aws", "configure", "sso", "--profile", name]
        method = "aws configure sso"
    elif choice == "3":
        cmd = ["aws", "configure", "--profile", name]
        method = "aws configure"
    else:
        print(f"Unknown choice '{choice}'. Aborting.")
        return 1

    print(f"Running `{' '.join(cmd)}` ...")
    print()

    try:
        rc = subprocess.call(cmd)
    except FileNotFoundError:
        print(
            "AWS CLI not found in PATH. Install it: "
            "`brew install awscli` or "
            "see https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
        )
        return 127

    if rc != 0:
        print(f"`{method}` exited with code {rc}.")
        if method == "aws login":
            print(
                "Hint: `aws login` requires AWS CLI v2.13+. "
                "Try option [2] (SSO) or [3] (access keys), or upgrade with "
                "`brew upgrade awscli`."
            )
        return rc

    print()
    print("Validating credentials ...")
    try:
        session = get_session(profile=name)
        identity = whoami(session)
    except AuthError as e:
        print(f"Validation failed: {e}", file=sys.stderr)
        return 2
    except ClientError as e:
        print(f"AWS rejected the credentials: {e}", file=sys.stderr)
        return 2

    print()
    print(f"  Account:        {identity['account']}")
    if "account_alias" in identity:
        print(f"  Account alias:  {identity['account_alias']}")
    print(f"  ARN:            {identity['arn']}")
    print(f"  Region:         {identity['region']}")
    print(f"  Profile:        {identity['profile']}")
    print()
    print(f"Profile '{name}' is configured and reachable. Setup complete.")

    # Friendly nudge if the caller landed on root credentials
    if ":root" in identity.get("arn", ""):
        print()
        print(
            "Note: you authenticated as the AWS account root. Root creds work "
            "but are over-privileged for routine ops. Consider creating an IAM "
            "user (or IAM Identity Center user) and re-running this wizard "
            "with those credentials when you have a moment."
        )

    return 0
