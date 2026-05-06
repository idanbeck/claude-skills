# aws-skill

Customer-tagged, opinionated CLI over AWS via boto3. Use it instead of the AWS console for routine ops on the Epoch account.

See [SKILL.md](SKILL.md) for the Claude-facing usage doc; this README is for humans setting up the skill.

## Install

```bash
python3 -m pip install --user -r ~/.claude/skills/aws-skill/requirements.txt
```

## First-time setup

If `~/.aws/credentials` doesn't exist on this machine yet:

```bash
python3 ~/.claude/skills/aws-skill/aws_skill.py setup
```

Walks through `aws configure --profile epoch` and validates the credentials with an STS GetCallerIdentity call.

For SSO-backed accounts: `aws configure sso --profile epoch`, then `aws_skill.py iam who-am-i` to verify.

## File layout

```
aws-skill/
├── SKILL.md                       Claude-facing usage doc
├── README.md                      this file
├── aws_skill.py                   CLI entry point
├── requirements.txt
├── lib/
│   ├── auth.py                    profile/session/region resolution + setup wizard
│   ├── output.py                  json/table/markdown/ids formatters
│   ├── confirm.py                 --confirm / --confirm-delete guardrails
│   ├── tagging.py                 required-tag policy + tag-filter helpers
│   ├── services/
│   │   ├── iam.py
│   │   ├── ec2.py                 instances, EIPs, SGs, key pairs, AMIs
│   │   ├── s3.py
│   │   ├── rds.py
│   │   ├── lambda_ops.py          ('lambda' is reserved)
│   │   ├── vpc.py
│   │   ├── route53.py
│   │   ├── cloudwatch.py
│   │   ├── ecr.py
│   │   ├── eks.py
│   │   └── cost.py                Cost Explorer
│   └── intent/
│       ├── jumphost.py            provision/teardown
│       ├── inventory.py           cross-service tag-based listing
│       ├── cleanup.py             untagged-resource hunter
│       ├── cost_report.py         per-customer cost report
│       ├── audit.py               security misconfiguration scan
│       └── terraform.py           render intent ops as .tf files
├── templates/
│   ├── jumphost-userdata.sh
│   ├── default-tags.json
│   └── customer-config.example.json
├── customers/                     gitignored — per-customer config
│   └── d-matrix.json              (local only)
├── terraform/                     gitignored — generated .tf files per customer
└── .gitignore
```

## What's in v2 (current)

- IAM (read-only)
- EC2: full lifecycle + EIPs + SGs + key pairs
- S3: read + put/rm + public-access status
- RDS: read + snapshot
- Lambda: read + invoke + log tailing
- VPC: VPCs / subnets / route tables / NAT gateways
- Route 53: zones + records + upsert/delete
- CloudWatch: log groups, log tailing, metric statistics
- ECR: repos, images, docker login token
- EKS: list + kubeconfig writer
- Cost Explorer: total / by-service / by-tag / per-customer report
- Jumphost intent (provision + teardown + terraform render)
- Inventory intent (per-customer or arbitrary tag)
- Cleanup intent (untagged report + safe auto-delete)
- Audit intent (open SGs, public S3, old keys, no-MFA users, public RDS)
- Terraform integration (jumphost-as-tf renderer)

## What's out (v3+)

- Cost optimization recommendations
- Drift detection vs. expected state
- Multi-account aggregation (when account model B becomes relevant)
- Per-resource Terraform import for existing skill-managed resources
- WAF / Shield / GuardDuty service modules

## Verification path

```bash
# auth
python3 ~/.claude/skills/aws-skill/aws_skill.py iam who-am-i

# read sanity across services
python3 ~/.claude/skills/aws-skill/aws_skill.py ec2 list
python3 ~/.claude/skills/aws-skill/aws_skill.py s3 ls-buckets
python3 ~/.claude/skills/aws-skill/aws_skill.py rds list
python3 ~/.claude/skills/aws-skill/aws_skill.py lambda list
python3 ~/.claude/skills/aws-skill/aws_skill.py vpc list
python3 ~/.claude/skills/aws-skill/aws_skill.py route53 zones
python3 ~/.claude/skills/aws-skill/aws_skill.py ecr list
python3 ~/.claude/skills/aws-skill/aws_skill.py cost last-30d

# intent ops (read-only)
python3 ~/.claude/skills/aws-skill/aws_skill.py inventory --customer d-matrix
python3 ~/.claude/skills/aws-skill/aws_skill.py cleanup untagged
python3 ~/.claude/skills/aws-skill/aws_skill.py audit --format table

# d-matrix jumphost (the original use case)
python3 ~/.claude/skills/aws-skill/aws_skill.py jumphost provision --customer d-matrix --dry-run
python3 ~/.claude/skills/aws-skill/aws_skill.py jumphost provision --customer d-matrix --confirm

# or render as terraform instead
python3 ~/.claude/skills/aws-skill/aws_skill.py terraform jumphost --customer d-matrix
```

## Repo conventions

This directory is part of `idanbeck/claude-skills`. Per the existing convention:

- `SKILL.md`, `README.md`, `aws_skill.py`, `lib/`, `templates/` — committed.
- `customers/*.json` — **never committed** (may contain network-sensitive details).
- `terraform/` — **never committed** (generated, may contain CIDRs).
- `*.pem`, `*.key`, `credentials.json`, `config.json` — never committed.
- AWS credentials live in `~/.aws/`, not in this directory.
