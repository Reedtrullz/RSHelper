# Confidence acquisition

Overlapping history requests in one process share an acquisition for the same
canonical profile cache path, item and interval. Different profiles or intervals
remain independent. Each caller receives its own result copy. At most 32 history
acquisitions are admitted; the existing four provider slots, shared request
pacing and 60-second acquisition deadline still apply. Expired Wiki completions
cannot replace the cache. Failed acquisitions release their admission slot.

Both batch interfaces collapse duplicate IDs, take at most 30 unique items and
report truncation on stderr. Cross-process callers retain the existing shared
pacing; this in-memory coalescer does not claim cross-process single dispatch.

Dashboard scores depend on market revision and effective configuration, with a
ten-minute maximum lifetime and 512 stored item results. Current price-dependent
profitability is recomputed against the new quote; unchanged candle acquisition
can use the existing fresh disk cache. Old completions cannot populate a newer
score generation. Results disclose their market revision, current profit and
expected GP/hour. Missing or unusable Wiki history is explicit; Tracker supplies
no candles. A valid zero confidence is displayed as zero rather than hidden.

Local validation on 12 October 2026: eight targeted concurrency/deadline/config
cases and the 914-test offline suite passed (66 files, four provider skips).
Browser authentication and 16 view scenarios passed. Live CLI JSON and four
overlapping authenticated HTTP requests agreed on revision 1 with Wiki history.
That live run reused a fresh history cache; controlled tests prove single dispatch.

A bounded Sonnet diff review identified shared exception re-raising and an overly
broad test event hook; both were corrected and tested. Its other claims were
checked against source: deadline rejection is intentional; finally blocks unwind
in lexical order; profile path resolution enforces isolation; Config uses JSON
scalars; hashing sorts keys; market generations cannot share score dictionaries;
eviction is bounded insertion order, not an LRU promise; UI reasons are escaped.
The post-review full-suite result is retained separately. Deployment acceptance
is pending signed commits, exact-head CI and the controlled runtime handoff.
