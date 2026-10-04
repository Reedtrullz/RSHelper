# Dashboard access policy route inventory

This inventory describes the backend policy in `dashboard/access.py` and the
gate in `dashboard/handlers.py`. A request is authorized before its route
callback runs. Authorization is independent of `Origin` and `Host`; recognized
POST mutations then retain the existing Origin/Host CSRF check.

## Access rules

| Mode | Anonymous access | Bearer access |
| --- | --- | --- |
| `public-demo` | Static root, sanitized health, capabilities, and public market GETs | No private or mutation access |
| `owner` | Static root, sanitized health, and capabilities | Required for market APIs, private state, and mutations |

The owner token is accepted only in `Authorization: Bearer <token>` and is
compared with `hmac.compare_digest`. An absent configured token fails closed.
Capabilities reports only the mode and feature names. Daemon control POSTs
also require the independent `control=True` flag, even after bearer
authentication. VPS deployment remains with control disabled.

Public-demo market reads may refresh the shared in-memory price cache. That
refresh does not load the watchlist, write watch/system alerts, or broadcast
owner alert events. Request logs redact query strings and Authorization
values; URL query parameters never authenticate a request.

## GET routes

| Route | Resource | Public-demo |
| --- | --- | --- |
| `/` | static | Allowed |
| `/api/capabilities` | capabilities | Allowed |
| `/api/health` | sanitized-health | Allowed |
| `/api/scan` | public-market | Allowed |
| `/api/prices` | public-market | Allowed |
| `/api/timeseries` | public-market | Allowed |
| `/api/process` | public-market | Allowed |
| `/api/alch` | public-market | Allowed |
| `/api/confidence` | public-market | Allowed |
| `/api/monitor` | private-state | Denied |
| `/api/signals` | private-state | Denied; watch-dependent |
| `/api/trades` | private-state | Denied |
| `/api/pnl` | private-state | Denied |
| `/api/history` | private-state | Denied |
| `/api/meta` | private-state | Denied; may contain private counts |
| `/api/watchlist` | private-state | Denied |
| `/api/watchlist/check` | private-state | Denied; can update alert state |
| `/api/positions` | private-state | Denied |
| `/api/trader` | private-state | Denied |
| `/api/ge` | private-state | Denied |
| `/api/bank` | private-state | Denied |
| `/api/alerts` | private-state | Denied |
| `/api/events` | private-state | Denied; no public SSE stream |

## POST routes

All POST routes require owner bearer authentication and pass the Origin/Host
check. In `public-demo`, all mutations are denied before body parsing or
callbacks.

| Route | Resource | Additional gate |
| --- | --- | --- |
| `/api/trades` | private-state | — |
| `/api/watchlist` | private-state | — |
| `/api/paper` | private-state | — |
| `/api/ge/collect` | private-state | — |
| `/api/positions` | private-state | — |
| `/api/trader` | daemon-control | `control=True` |
| `/api/monitor` | daemon-control | `control=True` |
| `/api/alerts/read` | private-state | — |
| `/api/trades/delete` | private-state | — |

## Integration boundary

The backend accepts explicit `access_mode` and `owner_token` parameters in
`dashboard.server.run`; the handler factory accepts `mode`, `owner_token`, and
`control`. CLI parsing, private token-file provisioning, and the in-memory browser bearer
flow are now wired in the pending integration package. A production owner UI needs to
send the bearer header on protected API requests; it must not put the token in
a URL, persistent browser storage, or logs. Public mode should be selected
explicitly. A missing or invalid owner token never grants private access.
