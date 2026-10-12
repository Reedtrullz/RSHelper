# Conditional inventory scenarios

The private Scenarios tab freezes current paper lots, usable quotes and separately
declared available/reserved cash. Zero shock matches the selected lot exit legs;
all/item/group shocks are additive basis points. Shocked and haircut prices round
down per unit before the shared GE tax calculation. Group membership is manual.
Missing quotes keep total valuation, concentration shares and percentage changes
unknown; known subtotals remain explicitly partial. Unknown cash blocks equity.

The pure evaluator changes no trading state or defaults. An observed-manual input
is explicit inventory, never inventory inferred from observed offer cash flow.
The dashboard submits private POST bodies and fences both view/auth generations
and overlapping calculations. Its report includes exact frozen input, input hash,
market revision, price legs and assumptions. Copy the report's `input` object to a
private JSON file, then run `rshelper scenario --input FILE --json` to reproduce it.
Inputs are bounded to 1000 lots and 64 KiB at CLI/HTTP boundaries. Monetary values
are bounded integers; scenarios are conditional arithmetic with no probabilities,
execution, liquidity guarantees or forecast claim.

Validation: 1104 Python tests/81 files/four named offline provider skips, zero
failures/errors; 42 browser view contracts plus owner authentication, seven fresh
Wiki checks and six production Python 3.11 checks. Native synthetic browser trial
confirmed mixed exit legs, haircut/shock calculations, unknown quote coverage,
private exported report reproduction by CLI and reachable controls at 320px.
The trial exposed unknown concentration printed as zero and an out-of-order reply
race; both have regression checks and were corrected. One bank test originally
patched profile config without isolating the explicit default positions path;
the fixture now isolates both paths. It made no owner-state writes. An initial
read-only Docker test lacked a writable HOME; the corrected tmpfs-HOME run passed.

Scoped Anti Sonnet review run `20261012T175651Z-617b4f73` submitted all 11 changed
paths but failed with gateway HTTP 504 at the 120-second deadline. Retry was zero
and fallback disabled; no review verdict or whole-diff approval is claimed. Native
review and functional checks passed. Owner usefulness is unverified; richer models
require demonstrated utility before expansion.
