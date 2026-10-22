---
name: zergdesk-cli
description: Use ZergDesk's first-party CLI (zdesk/zergdesk) for sales or fundraising CRM discovery, scoped record changes, collateral uploads, and knowledge-base reconciliation. Use for any ZergDesk or Zerg CRM question or change, including accounts, deals, pipeline and forecast, activities, tasks, sequences, decks, and syncing the vault's Epoch/CRM to Desk.
---

# ZergDesk CLI

ZergDesk supports sales, fundraising and custom projects. Use `zergdesk` (alias
`zdesk`) to operate its workspace CRM. Public discovery is at
https://zergdesk.com/agents.md. Read https://zergdesk.com/docs/cli.md for command
contracts and https://zergdesk.com/docs/api.md when using direct HTTP. For sales
fields, forecasting, stage history and feature boundaries, read
https://zergdesk.com/docs/sales-crm.md. These URLs work without a source checkout.

## Install and discover

Requires Node.js 22+ and npm. Install a pinned first-party tarball:

```sh
npm install --global https://zergdesk.com/downloads/cli/zergai-zergdesk-0.2.0.tgz
zdesk --version
zdesk --help
zdesk health
```

https://zergdesk.com/downloads/cli/latest.json provides release metadata,
`tarballUrl`, `sha256` and `integrity`. Registry publication is not required for
the direct tarball install; npm resolves its dependencies. Pin a version during
sync runs and upgrade between runs using the manifest's tarball URL. If the global
npm prefix is not writable, install with `--prefix "$HOME/.local"` and add
`$HOME/.local/bin` to `PATH`. The CLI's
`update` command currently targets the npm registry; use the public tarball path
for this release. `help GROUP` documents positional parameters and `routes
FILTER` lists the offline route catalog. A listed route may still require a
browser session.

## Credentials and scope

Have the user sign in to https://zergdesk.com with Zerg SSO, then create a token
in **Account → API tokens**, bound to the intended workspace and optionally a
project. Prefer `workspace:read,crm:read` for discovery. Request `crm:write` only
for authorized data changes and `workspace:write` for project administration.
Membership/role checks and plan limits remain in force. API tokens cannot create
workspaces, mint tokens or enter billing/SSO flows. Local password login and
recovery are retired.

Obtain the token through the agent host's secure secret form, secret manager or
private credential file, never chat. Use `ZDESK_API_TOKEN`, `--token-env NAME` or
`--token-file PATH`; there is no literal token argument. Token files must be
regular, nonsymlink, 0600 files containing a plain token or issued-token JSON.
The CLI leaves the source file intact. Do not extract browser cookies or create
administrative sessions as an access workaround.

```sh
export ZDESK_BASE_URL=https://zergdesk.com
# ZDESK_API_TOKEN comes from the host's secret manager.
zdesk auth configure --profile crm-agent
# Or use: zdesk auth configure --profile crm-agent --token-file /private/path/token.json
zdesk whoami --profile crm-agent
zdesk workspaces list --profile crm-agent
zdesk projects list WORKSPACE_SLUG --profile crm-agent
zdesk config set --profile crm-agent --workspace WORKSPACE_SLUG --project PROJECT_ID
```

Saved profiles are private and pinned to their origin. Set `ZDESK_PROFILE` or
pass `--profile` consistently; an isolated `--config PATH` is useful for another
actor. Never send a production credential to another origin. `config show`
reports context without exposing credentials. The user can revoke a token in
Account; local `auth logout` only forgets the saved credential.

`--workspace` is a **slug**; `--project` is a stable **ID** from `projects list`.
Project administration commands take project URL slugs separately. Firms are
sales accounts or investors, and people/firms are shared workspace records.
Deals and most workflow collections select a project; catalogs are workspace-wide.

## Inspect, export and reconcile

```sh
zdesk workspaces get WORKSPACE_SLUG --profile crm-agent
zdesk pipeline get --profile crm-agent
zdesk firms list --profile crm-agent --search 'Example' --field name
zdesk people list --profile crm-agent
zdesk opportunities list --profile crm-agent
zdesk crm export --profile crm-agent --include-sales --output desk-before.json
```

Read `workspace.plan`, `workspace.limits` and `workspace.usage` before imports.
`-1` means unlimited. Arrange required capacity through the browser/admin flow;
do not bypass a limit. Export to a new private path; existing files are refused.
`--include-sales` follows every page of activities, tasks, resources, catalogs,
views and sequences in addition to the pipeline snapshot.

Before a requested patch, fetch the record by ID and send only intended fields:

```sh
zdesk firms get FIRM_ID --profile crm-agent
zdesk firms update FIRM_ID --profile crm-agent --data @account-patch.json
zdesk people update PERSON_ID --profile crm-agent --data @contact-patch.json
zdesk opportunities update OPPORTUNITY_ID --profile crm-agent --data @deal-patch.json
zdesk activities create --profile crm-agent --data @meeting.json
zdesk tasks create --profile crm-agent --data @follow-up.json
```

Schemas reject unknown fields. Omitted fields are preserved; supplied arrays
replace arrays. Nullable dates use actual `YYYY-MM-DD` strings or `null` to
clear. Activity timestamps include an offset. Discover stage IDs from project
settings. Deal contact roles use `{personId,role}` and references must belong to
the tenant. Person private notes have separate admin access; workspace ownership
alone does not grant it. Shared account changes can affect another project.

For imports use `crm import firms|people|opportunities --file PATH --dry-run`,
review results, then omit `--dry-run` only for authorized writes. JSON and CSV are
supported, in batches of 500. Create base firms, then people, then firm contact
lists and dependent deals. `person.firmId` and `firm.contacts` are independent
links; reconcile both when the workflow uses both. Dry
runs do not save dependencies. Preserve a globally unique random ID and source
mapping before the first write; reruns must reuse it. Inspect each result because
batches can partially succeed. The CLI returns exit 4 on record failures.

An export is a snapshot, not a version lock. Firms/people lack version
preconditions and incremental change tracking. Preserve authored vault content,
provenance and Desk edits; implement explicit conflict detection for syncs rather
than assuming a blind push is safe. No first-party automatic vault sync exists.
After writes, export again and compare affected fields and relationships.

## Collateral and sales work

Use `activities`, `tasks`, `resources`, `catalogs`, `views`, `sequences` with
`list`, `create`, `update ID`; `views delete ID` deletes a saved view. Lists support
`--query firmId=ID`, `opportunityId`, `personId`, `kind`, `status`, `limit`, `offset`;
follow `pagination.hasMore`. Catalogs hold products, segments and competitors.
Resources link files or Markdown, including case studies and contract/invoice
metadata. They do not perform signing or payment collection. Sequences record
manual outreach plans and status; saving one does not send messages.

`decks create --data @deck.json` can take persistent random `id` and `versionId`.
`decks version-update --data @version.json` adds/patches versions.
`decks upload DECK_ID VERSION_ID --file deck.pdf` accepts PDF/PPTX up to 32 MiB;
PPTX conversion needs the server's Google integration. `dataroom upload --file
PATH --data @metadata.json` uploads general attachments. Scoped tokens support
these uploads. Share-link administration and analytics remain browser workflows.
Link attachments to accounts/deals with `resources` metadata and an authenticated
absolute download URL. Uploading does not make a file public.

`crm duplicates firms|people` returns candidates; `crm merge ENTITY SOURCE TARGET`
previews. Apply only an explicitly authorized merge after export and review;
`--apply` removes the source and requires workspace admin rights plus a
workspace-wide token. People merges also require private-note access.

## Results and boundaries

JSON results go to stdout; bounded JSON errors go to stderr. Exit codes: 0
success, 1 local I/O, 2 usage, 3 credentials, 4 API/payload failure, 5 network or
timeout. Mutations are never retried automatically. After an ambiguous timeout,
read by the persisted ID before repeating the write. A discovery request does
not authorize deletes, merges, outreach or private-file uploads.

`ztc ask` invokes the server-owned read-only CRM assistant. Model-provider
requests can include selected CRM context; use it for requested analysis.
Product feedback belongs in Desk's feedback capture UI; deck viewer comments and
CRM activities are not software-feedback tickets.

## Local setup (this machine)

This section is local. Everything above is the public portable skill from
https://zergdesk.com/skills/zergdesk-cli/SKILL.md, fetched 2026-10-22 for CLI
0.2.0. To refresh, compare with that URL and keep this section.

- **Binary.** The global `zdesk` may still be 0.1.1, which has none of the sales
  commands. Run `zdesk --version`. Below 0.2.0, use the pinned side install
  `~/.local/lib/zergdesk-cli-0.2.0/node_modules/.bin/zdesk`; its tarball matched
  the `sha256` in `latest.json`. Don't upgrade the global install without asking,
  because other agents use it.
- **Workspace details live in the vault.** The workspace, project IDs, CLI
  profile and token scopes are in `Epoch/CRM/Zerg CRM.md` in the Obsidian vault.
  Read it before any Desk work and use that profile. Never ask for a token in chat.
- **The vault is the source.** `Epoch/CRM/Desk Sync/desk_sync.py` (`plan`, `sync`,
  `verify`) writes the records that came from the vault: accounts, people, deals,
  activities, tasks, documents, catalogs, views and sequences. To change one, edit
  the vault note or inventory, then run `plan` and `sync`. If you patch such a
  record in Desk instead, the sync keeps your edit and lists it for review.
  Records created only in Desk are left alone.
- **House rules:**
  - CRM text is neutral: states, facts and dates. No blacklist, verdict or
    judgment words.
  - Delete, merge, send outreach or upload private files only after an explicit
    yes for that action.
  - Never use browser cookies or minted sessions as a workaround; the token covers
    everything the sync needs.
  - Write product feedback for the Desk lane as a note in the current week's daily
    folder, for Idan to relay. Don't post board cards.
