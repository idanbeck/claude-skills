# aws-skill

Customer-tagged, opinionated CLI over AWS via boto3. Use it instead of the AWS console for routine ops on the Epoch account.

See [SKILL.md](SKILL.md) for the Claude-facing usage doc; this README is for humans setting up the skill.

## Install

```bash
# from anywhere
pip install -r ~/.claude/skills/aws-skill/requirements.txt
```

(Or with a venv if you'd rather isolate.)

## First-time setup

If `~/.aws/credentials` doesn't exist on this machine yet:

```bash
python3 ~/.claude/skills/aws-skill/aws_skill.py setup
```

Walks through `aws configure --profile epoch` and validates the credentials with an STS GetCallerIdentity call.

For SSO-backed accounts, configure with `aws configure sso --profile epoch` instead, then re-run `who-am-i` to verify.

## File layout

```
aws-skill/
├── SKILL.md                Claude-facing usage doc
├── README.md               this file
├── aws_skill.py            CLI entry point
├── requirements.txt
├── lib/
│   ├── auth.py             profile/session/region resolution + setup wizard
│   ├── output.py           json/table/markdown/ids formatters
│   ├── confirm.py          --confirm / --confirm-delete guardrails
│   ├── tagging.py          required-tag policy + tag-filter helpers
│   ├── services/
│   │   ├── iam.py          read-only IAM ops
│   │   ├── ec2.py          full EC2 surface (instances, EIPs, SGs, key pairs, AMIs)
│   │   └── cost.py         Cost Explorer
│   └── intent/
│       ├── jumphost.py     provision/teardown customer jump hosts
│       └── inventory.py    cross-service tag-based listing
├── templates/
│   ├── jumphost-userdata.sh    cloud-init for jump-host EC2
│   ├── default-tags.json       required-tag schema
│   └── customer-config.example.json
├── customers/                  per-customer config (gitignored)
│   └── d-matrix.json
└── .gitignore
```

## Commit / repo conventions

This directory is part of the `idanbeck/claude-skills` repo. Per the existing convention:

- `SKILL.md`, `README.md`, `aws_skill.py`, `lib/`, `templates/` — committed.
- `customers/*.json` — **never committed** (may contain network-sensitive details).
- `*.pem`, `*.key`, `credentials.json`, `config.json` — never committed.
- AWS credentials live in `~/.aws/`, not in this directory.

## v1 scope

What's in:

- IAM (read-only): who-am-i, list-users, list-roles, list-policies
- EC2 (full): list, describe, start, stop, terminate, alloc-eip, associate-eip, release-eip, key pairs, security groups
- Cost Explorer: last-30d, by-service, by-tag
- Jumphost intent: provision + teardown
- Inventory: per-customer listing across EC2/EIP/SG/key-pair

What's out (v2+):

- S3, RDS, Lambda, VPC, Route 53, CloudWatch, ECR, EKS service modules
- Cleanup-untagged hunter
- Per-customer cost report (intent-level command)
- Security audit (open ports, public S3, etc.)
- Terraform integration

## Verification path

```bash
# auth sanity
python3 ~/.claude/skills/aws-skill/aws_skill.py iam who-am-i

# read-only sanity
python3 ~/.claude/skills/aws-skill/aws_skill.py ec2 list
python3 ~/.claude/skills/aws-skill/aws_skill.py cost last-30d

# dry-run jumphost
python3 ~/.claude/skills/aws-skill/aws_skill.py jumphost provision --customer dmatrix --dry-run

# real provision
python3 ~/.claude/skills/aws-skill/aws_skill.py jumphost provision --customer dmatrix --confirm

# teardown
python3 ~/.claude/skills/aws-skill/aws_skill.py jumphost teardown --customer dmatrix --confirm-delete
```
