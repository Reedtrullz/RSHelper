# Migration and replication at the owner profile size

The approved synthetic-demo transition was quiesced on 12 October 2026. Private
app-owned backups passed inspection on both hosts. The Mac backup contains
22,163 trades; the VPS has 8,331 trades from the older published Mac snapshot.
Full row comparisons against the published source establish the copied financial
and watchlist ancestry. The VPS's two copied open lots are superseded by the
Mac authority's empty current position snapshot. VPS dashboard alerts have their
own origin: the installed publication helper excludes alerts, and there is no
tracked alerts file in the published history examined.

The first rehearsal exposed quadratic manifest validation: a 100-trade migration
preview validated full manifests 406 times. Migration and packet verification
now group records by kind and declared origin, retaining every per-record proof
check and the original migration order. Native lot consumption totals are
collected once. A regression test bounds full-manifest validation work, checks
mixed origins and original order, and confirms missing lineage still fails.

The complete retained-backup rehearsal passed migration, forward transfer,
reverse transfer, a second forward revision and exact-packet retry. Both copies
converged to 22,163 trades, zero positions, 400 alerts and one watch. The two stale
VPS position copies were reconciled through the existing app-owned legacy
adapter before activation; no artificial trade was added. Rehearsal directories
were removed; private backups, UUID decisions, previews and receipts remain in
the ignored execution directory with restricted permissions.

This is rehearsal evidence. Neither real profile has been activated, the raw
publication channel has not been retired, and synthetic bytes have not been
published at this checkpoint. The owner has approved the synthetic field policy
and staged transition. A fresh Anti review attempt was unavailable because the
Google account returned `VALIDATION_REQUIRED`; it is not a successful review.
