# Daemon ownership and launchd migration (#14)

Trader and monitor hold a lifetime flock on a persistent `.pid.lease` inode.
Their owner records contain a per-instance nonce and process start identity.
Status distinguishes `verified_lease`, `legacy_unverified` and `synced_snapshot`;
a PID or imported state document alone cannot certify a running local daemon.
The private control socket uses a short, UID-owned directory and a hash of the
profile PID pathname, so a long HOME/profile path does not exceed Unix limits.
The nonce stays out of CLI/HTTP status receipts and synchronized state.

Stop sends a nonce-checked request to that owner; it never signals a PID read
from a file. A stop receipt distinguishes request acceptance, actual lease
release, timeout and desired service state. A busy loop may still hold its lease
after accepting a stop; the CLI/dashboard retain that distinction. SIGTERM
wakes the owned loop and its final state write/cleanup runs before lease release.
Only the owned control socket is removed. The lease inode and legacy PID evidence
remain; unverified legacy instances require a controlled supervisor restart.

For launchd instances, the installed plist supplies the service kind, domain and
label. Stop disables the service before bootout, preventing KeepAlive from
restarting it. A bootout failure retains the confirmed disabled desired state.
Resume uses the retained service identity to enable/bootstrap that service and
wait for its verified readiness, rather than creating an unmanaged replacement.
Failed bootstrap/readiness disables and unloads the known service. Receipts
report cleanup failures and the last confirmed desired state explicitly; a
failed disable never claims that a KeepAlive service is disabled.
The dashboard's detached start also waits for the particular child process,
matching lease and initial-state readiness. Exited/failed/unready children are
reported as failures and only that spawned process handle is cleaned up.

`monitor --status --json` and `auto-trade --status --json` expose lifecycle
receipts. Stop accepts `--json` for either command. Human-readable stop output
distinguishes shutdown requested from completed; refusal/failure exits nonzero.
Dashboard controls remain owner-authenticated and require `--control`;
production still omits that flag.

The installer stages code and writes plists only for explicit `install`.
`status` reports whether launchd loaded the known jobs without restaging the
synchronizer or creating HOME directories. Install creates private files,
enables the configured service and checks ready receipts after bootstrap.
Successful bootstrap alone is not a successful startup. Failed bootstrap or
readiness triggers disable/bootout of that configured job; cleanup errors
remain actionable on stderr and installation exits nonzero. Installation also
retains the synchronizer's required-signing policy and explicit repository path.

The implementation tests use disposable HOME directories, synthetic provider
cycles, actual child processes and fake launchctl adapters. They do not change
an installed trader, monitor, sync helper or live trading state. Before an
operator migration, capture an app-owned private backup, retain current plists
and source, then restart the known launchd jobs from the reviewed release.
Verify each lease/readiness/desired-state receipt and the required-signing sync
receipt; use the retained plists/source to roll back if startup fails. Reconcile
source readiness without resetting primary-checkout WIP. Private feed transport
and exact synchronized application revisions remain E08-B/#11/#33 gates.
