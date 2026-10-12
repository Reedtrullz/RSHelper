# Processing models and evidence

Processing results are illustrative models. Every legacy hourly rate is still
unverified; `gp_per_hour` is null and CSV leaves that cell empty. The distinct
`model_profit` and `model_gp_per_hour` retain explicitly labelled estimates.
Missing yield/success facts also leave `profit` and ROI null. No recipe executes
game actions or changes trader strategy defaults.

The shared breakdown uses inputs per run, expected outputs per run, process fee
per output and `ge_tax` per sold output. An outputs-per-hour rate is converted to
runs before calculating batch profit. Ordinary furnace iron has 50% expected
success; this is an expectation across attempts, not a guaranteed batch yield.
Unknown success uses an explicit 100% illustrative assumption while keeping the
actual probability unknown. Models disclose this distinction and evidence gaps.

Throughput is limited by input acquisition, action rate, illustrative output
sell volume and optional capital. Every input limit participates; an unknown or
zero limit blocks a positive capacity model. An output item's buying limit does
not restrict selling it. Four-hour buying limits are converted to an illustrative
hourly acquisition cap; actual account purchase-window capacity belongs to the
shared budget work. Standing-order volume is not executed-volume evidence.

## Account facts

Optional private profile configuration supplies facts without inference:

```toml
[account]
membership = "member" # unknown, free, or member
levels = { smithing = 30 }
unlocks = { example_route = true }
```

Levels are integers 0–99. Named unlocks are true/false; omitted membership, levels
and unlocks remain unknown. Each map is bounded to 100 entries/100-character names.
The scanner distinguishes eligible, ineligible and unknown methods. Known
ineligible methods are excluded; unknown methods remain labelled models. The
CLI and owner dashboard use the same context. Public-demo scans ignore private
account facts. `--members-only` selects member methods and is independent of
whether the account is known to be a member. CLI name/skill/top filters can narrow
display beyond the dashboard's configured common filters.

## Source review boundary — 12 October 2026

- [Smithing](https://oldschool.runescape.wiki/w/Smithing): classic bar inputs,
  levels and ordinary-furnace success. Ring/Blast Furnace/Superheat routes are
  separate assumptions; their equipment, fuel and costs are not silently adopted.
- [Sawmill](https://oldschool.runescape.wiki/w/Sawmill): baseline plank fees,
  member access and yield without vouchers. Bank/route timings remain unverified.
- [Rune arrow](https://oldschool.runescape.wiki/w/Rune_arrow): member level75,
  batch15 yield. The legacy model includes shaft/feather preparation; the final
  arrow-making animation does not establish a rate for that whole pipeline.
- [Cooking](https://oldschool.runescape.wiki/w/Cooking): burn probability depends
  on account level and route/equipment. It remains unknown in legacy recipes.
- [Herblore](https://oldschool.runescape.wiki/w/Herblore) and
  [Runecraft](https://oldschool.runescape.wiki/w/Runecraft): general requirements,
  enhancements and level-dependent yields expose incomplete legacy assumptions.
  Individual recipe yields/requirements remain unverified.
- Other crafting/magic/fletching/nail recipes retain source/yield/requirements
  gaps. For example, orb models omit route equipment/elemental rune costs; tanning
  fees and rune multipliers need route review. Their estimates are quarantined
  behind explicit unknown evidence and never become verified hourly rates.

A source URL/review date records which source was consulted. Separate yield/rate
flags state which claims were verified; a general source read is not individual
recipe approval. No unsupported timings or additional recipes were introduced.

## Verification and release boundary

Focused cases cover batch tax/fees, fractional cost ROI, default unknown success,
iron losses, input/output limits, capital/volume caps, account eligibility,
membership filters, pure CSV output and public account isolation. All917 offline
tests across66 files passed with four explicit provider skips. Authentication
and sixteen browser view scenarios passed. Actual Wiki acquisition produced50
CLI JSON/CSV and owner HTTP models with equal economics; none had a verified
hourly rate. Snapshots retain model qualification and null verified hourly rates.

Two bounded Sonnet reviews were checked locally. The confirmed default-success
ambiguity was fixed, capital/volume and CSV cases added, and account facts bounded.
Historical buying-limit behavior was deliberately corrected. Claims that CSV
writes literal None or that the review date is in the future were refuted against
actual output/current session date. Aliased ROI fields preserve existing clients;
configuration loads validate all currently supported fields.

Signed commit, integration with scan manifests, CI, deployment and Mac/private
readback remain pending. Older images reject the new account table: retain the
previous configuration backup for rollback; do not remove financial state or
claim source evidence makes a model executable.
