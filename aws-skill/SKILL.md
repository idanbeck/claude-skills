---
name: aws-skill
description: Customer-tagged, opinionated CLI over AWS via boto3. Reads + writes + intent commands for EC2, IAM, Cost Explorer, plus a `jumphost` provision/teardown for customer engagements. Multi-account via AWS profiles.
allowed-tools: Bash, Read
---

# AWS Skill

A CLI wrapper over AWS that encodes our patterns: customer-tagged resources, safe defaults, multi-account auth, intent-level commands. Use it instead of the AWS console for routine ops.

## When to use this skill

Use this skill when the user wants to:

- Inspect AWS resources (EC2 instances, Elastic IPs, IAM users/roles/policies, security groups)
- Look up cost (last 30 days, by-service, by-tag)
- Provision a static-IP jump host for a customer engagement
- Tear down a customer's jump host
- Inventory all resources tagged for a customer
- Set up AWS auth on this machine for the first time (`setup` subcommand)

**Do NOT use for:**
- IAM writes (do those in console / Terraform — too easy to break things)
- VPC / Route 53 / RDS / S3 writes (v2 scope; not in v1)
- Anything with a corresponding Terraform plan — prefer Terraform for durable infra

## Setup

First-time setup on a new machine:

```bash
python3 ~/.claude/skills/aws-skill/aws_skill.py setup
```

This walks through `aws configure --profile epoch` to create `~/.aws/credentials` and `~/.aws/config`. The skill defaults to the `epoch` profile; pass `--profile NAME` to override.

Dependencies (install once):

```bash
pip install -r ~/.claude/skills/aws-skill/requirements.txt
```

## Universal flags

```
--profile NAME           AWS profile (default: epoch, or AWS_PROFILE env)
--region REGION          override profile region
--format FMT             json (default), table, markdown, ids
--confirm                required for write operations
--confirm-delete         required for destructive operations (separate flag)
--dry-run                preview, don't execute
```

Reads are free. Writes require `--confirm`. Deletes require `--confirm-delete` — intentionally a different flag from `--confirm` to prevent muscle-memory mistakes.

## Commands

### IAM (read-only)

```bash
aws_skill.py iam who-am-i               # STS GetCallerIdentity + account alias
aws_skill.py iam list-users
aws_skill.py iam list-roles
aws_skill.py iam list-policies          # customer-managed by default
aws_skill.py iam list-policies --scope AWS
```

### EC2

```bash
# reads
aws_skill.py ec2 list                              # running + pending only
aws_skill.py ec2 list --all                        # include stopped/terminated
aws_skill.py ec2 list --customer dmatrix
aws_skill.py ec2 describe i-0abcd1234
aws_skill.py ec2 addresses --customer dmatrix      # Elastic IPs

# writes (--confirm)
aws_skill.py ec2 start i-0abcd1234 --confirm
aws_skill.py ec2 stop  i-0abcd1234 --confirm
aws_skill.py ec2 alloc-eip --confirm
aws_skill.py ec2 associate-eip --allocation-id eipalloc-xxx --instance-id i-xxx --confirm

# deletes (--confirm-delete)
aws_skill.py ec2 terminate i-0abcd1234 --confirm-delete
aws_skill.py ec2 release-eip eipalloc-xxx --confirm-delete
```

### Cost Explorer

```bash
aws_skill.py cost last-30d                  # total spend
aws_skill.py cost by-service                # grouped by AWS service
aws_skill.py cost by-tag --key Customer     # grouped by Customer tag value
aws_skill.py cost last-30d --days 7         # custom window
```

> **Note:** `by-tag` requires the tag (e.g. `Customer`) to be activated as a cost-allocation tag in the AWS Billing console. Otherwise it returns empty.

### Jumphost (intent-level)

Provision a complete static-IP jump host for a customer engagement:

```bash
aws_skill.py jumphost provision \
    --customer dmatrix \
    --allowed-ip 1.2.3.4/32 \
    --confirm
```

Creates: SSH key pair (saved locally), security group with port-22 ingress restricted to `--allowed-ip`, EC2 instance (Ubuntu 22.04 LTS, t4g.small default), Elastic IP, and association. Everything is tagged with `Customer`, `Project=jumphost`, `Owner`, `Environment`, `ManagedBy=zerg-aws-skill`.

Tear down everything tagged `Customer=<name> Project=jumphost`:

```bash
aws_skill.py jumphost teardown --customer dmatrix --confirm-delete
```

Customer-specific config (region, allowed-ingress, instance type, key path) lives at `customers/<name>.json`. Copy `templates/customer-config.example.json` to start a new customer.

### Inventory

```bash
aws_skill.py inventory --customer dmatrix       # all resources for a customer
aws_skill.py inventory --tag-key Project --tag-value jumphost
```

## Output formats

- `json` (default) — pretty JSON. What Claude expects.
- `table` — psql-style terminal table.
- `markdown` — github-flavored markdown table.
- `ids` — one resource ID per line. Composable: `aws_skill.py ec2 list --format ids | xargs ...`

## Required-tag policy

Every skill-managed resource carries:

| Tag         | Example              | Purpose                                  |
| ----------- | -------------------- | ---------------------------------------- |
| Customer    | `dmatrix`            | cost allocation, cleanup, inventory      |
| Project     | `jumphost`, `poc`    | sub-allocation within customer           |
| Owner       | `idan@zergai.com`    | who to ask                               |
| Environment | `dev`/`staging`/`prod` | lifecycle                              |
| ManagedBy   | `zerg-aws-skill`     | distinguish skill-managed from manual    |

## Account model

v1 uses a single Epoch AWS account with customer-tagged resources. The `--profile` flag is AWS-native — switching to per-customer accounts later is a config swap, not a code change.

## Safety

- Reads are free.
- Writes require `--confirm`.
- Deletes require `--confirm-delete`.
- `--dry-run` previews any operation.
- Skill never stores credentials itself; honors `~/.aws/credentials` and `~/.aws/config`.

## Errors

Errors are emitted as `{"error": "..."}` JSON with non-zero exit code:

| Code | Meaning                                                  |
| ---- | -------------------------------------------------------- |
| 2    | Auth failure (profile missing, SSO expired, etc.)        |
| 3    | Confirmation required (re-run with `--confirm`)          |
| 4    | Local file conflict (e.g. SSH key already exists)        |
| 5    | Bad arguments (missing customer config, etc.)            |
| 10   | AWS API error or unexpected exception                    |

## Common workflows

### Stand up the d-Matrix jump host (today's use case)

```bash
# 1. Verify auth
python3 ~/.claude/skills/aws-skill/aws_skill.py iam who-am-i

# 2. Dry-run the provision
python3 ~/.claude/skills/aws-skill/aws_skill.py jumphost provision \
    --customer dmatrix --dry-run

# 3. Provision for real
python3 ~/.claude/skills/aws-skill/aws_skill.py jumphost provision \
    --customer dmatrix --confirm

# 4. SSH to verify (uses key path in customers/d-matrix.json)
ssh -i ~/.ssh/aws-skill-dmatrix-jumphost ubuntu@<EIP-from-step-3>

# 5. When d-Matrix engagement ends
python3 ~/.claude/skills/aws-skill/aws_skill.py jumphost teardown \
    --customer dmatrix --confirm-delete
```

### Check cost by customer

```bash
python3 ~/.claude/skills/aws-skill/aws_skill.py cost by-tag --key Customer --format table
```

### Find everything tagged for a customer

```bash
python3 ~/.claude/skills/aws-skill/aws_skill.py inventory --customer dmatrix
```
