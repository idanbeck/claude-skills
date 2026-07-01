---
name: zstack-ops
description: Use when operating, debugging, or extending ZStack workspaces, deployments, provider resources, domains, telemetry, or API-driven deploy flows.
---

# ZStack Ops

## Scope

Use this skill for ZStack control-plane work: workspace provisioning, deploy failures, live logs, Fly resources, domains/DNS, telemetry, and API automation.

Work from `/Users/idanbeck/zerg-stack/zstack` unless the task names another repo.

## Safety

- Prefer the ZStack API over direct database edits.
- Do not print API tokens, session cookies, or provider credentials.
- Use `/private/tmp/zstack-cookie.txt` for curl cookies and overwrite it between sessions.
- When `fly` cannot find auth locally, pass `FLY_ACCESS_TOKEN` from `~/.fly/config.yml` inside the same command and never echo it.
- Confirm the target workspace, environment, branch, and provider app before changing live infrastructure.

## Auth

Set the base URL and log in with a cookie jar:

```bash
ZSTACK_BASE_URL=https://zergstack.com
ZSTACK_COOKIE=/private/tmp/zstack-cookie.txt
curl -sS -c "$ZSTACK_COOKIE" \
  -H 'content-type: application/json' \
  -d "{\"email\":\"$ZSTACK_EMAIL\",\"password\":\"$ZSTACK_PASSWORD\"}" \
  "$ZSTACK_BASE_URL/api/auth/login"
```

Verify the session:

```bash
curl -sS -b "$ZSTACK_COOKIE" "$ZSTACK_BASE_URL/api/auth/me"
```

## Discover State

List workspaces:

```bash
curl -sS -b "$ZSTACK_COOKIE" "$ZSTACK_BASE_URL/api/workspaces"
```

Read one workspace and its environments:

```bash
curl -sS -b "$ZSTACK_COOKIE" "$ZSTACK_BASE_URL/api/workspaces/<workspace-slug>"
curl -sS -b "$ZSTACK_COOKIE" "$ZSTACK_BASE_URL/api/envs/<environment-id>"
```

Read provider resources, domains, and telemetry:

```bash
curl -sS -b "$ZSTACK_COOKIE" "$ZSTACK_BASE_URL/api/envs/<environment-id>/resources"
curl -sS -b "$ZSTACK_COOKIE" "$ZSTACK_BASE_URL/api/envs/<environment-id>/domains"
curl -sS -b "$ZSTACK_COOKIE" "$ZSTACK_BASE_URL/api/envs/<environment-id>/telemetry"
```

## Deploy Debugging

Find recent deploys:

```bash
curl -sS -b "$ZSTACK_COOKIE" "$ZSTACK_BASE_URL/api/deploys?app=<app-slug>&env=<env-name>&limit=5"
```

Read a deploy and logs:

```bash
curl -sS -b "$ZSTACK_COOKIE" "$ZSTACK_BASE_URL/api/deploys/<deploy-id>"
```

Stream logs while a deploy is running:

```bash
curl -N -b "$ZSTACK_COOKIE" "$ZSTACK_BASE_URL/api/deploys/<deploy-id>/stream?after=0"
```

Diagnose in this order:

1. Read `deploy.status`, `deploy.error`, branch, commit, and release fields.
2. Inspect the last 200 log lines, then find the first fatal build/runtime error.
3. Check whether the app deploy failed, the machine started but health failed, or the control-plane status is stale.
4. Compare `zstack.yaml` source settings with the target repo's deploy files (`fly.toml`, Dockerfile, package files, migration docs).
5. For Fly-backed apps, compare API resources with `fly status`, `fly logs`, `fly machines list`, and `fly volumes list`.

## Retry Deploy

Trigger a manual deploy:

```bash
curl -sS -b "$ZSTACK_COOKIE" \
  -H 'content-type: application/json' \
  -d '{"branch":"<branch-name>"}' \
  "$ZSTACK_BASE_URL/api/envs/<environment-id>/deploy"
```

After triggering, stream the returned deploy id until it reaches `success` or `failed`.

## Relevant API Surface

- `POST /api/auth/login`
- `GET /api/auth/me`
- `GET /api/workspaces`
- `GET /api/workspaces/:slug`
- `GET /api/envs/:id`
- `POST /api/envs/:id/deploy`
- `POST /api/envs/:id/restart`
- `POST /api/envs/:id/suspend`
- `GET /api/envs/:id/resources`
- `PATCH /api/envs/:id/resources`
- `POST /api/envs/:id/resources/apply`
- `GET /api/envs/:id/domains`
- `POST /api/envs/:id/domains`
- `POST /api/envs/:id/domains/:domainId/check`
- `POST /api/envs/:id/domains/:domainId/apply-dns`
- `POST /api/envs/:id/domains/:domainId/wire`
- `GET /api/envs/:id/telemetry`
- `GET /api/deploys`
- `GET /api/deploys/:id`
- `GET /api/deploys/:id/stream`
