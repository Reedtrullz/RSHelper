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

## Deployment verification status

Verify the current live SHA with:

```bash
git rev-parse origin/main
curl -fsS https://rs.reidar.tech/api/health
gh run list --commit "$(git rev-parse origin/main)" --limit 5 --json databaseId,status,conclusion,headSha,url
```

The live SHA — not this file — is the source of truth for what is deployed.

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
  -e "docker_image=ghcr.io/reedtrullz/rshelper:$(git rev-parse --short=12 HEAD)"
```

The playbook validates that the image tag and `APP_VERSION` look like
immutable SHA deploys, starts the container behind a `127.0.0.1` host port,
adds the Caddy site block for `rs.reidar.tech`, verifies the local and public
`/api/health` endpoints expose the exact SHA, and rolls back to the previous
image if any verification step fails.
