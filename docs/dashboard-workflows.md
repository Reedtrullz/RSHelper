# Dashboard workflows and acceptance

Scan, inspect the source and directional economics, watch an item, then use the
separate paper workflow and review its recorded lots. The expandable help on the
empty inspector explains eligibility, missing history and Tracker standing-order
volume. Illustrative GP/hr and confidence are not promised returns or success
probabilities. Confidence exposes reliability, profitability, recency and trend.
Unknown evidence remains unknown.

Flip JSON, CSV, HTML and terminal ROI use the selected buy leg. Traditional
mode buys at API low; arbitrage buys at API high. The API field names retain their
instant-buy/instant-sell meaning. Server tax, net profit and throughput also
appear in the inspector and scan explanations. Watchlist values explicitly use
instant execution; margin charts use the configured scan direction.

Use Left/Right/Home/End on the view tabs. Item and sort controls are native
buttons. Enter on an item moves focus to its inspector. Native alert dialogs
contain focus, close with Escape or Cancel, and return focus to the opener or
Watchlist if refresh replaced it. Invalid whole-number inputs preserve the draft
and announce their error. Chart disclosures contain the actual plotted values,
UTC dates and unknown marks. Reduced-motion preferences disable animation.

Narrow layouts stack the inspector below a horizontally scrollable table; view
tabs scroll horizontally and controls have at least 44px targets. Bank cards
offer a keyboard/touch details action as well as their tooltip.

URL fragments support only known view names and positive item IDs, for example
`#view=market&item=4151`. Private views require owner reconnection; the bookmark
survives that gate. Invalid, duplicate or unsupported parameters fall back to
Market. Generated URLs contain no tokens, notes, journal records or preset names.

Enter a preset name and save up to ten known scan settings, each name at most
40 characters. Settings include chips, density, Flips/Alchemy and one or two
supported sort keys. Active state and named presets live in this browser's
localStorage, bounded to 16KiB when read, scoped by the authenticated profile
UUID. Another profile has a separate namespace. Legacy unidentified profiles
cannot save presets. Reset removes that profile's preferences. These browser
preferences are outside financial backup/replication and do not survive clearing
browser storage or moving to a different browser.

## Evidence and remaining human trials

Disposable synthetic browser trials verified native Enter/tab navigation,
Escape and focus fallback after a refresh, editable fractional-input rejection,
chart data tables, named-preset save/load and reload/reconnect, and Back/Forward
view/item restoration. The browser trial found and fixed the initial bookmark
loss, Enter interception, missing inspector on tab return and unusable preset
prompt. No owner financial state was modified for those trials.

At 320px/375px/768px, the alert dialog measured 296px/351px/600px wide,
respectively, within the viewport. Its narrow controls measured at least 44px
high. Simulated 200% pinch zoom was exercised separately; this is not evidence
of physical touch or a desktop screen-reader/zoom acceptance trial.

The Python suite has 1,084 cases across 79 files, with four named offline
provider skips; seven fresh Wiki provider cases pass separately. Directional
output fixtures cover all four CLI formats and capital sizing; watch fixtures
cover positive, zero and stale prices. Node tests cover URL validation, profile
isolation, tab relationships, unknown chart data and current-view fencing.
Production-Python 3.11 passes the seven catalog and six output-contract cases.

The owner trials for #26 (first-use clarity), #24 (screen reader) and #25
(physical touch and desktop zoom) remain open. For a bounded trial, inspect an
excluded item, explain the buy/sell/tax and unknown-history messages, navigate
tabs/items/dialogs with keyboard and reader, open chart tables, and use an alert
dialog and Bank details on a phone. Report the action, device/reader and any
unreachable control. Save and reload a scan preset if useful. These trials do
not require placing an offer or modifying a financial record.

## Review disposition

One scoped Anti Sonnet review (`20261012T161732Z-7a0d53dc`) completed in
33.360s with 23,966 input and 1,404 output tokens, complete diff coverage and
no fallback. Native inspection triaged every finding:

1. Scan explanation repeats are bounded linear passes over a pure function;
   exclusion behavior is directly covered. No side effects or quadratic work.
2. CLI explanation repeats are pure and bounded by the selected top rows;
   directional output fixtures prove agreement. No speculative cache added.
3. Watch division is guarded by `price_issue`, which rejects high/low <=0.
   Actual zero/stale callback fixtures omit numeric economics and retain reasons.
4. Owner connect explicitly awaits `fetchData` before URL restoration. The
   claimed contrary ordering is absent; actual reconnect restoration passes.
5. Preset state is validated before loading; stale/out-of-bounds select values
   fail closed. No arbitrary state or scripting is accepted.
6. Native closed-dialog `close()` is a no-op; removed dialogs are outside the
   query. Actual Escape/Cancel and replaced-opener focus behavior pass.
7. The auth harness is isolated. Its rejected-form stub now models `.close()`;
   errors must keep the form open. Real dialogs are checked in the browser.
8. Added zero/stale callback coverage for the new economics fields.
9. `/api/meta` belongs to the private-state route policy and is denied to
   unauthenticated/public-demo callers. UUID is a namespace, not authentication;
   browser-origin access cannot be secured by hiding that UUID.
10. Python caches imports. Reading the small activation manifest reflects the
    active identity; caching it could retain a stale profile namespace.

Later browser-driven changes were inspected and regression-tested natively.
Technical issue acceptance additionally requires signed CI, exact production
identity and Mac/private replication verification; a local pass is not deployment.
