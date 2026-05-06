---
name: aws-skill
description: Customer-tagged, opinionated CLI over AWS via boto3. Reads + writes + intent commands across IAM, EC2, S3, RDS, Lambda, VPC, Route 53, CloudWatch, ECR, EKS, Cost Explorer, plus jumphost provision/teardown, security audit, untagged-resource cleanup, per-customer cost reports, and Terraform rendering. Multi-account via AWS profiles.
allowed-tools: Bash, Read
---

# AWS Skill

A CLI wrapper over AWS that encodes our patterns: customer-tagged resources, safe defaults, multi-account auth, intent-level commands. Use it instead of the AWS console for routine ops.

## When to use this skill

- Any AWS read (ec2, s3, iam, rds, lambda, vpc, route53, cloudwatch, ecr, eks)
- Cost lookups (last-30d, by-service, by-tag, per-customer report)
- Provisioning a static-IP jump host for a customer engagement (`jumphost`)
- Generating a Terraform module from an intent op (`terraform jumphost`)
- Running a security audit (open SGs, public S3, old IAM keys, no-MFA users, public RDS)
- Hunting untagged resources (`cleanup untagged`)
- Cross-service inventory by customer or tag
- First-time AWS setup on this machine (`setup` subcommand)

**Do NOT use for:**
- IAM writes (do those in console / Terraform — too easy to break things)
- Bulk S3 sync (use `aws s3 sync` directly — built for it)
- Cluster creation / deletion (Terraform / eksctl — declarative beats imperative)

## First-time setup

```bash
python3 ~/.claude/skills/aws-skill/aws_skill.py setup
```

Walks through `aws configure --profile epoch` and validates with STS. The skill defaults to the `epoch` profile; `--profile NAME` overrides.

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

## Service commands

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

### S3

```bash
aws_skill.py s3 ls-buckets
aws_skill.py s3 ls my-bucket [--prefix path/]
aws_skill.py s3 head my-bucket some/key
aws_skill.py s3 get my-bucket some/key --out ~/Downloads/file
aws_skill.py s3 put my-bucket some/key ~/local/path --confirm
aws_skill.py s3 rm my-bucket some/key --confirm-delete
aws_skill.py s3 public-status my-bucket          # exposure assessment
```

### RDS

```bash
aws_skill.py rds list [--customer NAME]
aws_skill.py rds describe my-db
aws_skill.py rds snapshot my-db --confirm
aws_skill.py rds list-snapshots [--instance-id my-db]
```

### Lambda

```bash
aws_skill.py lambda list [--customer NAME]
aws_skill.py lambda get my-function
aws_skill.py lambda invoke my-function --payload '{"x":1}' --confirm
aws_skill.py lambda invoke my-function --payload @./payload.json --confirm
aws_skill.py lambda logs my-function --since 30m --limit 100
```

### VPC

```bash
aws_skill.py vpc list
aws_skill.py vpc subnets [--vpc-id vpc-xxx]
aws_skill.py vpc route-tables [--vpc-id vpc-xxx]
aws_skill.py vpc nat [--vpc-id vpc-xxx]
```

### Route 53

```bash
aws_skill.py route53 zones
aws_skill.py route53 records --zone-id ZONE_ID
aws_skill.py route53 upsert --zone-id ZONE --name foo.example. --type A --value 1.2.3.4 --confirm
aws_skill.py route53 delete --zone-id ZONE --name foo.example. --type A --value 1.2.3.4 --confirm-delete
```

### CloudWatch

```bash
aws_skill.py cloudwatch log-groups [--prefix /aws/lambda/]
aws_skill.py cloudwatch logs /aws/lambda/my-fn --since 1h --limit 500 [--filter "ERROR"]
aws_skill.py cloudwatch metric --namespace AWS/EC2 --name CPUUtilization --days 1
```

### ECR

```bash
aws_skill.py ecr list                            # repositories
aws_skill.py ecr images my-repo --limit 50
aws_skill.py ecr login                           # docker login command + token
```

### EKS

```bash
aws_skill.py eks list [--customer NAME]
aws_skill.py eks kubeconfig my-cluster --confirm        # writes ~/.kube/config
```

### Cost Explorer

```bash
aws_skill.py cost last-30d                              # total spend
aws_skill.py cost by-service                            # grouped by AWS service
aws_skill.py cost by-tag --key Customer                 # grouped by Customer tag
aws_skill.py cost report --customer dmatrix --days 30   # detailed per-customer report (intent)
```

> **Cost-allocation tag note:** `by-tag` and `report --customer` require the `Customer` tag to be activated as a cost-allocation tag in the AWS Billing console. Otherwise totals come back zero.

## Intent commands

### Jumphost (provision / teardown)

```bash
aws_skill.py jumphost provision \
    --customer dmatrix \
    --allowed-ip 1.2.3.4/32 \
    --confirm

aws_skill.py jumphost teardown --customer dmatrix --confirm-delete
```

Creates: SSH key pair (saved locally), security group with port-22 ingress restricted to `--allowed-ip`, EC2 instance (Ubuntu 22.04 LTS, t4g.small default), Elastic IP, and association. Everything is tagged with `Customer`, `Project=jumphost`, `Owner`, `Environment`, `ManagedBy=zerg-aws-skill`.

Customer-specific config (region, allowed-ingress, instance type, key path) lives at `customers/<name>.json`. Copy `templates/customer-config.example.json` to start a new customer.

### Inventory

```bash
aws_skill.py inventory --customer dmatrix       # all skill-touchable resources for a customer
aws_skill.py inventory --tag-key Project --tag-value jumphost
```

### Cleanup (untagged-resource hunter)

```bash
# Report only — never deletes
aws_skill.py cleanup untagged

# Auto-delete safe categories (unattached EIPs, stopped instances older than 7 days)
aws_skill.py cleanup auto --confirm-delete --older-than-days 7

# Preview what auto would do
aws_skill.py cleanup auto --dry-run
```

### Security audit

```bash
aws_skill.py audit                              # all checks
aws_skill.py audit --key-age-days 60 --format table
```

Checks:
- Security groups with `0.0.0.0/0` ingress on non-web ports (SSH = high; web = info)
- S3 buckets with public ACL grants or missing public-access-block
- IAM access keys older than `--key-age-days` (default 90)
- IAM users with passwords but no MFA
- RDS instances with `PubliclyAccessible = true`
- Resources missing required tags (delegates to `cleanup untagged`)

Output groups by severity (high/medium/low/info) with a recommendation per finding.

### Per-customer cost report

```bash
aws_skill.py cost report --customer dmatrix --days 30
```

Returns total + per-AWS-service breakdown + last-6-months trend, all filtered to the `Customer` tag.

## Terraform integration

Render an intent op as a stand-alone Terraform module instead of executing it via boto3:

```bash
aws_skill.py terraform jumphost --customer dmatrix
```

Writes `terraform/<customer>/{main.tf,variables.tf,outputs.tf,user-data.sh}`. Then:

```bash
cd ~/.claude/skills/aws-skill/terraform/dmatrix
terraform init && terraform plan && terraform apply
```

Same intent — different execution path. Use boto3 path for fast, scriptable provisioning; use Terraform path for declarative, drift-aware infrastructure with shared state.

The `jumphost terraform --customer NAME` shortcut is identical:

```bash
aws_skill.py jumphost terraform --customer dmatrix
```

## Output formats

- `json` (default) — pretty JSON. What Claude expects.
- `table` — psql-style terminal table.
- `markdown` — github-flavored markdown table (good for vault notes).
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

v1+v2 use a single Epoch AWS account with customer-tagged resources. The `--profile` flag is AWS-native — switching to per-customer accounts later is a config swap, not a code change.

## Safety

- Reads are free.
- Writes require `--confirm`.
- Deletes require `--confirm-delete`.
- `--dry-run` previews any operation.
- Skill never stores credentials itself; honors `~/.aws/credentials` and `~/.aws/config`.
- `cleanup auto` only acts on categorically-safe types (unattached EIPs, stopped EC2 older than threshold). Security groups, EBS volumes, key pairs are reported only.

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

### Stand up a customer jump host

```bash
python3 ~/.claude/skills/aws-skill/aws_skill.py iam who-am-i
python3 ~/.claude/skills/aws-skill/aws_skill.py jumphost provision --customer dmatrix --dry-run
python3 ~/.claude/skills/aws-skill/aws_skill.py jumphost provision --customer dmatrix --confirm
# (SSH using the printed hint)
python3 ~/.claude/skills/aws-skill/aws_skill.py jumphost teardown --customer dmatrix --confirm-delete
```

### Cost by customer

```bash
python3 ~/.claude/skills/aws-skill/aws_skill.py cost by-tag --key Customer --format table
python3 ~/.claude/skills/aws-skill/aws_skill.py cost report --customer dmatrix --days 30
```

### Find everything tagged for a customer

```bash
python3 ~/.claude/skills/aws-skill/aws_skill.py inventory --customer dmatrix
```

### Run a security audit before an external review

```bash
python3 ~/.claude/skills/aws-skill/aws_skill.py audit --format table
```

### Clean up forgotten EIPs and stopped instances

```bash
python3 ~/.claude/skills/aws-skill/aws_skill.py cleanup untagged       # see the list
python3 ~/.claude/skills/aws-skill/aws_skill.py cleanup auto --dry-run # preview action
python3 ~/.claude/skills/aws-skill/aws_skill.py cleanup auto --confirm-delete
```

### Hand a jumphost to Terraform instead of executing via boto3

```bash
python3 ~/.claude/skills/aws-skill/aws_skill.py terraform jumphost --customer dmatrix
cd ~/.claude/skills/aws-skill/terraform/dmatrix
terraform init && terraform plan && terraform apply
```
