# RSHelper state corruption diagnosis and recovery boundary

RSHelper refuses to mutate state after a JSON, schema, extension-bound, or
lock failure. Treat the original bytes as evidence. Diagnosis is read-only:
record the safe error, identify the affected path, and inspect state only
through application readers or a disposable copy. Do not edit, truncate,
replace, move, or delete files under `~/.config/rshelper/` by hand.

## Local writer behavior

The launchd trader has `KeepAlive: true`, so stopping its process is temporary:
launchd can start it again. Do not use a process stop as a recovery hold or
attempt to keep it down by editing its state. If repeated restarts or writes
are a concern, leave state untouched and report the affected path and
diagnostic to the operator responsible for the service.

## Recovery availability

The project does not yet provide an app-owned backup/restore workflow. Until
the forthcoming #28 feature supplies validated backups, an auditable restore
selection, and application-controlled writes, recovery is unavailable. Retain
the corrupt bytes in place and report that recovery is unavailable; do not
recommend manual overwrites or filesystem restoration. The prepared strict deploy merge (slice B, not yet integrated)
will abort on validation or lock errors before any replacement. The existing
deploy helper remains in place until the recovery prerequisite is verified. Image rollback does not restore state.

After #28 is available, its application-owned workflow must preserve the
original bytes, validate the selected backup, identify exactly which state is
restored, and perform the mutation under the shared writer locks. This note
does not authorize a recovery operation before that workflow exists.
