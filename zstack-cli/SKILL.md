---
name: zstack-cli
description: Use when operating ZStack through its first-party `zstack` CLI, including logging in, creating API tokens, listing workspaces, deploying environments, streaming logs, wiring domains, managing resources/units, or opening runtime shells for ZStack-backed apps.
---

# ZStack CLI

Use the `zstack` CLI instead of scraping the ZStack web UI whenever you need to inspect or operate workspaces, deployments, resources, domains, deploy logs, runtime DB/files/secrets, admin capacity, GitHub source discovery, or shell access.

## Defaults

- Run from `/Users/idanbeck/zerg-stack/zstack` unless the user asks for another repo.
- CLI source lives in `cli/zstack`.
- Config is `~/.config/zstack/config.json`; environment overrides are `ZSTACK_BASE_URL`, `ZSTACK_TOKEN`, `ZSTACK_SESSION_TOKEN`, `ZSTACK_WORKSPACE`, `ZSTACK_CONFIG_PATH`.
- Prefer API tokens for automation. Browser session login is fine for local operator tasks.
- Prefer JSON-returning commands for scripts and agents.

## Build

```bash
cd /Users/idanbeck/zerg-stack/zstack/cli/zstack
go build -o zstack .
```

Use `./zstack ...` from the build directory or install the binary onto `PATH`.

## Common Workflows

Authenticate:

```bash
zstack auth login --email "$EMAIL" --password "$PASSWORD"
zstack auth whoami
```

Create a workspace-bound automation token:

```bash
zstack auth token create \
  --name agent \
  --workspace zstack \
  --scope workspace:write \
  --scope deploy:write \
  --scope resource:write \
  --scope domain:write
```

Inspect workspaces and deployments:

```bash
zstack workspace list
zstack workspace show zstack --json
zstack workspace branches --workspace zstack
zstack workspace branch-deploy --workspace zstack --source-env <environment-id> --branch feature/foo
zstack deploy list --app zstack --limit 20
```

Deploy and follow logs:

```bash
zstack env deploy --id <environment-id> --follow
zstack deploy logs <deploy-id> --follow
```

Open runtime shell:

```bash
zstack shell --env <environment-id>
```

Wire a domain:

```bash
zstack domain wire --env <environment-id> --hostname dev.example.com --provider godaddy --zone example.com
```

Manage resource topology:

```bash
zstack resource list --workspace zstack
zstack unit list --env <environment-id>
zstack resource promote --workspace zstack --unit-id <unit-id> --name shared_database
zstack env resources show --env <environment-id>
zstack env resources scale --env <environment-id> --vm-size shared-cpu-2x
zstack unit backup <unit-id>
```

Inspect runtime data and files:

```bash
zstack db info --env <environment-id>
zstack db table --env <environment-id> --schema public --table users --limit 20
zstack db query --env <environment-id> --sql 'SELECT now()'
zstack files list --env <environment-id> --path /app
zstack files download --env <environment-id> --path /app/file.txt --out file.txt
zstack secrets list --env <environment-id>
```

Admin and source discovery:

```bash
zstack github repos --owner Epoch-ML
zstack github branches --owner Epoch-ML --repo zerg
zstack admin overview
zstack admin capacity
zstack admin queue reconcile
```

## Safety

- Do not run restart, suspend, resume, rollback, domain delete, or resource topology mutations unless the user asked for the operation or it is clearly required by the task.
- For production environments, show the target workspace/environment before mutating.
- If a command returns a deploy id, use log streaming to verify the deploy completed.
