# RSHelper VPS deploy

This deploys RSHelper to the Racknerd VPS at:

- Public URL: https://rs.reidar.tech
- GitHub repository: https://github.com/Reedtrullz/RSHelper
- VPS: 198.23.137.16 (`Racknerd-Deploy`, user `deploy`)
- Container image: `ghcr.io/reedtrullz/rshelper:<git-sha>`
- Container: `rshelper`
- Host port: `127.0.0.1:5556 -> container:5555`
- Remote app dir: `/opt/apps/rshelper` (state volume at `/opt/apps/rshelper/data`)

The VPS never clones this source repository. The intended flow is:

```text
local code -> GHCR image -> Ansible pulls image on VPS -> Caddy reverse proxy
```

The GitHub Actions version of the flow (`.github/workflows/ci.yml`):

```text
push/PR -> automatic checks -> main-only Docker build/push -> main-only Ansible deploy -> exact-SHA public health verification
```

`probe-sources.yml` is a manual (dispatch-only) diagnostic that curls
candidate GE data sources from the VPS host and prints HTTP codes. Run it
whenever a source's reachability needs re-checking:

```bash
gh workflow run probe-sources.yml --repo Reedtrullz/RSHelper
```

## Deployment verification status

Verify the current live SHA with:

```bash
git rev-parse origin/main
curl -fsS https://rs.reidar.tech/api/health
gh run list --commit "$(git rev-parse origin/main)" --limit 5 --json databaseId,status,conclusion,headSha,url
```

The live SHA — not this file — is the source of truth for what is deployed.

## Syncing local trading state (trades, watchlist, snapshots)

The VPS state volume (`/opt/apps/rshelper/data`, mounted as the container
HOME) is empty until you seed it. The deploy playbook now copies the
repo-tracked `data/state/` directory into the volume before the container
starts, so the live Paper Trading history matches your local journal:

```bash
scripts/sync-state.sh          # copies ~/.config/rshelper state -> data/state
git add data/state
git commit -m "state: sync trading history"
git push                       # CI deploys; playbook seeds the volume
```

The sync is additive and intentionally excludes `config.toml` and
`active_profile`; see `data/state/README.md`.

## OSRS Wiki access from the VPS

The OSRS Wiki API (Cloudflare-fronted) returns HTTP 403 for the VPS datacenter
IP (confirmed 2026-07-31 with both `curl` and `urllib` from the VPS host,
independent of User-Agent). The API client falls back to the GE Tracker
all-items dump (`www.ge-tracker.com/api/items`, no auth, verified reachable
from the VPS) for item metadata, live buy/sell prices, and a quantity-based
volume proxy, so the deployed dashboard serves live item data instead of an
empty list. Real 5m/1h trade-volume timeseries remain wiki-only; `server.py`
still survives a total failure of both sources.

To seed item data, copy a populated `~/.cache/rshelper` from a machine that
can reach the wiki into the container HOME at
`/opt/apps/rshelper/data/.cache/rshelper`, then restart the container:

```bash
cd /opt/apps/rshelper && docker compose -f compose.production.yml restart
```

The mapping cache is served stale for up to 72h; the GE Tracker fallback
makes seeding optional for live prices.

## One-time prerequisites

GitHub Actions secrets (set in the repo settings):

```text
VPS_SSH_PRIVATE_KEY = private SSH key for deploy@198.23.137.16
VPS_SSH_HOST_KEY = exact public host key line for 198.23.137.16
```

Get the host key from a trusted local source and review it once:

```bash
ssh-keyscan -T 10 -t ed25519 198.23.137.16
```

The CI job compares a fresh `ssh-keyscan` against `VPS_SSH_HOST_KEY` before
writing `known_hosts`; it fails the deploy on mismatch instead of trusting
whatever key appears during the run.

## Local/manual deploy

Requirements: Docker, `ansible-playbook` with the `community.docker`
collection, and SSH access to the VPS as `deploy`.

```bash
APP_VERSION=$(git rev-parse HEAD) ansible-playbook \
  -i deploy/inventory/hosts.yml deploy/playbook.yml \
  -e "docker_image=ghcr.io/reedtrullz/rshelper@${RSHELPER_IMAGE_DIGEST:?Set the reviewed registry sha256 digest}"
```

Use the digest emitted by the successful GHCR build for the requested commit.
CI passes that digest directly; SHA-shaped tags and mutable tags are refused.
Docker resolves an OCI index for `linux/amd64`; the verifier checks the pulled
digest, actual platform, OCI revision label and root-owned baked build metadata
before replacing the service. Runtime `VERSION` never supplies health's build
revision. Local/public receipts must match the baked SHA and declared digest,
and Docker must report the exact image ID inspected during preflight.

Rollback retains the previous image's repository digest, OCI revision and
physical image ID, plus a tagged local retention reference. It uses the recorded
digest with `pull: never` and verifies the restored image ID. Existing images
from before this change have no baked metadata; that initial rollback baseline
is explicitly legacy and uses its inspected OCI revision and previous health
format. Once upgraded, rollback also requires baked SHA/digest health receipts.
Artifact verification does not certify state-schema rollback compatibility;
the separate #32 recovery drill supplies that gate. A candidate preflight failure
leaves the existing container and saved Compose configuration intact. Candidate
metadata is copied from an unstarted disposable container; preflight executes
no candidate code and mounts no application state.

## Reviewed Python base refresh

The old base was the moving `python:3.11-slim` tag. On 2026-10-04, the Docker
Registry API returned index
`sha256:6f31d6e9ba2b0a787a3f81c37b004155b87b9efa1b771182bd550c1615745be5`
and the selected `linux/amd64` manifest
`sha256:922f47525757de33aff59f24cdfc85f412ac4a06aa8af7c7e9028d584b7bcdeb`.
Both response bodies matched their registry digest headers. Dockerfile pins the
selected platform manifest and records that base digest in the built metadata.

For a refresh, inspect `python:3.11-slim` with
`docker buildx imagetools inspect python:3.11-slim --raw`, select exactly one
Linux/amd64 manifest, and verify its digest against the registry response.
Record old/new index and platform digests in the PR, update `BASE_IMAGE_DIGEST`,
then run offline/Python3.11/Node checks, a Linux/amd64 fixture image build and
the artifact mismatch/rollback receipt checks. Release only after exact-head
CI and actual digest/revision receipts pass. No scheduled tag-only refresh.

## Owner access boundary

The production command explicitly serves owner mode. Static HTML, `/api/health` and `/api/capabilities` are public; every market/private API and mutation requires an owner bearer token independently of Origin/Host. Caddy terminates HTTPS and proxies to the existing loopback port; forwarded identity headers confer no access. Daemon control remains disabled because production never passes `--control`.

First owner startup atomically provisions a random 256-bit credential in the selected profile's `owner.token`, owned by container UID1000 with0600 permissions. It remains in the existing private container HOME volume, is excluded from backup allowlists and state-sync scripts, and is never placed in Git, Compose environment values, process arguments, URLs, localStorage or logs. Invalid/permissive/symlinked token files fail startup rather than falling back to anonymous access. Local `dashboard --owner-token-file PATH` selects another private file; public `dashboard --access-mode public-demo` exposes market GETs only and refuses private/SSE/mutation callbacks.

To connect, obtain the credential through the owner's authenticated SSH/local file access and enter it in the dashboard's password field over HTTPS (loopback HTTP is acceptable locally). Do not paste it into an issue, command argument, shared screenshot or browser URL. The session keeps the token only in memory and sends Authorization headers, including for fetch-stream SSE. Disconnect clears private state and destroys the session; a page reload requires reconnection. No password identity service or implicit proxy trust is claimed. Public/private replication and historical Git-data disposition remain separate E08 acceptance gates.

State-only sync verifies private record availability inside the owner container through `deploy/check_state.py`. The bearer credential stays in that container, and the CI log receives only boolean authentication/schema success; record values and counts are not printed. Public `/api/health` remains the sanitized deployment receipt.
