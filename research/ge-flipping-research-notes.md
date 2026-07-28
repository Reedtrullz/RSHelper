# OSRS Grand Exchange Flipping — Research Notes for RSHelper

Source base: ge-tracker.com `/guides` (475 article pages parsed) plus 9 external sources. Notes extracted only from on-page text; pure video embeds with no text and pure PvM/skilling money-makers were skipped (see **Skipped** appendix). Two verified mechanic facts used throughout:

- **GE tax (current):** 2% on executed sell offers since the 29 May 2025 "Yama" update (was 1% before), **capped at 5m gp per offer**, applied per-item and **rounded down**, **exempt for items sold under 50 gp** (2% of <50 is <1 gp). Source: OSRS Wiki — Grand Exchange.
- **High Alchemy:** converts an item to coins = **60% of its store value** (not its GE price); costs **1 nature rune + 5 fire runes** (fire staff / tome of fire eliminates fire runes); **5-tick / 3 s per cast → ~1,200 casts/hr → ~78k Magic xp/hr** (65 xp/cast); level 55. Nature rune ≈ 147 gp (live). Profit/cast = `Alch Value − Buy Price − Nature Rune Cost`.

---

### Benefits Complete OSRS Flipping Guide - Old School Runescape

**URL:** https://www.ge-tracker.com/guides/view/benefits-complete-osrs-flipping-guide-old-school-runescape

**Category:** Flipping Strategy

**Key claim/strategy:** A full long-form manual (37k chars) covering GE matching mechanics, volume-based item classification, merchant archetypes, game-update valuation, and chart reading — the single most substantive guide in the set.

**Supporting detail:**
- GE matching: offers match best opposite price; **same-price ties go to the oldest offer (FIFO)**; a newly placed sell offer matches the highest buy offer, so a seller undercutting collects the full spread ("third scenario": a 600m instant-sell collects 650m).
- Margin = highest sell offer − lowest buy offer; **don't margin-check items with wide spreads** (a 15m gap is a one-off, not flippable). Volume tiers: **High** = runes/logs/food/potions/ore/bars (coal, gold bar, lobster, astral rune) — safe to margin-check, thin margins; **Average** = gray area, stop margin-checking, use graphs (abyssal whip, ranger boots, dharok's platebody); **Low** = avoid (hunter's potion, slayer's respite, dragon bitter), shown as "?" on GE Tracker — exceptions are rare/new items (twisted bow, 3rd age axe/pickaxe, elysian spirit shield, prayer scrolls) which are low volume but profitable.
- Merchant archetypes: Beginners mimic and quit on first loss; Average (1m–500m profit) = "the herd," flip common items (barrows, PvM drops), emotional, drive skyrockets/crashes; **Masterminds (500m–2bil+)** read every dev blog/Q&A, keep notes, hold months, diversify, comfortable with risk.
- **No item sinks** → steady supply inflates → long-term decline (e.g., Armadyl godsword). New items most volatile/profitable; when a new BiS releases the old one dumps (dragonfire shield → elysian). DWH went 70m→40m on release then rebounded (best weapon for Corp); dragon claws 300–500m→100–200m (nerfed, no ancient curses).
- **Timing:** invest when reddit + JMods both back an item update (before the dev blog triggers mass buying); **never invest days before release** ("99.99% you lose" — players dump on release day). Charts: log default; linear for hype/panic; **historic high with no supporting update = bubble, avoid**; long-term moving average for trend; candlesticks (beta) — hollow body = down, solid = up. Never invest whole bank; do other activities while offers fill.

**Relevance to RSHelper:** This is essentially a design spec — implement GE matching-aware margin logic, a volume-tier classifier with "?"-flag suppression, ROI vs volume tradeoff scoring, update-event tagging on charts, bubble detection (historic-high + no event), and capital-at-risk limits.

---

### [OSRS] HOW TO PICK PROFITABLE ITEMS AND FLIP THEM CORRECTLY - An Advanced Flipping Guide [2016]

**URL:** https://www.ge-tracker.com/guides/view/osrs-how-to-pick-profitable-items-and-flip-them-correctly-an-advanced-flipping-guide-2016

**Category:** Flipping Strategy

**Key claim/strategy:** Use chart data (rsbuddy exchange) to read the market, decide which items flip quickly, and price rare items.

**Supporting detail:**
- Core skills taught: read OSBuddy exchange charts, determine quick-flip items, figure selling price for rare items.
- Author points to two reference resources: rsbuddy exchange and the OSRS Wiki buying-limits page.
- Targets both expensive and cheap items; recommends a beginner guide first.

**Relevance to RSHelper:** Confirms chart-driven item selection and a hard dependency on a **buying-limits dataset**; ingest the Wiki buying-limits table as a first-class constraint, not an afterthought.

---

### [OSRS] How to Flip Items Overnight and Take Advantage of Bot Dumps - An Advanced Flipping Guide #2

**URL:** https://www.ge-tracker.com/guides/view/osrs-how-to-flip-items-overnight-and-take-advantage-of-bot-dumps-an-advanced-flipping-guide-2

**Category:** Investment Timing

**Key claim/strategy:** Flip items overnight using 24-hour price history; any bank size works, but you need a GE tracker exposing day-long history.

**Supporting detail:**
- Requires a tracking tool that exposes an item's **24-hour history**.
- Starting cash is flexible; strategy is about leaving offers up while offline.
- Topic explicitly pairs overnight flipping with **bot dumps** (the series frames dumps as the overnight edge).

**Relevance to RSHelper:** Add an "overnight mode": offers whose entry/exit span an offline window, scored using 24h history and a **bot-dump detector** (sudden volume + price drop) as an entry signal.

---

### [OSRS] How to Flip High Volume Items For Easy and Low Risk Profit! - An Advanced Flipping Guide #5

**URL:** https://www.ge-tracker.com/guides/view/osrs-how-to-flip-high-volume-items-for-easy-and-low-risk-profit-an-advanced-flipping-guide-5

**Category:** Flipping Strategy

**Key claim/strategy:** High-volume items (500k+ traded/day) are low-risk, easy-profit flips.

**Supporting detail:**
- **Explicit threshold: "high volume" = 500,000 or more traded per day.**
- High-volume items give "a very small chance of losing money" when done correctly.
- Designed for easy, low-risk profit (not max margin).

**Relevance to RSHelper:** Bake the **500k/day** number into the volume classifier as the high-liquidity cutoff for the low-risk strategy, distinct from the Benefits guide's qualitative tiers.

---

### [OSRS] Make 1000k Overnight While Sleeping - Oldschool Runescape Money Making Method!

**URL:** https://www.ge-tracker.com/guides/view/osrs-make-1000k-overnight-while-sleeping-oldschool-runescape-money-making-method

**Category:** Set Arbitrage

**Key claim/strategy:** Overnight profit by combining treasure-trail **page sets** — buy pages 1–4, combine into a set, leave offers overnight.

**Supporting detail:**
- Buy page 1, 2, 3, and 4; assemble into a page set; offers usually complete overnight.
- Recommended capital: **at least 10m, 30m recommended.**
- Tagged as an overnight / "while sleeping" method.

**Relevance to RSHelper:** Model page-set combining (sum of parts vs set price) as a **processing-arbitrage** recipe runnable overnight; the 10m/30m thresholds map to a capital-tier gate.

---

### [OSRS] INSANE MARGINS FLIPPING 3RD AGE ITEMS - High Risk/High Reward Flipping!

**URL:** https://www.ge-tracker.com/guides/view/osrs-insane-margins-flipping-3rd-age-items-high-risk-high-reward-flipping

**Category:** Investment Timing

**Key claim/strategy:** Buy 3rd-age items that crashed when a new raid launched (players liquidated to fund raiding), expecting eventual price recovery.

**Supporting detail:**
- When raids released, nearly all 3rd-age items crashed as players sold to fund raids.
- Author invests in the **3rd-age mage hat** and actively flips other 3rd-age armour pieces.
- Rationale: rarity + belief in long-term price recovery.

**Relevance to RSHelper:** Capture the event-driven "old-rare crashes on new-content release → reversion" pattern: a detector flagging rare/low-supply items whose price drops coincide with a major update, scored for mean-reversion entry.

---

### [OSRS] Make 700k Overnight In F2P - Oldschool Runescape Money Making Method

**URL:** https://www.ge-tracker.com/guides/view/osrs-make-700k-overnight-in-f2p-oldschool-runescape-money-making-method

**Category:** Set Arbitrage

**Key claim/strategy:** F2P overnight profit by combining armour sets (green d'hide and Saradomin rune armour).

**Supporting detail:**
- Method = **armour set combinations** in F2P.
- Specific sets used: green d'hide and Saradomin rune armour.
- GE Tracker has a **F2P setting** to enumerate all F2P item combinations.

**Relevance to RSHelper:** Treat the GE Tracker "F2P mode / set-combination view" as a parity feature; RSHelper's set-arb finder needs an F2P filter and overnight placement.

---

### [OSRS] INSANE MARGINS FLIPPING NEW RAID REWARD DROPS - Day 2 - High Risk/High Reward Flipping!

**URL:** https://www.ge-tracker.com/guides/view/osrs-insane-margins-flipping-new-raid-reward-drops-day-2-high-risk-high-reward-flipping

**Category:** Investment Timing

**Key claim/strategy:** Day-2 raid-reward flipping: prices still settling, very risky but very profitable; started with 50m.

**Supporting detail:**
- Day-2 raid rewards on the GE: **dragon sword, dragon harpoon, dragon thrownaxe, ancestral hat, dragon hunter crossbow, twisted buckler** (targeting dinh's bulwark next).
- Started with **50m**; "prices are still settling."
- Brand-new items = buyers/sellers placing offers "all over the place" (high spread volatility).

**Relevance to RSHelper:** Add a "fresh-content" item list sourced from game updates; in the first 48h, widen margin bands and flag as high-risk/high-reward with explicit volatility warnings.

---

### [OSRS] How to Get the Largest Margins By Flipping Rare Items - An Advanced Flipping Guide #3

**URL:** https://www.ge-tracker.com/guides/view/osrs-how-to-get-the-largest-margins-by-flipping-rare-items-an-advanced-flipping-guide-3

**Category:** Flipping Strategy

**Key claim/strategy:** A repeatable **process** for flipping rare items — high margin, but easy to lose a lot if mishandled.

**Supporting detail:**
- Frames rare-item flipping as a defined process rather than ad-hoc.
- Explicit warning: "possible to lose a lot of money if done incorrectly."
- Cross-links to a beginner guide and a GE tracker tool.

**Relevance to RSHelper:** For low-volume rare items, surface a mandatory risk-warning tier and expose the rare-item "process" as a guided flow rather than a one-click flip.

---

### [OSRS] How I Made 2.3m in 1 Hour of Flipping Dagannoth King Drops only! [Episode #15]

**URL:** https://www.ge-tracker.com/guides/view/osrs-how-i-made-2-3m-in-1-hour-of-flipping-dagannoth-king-drops-only-episode-15

**Category:** Category Specialization

**Key claim/strategy:** Flip only items within one boss's drop table (Dagannoth Kings), 30m start, 1 hour.

**Supporting detail:**
- Rules: **30m starting cash, 1-hour limit, DK drops only.**
- Items include **archer ring, berserker ring, seers ring, warrior ring** (rare drop table included).
- Most profitable episode done, "mostly due to luck."

**Relevance to RSHelper:** Support **drop-table-scoped item universes** as a flip category (per-boss filtering); note profit variance is high — score expected value, not just best-case.

---

### Building an Insane 100 Account Flipping Farm! [Accounts 21 to 25] Flipping on 100 Accounts [OSRS]

**URL:** https://www.ge-tracker.com/guides/view/building-an-insane-100-account-flipping-farm-accounts-21-to-25-flipping-on-100-accounts-osrs

**Category:** Multi-Account

**Key claim/strategy:** Scaling flipping across 100 accounts, rotating items per slot and learning which items can't keep up with a standing buy offer.

**Supporting detail:**
- Dropped **rune essence** because "it takes way too long to sell and I would never be able to keep up with my buy offer" — an exit-liquidity failure.
- Added **empty jug** and **fishing bait** this episode; wants **at least 3m per account** → paused 1 week to rebuild capital.
- When out of capital, refines the existing item roster rather than adding accounts.

**Relevance to RSHelper:** Multi-account orchestration needs (a) a **sell-through/sell-rate check** so a buy order isn't placed where sell-side can't drain, and (b) per-account capital targets before scaling slot count.

---

### 1 Hour Merching With 30M ON 5 ACCOUNTS!! INSANE RESULTS

**URL:** https://www.ge-tracker.com/guides/view/1-hour-merching-with-30m-on-5-accounts-insane-results

**Category:** Multi-Account

**Key claim/strategy:** 150m across 5 accounts in one GE session; merching pitched as the most efficient money-maker.

**Supporting detail:**
- **30m × 5 accounts = 150m** deployed simultaneously.
- Notes ~10 min spent finding items at the start and the final 5 min discarded — overhead that wouldn't recur once "in the groove."
- Calls merching "the best way to make money… the most efficient."

**Relevance to RSHelper:** Multi-account throughput realistically needs an item-discovery warmup; model idle/overhead time so projected GP/hr isn't overstated for short sessions.

---

### Day Of Release Flipping Is The Only Thing That Keeps Me Alive [Dragon Slayer 2]

**URL:** https://www.ge-tracker.com/guides/view/day-of-release-flipping-is-the-only-thing-that-keeps-me-alive-dragon-slayer-2

**Category:** Game update effects

**Key claim/strategy:** Raw demonstration of day-of-release flipping: extremely high variance — "when you hit big its lit, when you don't, its not."

**Supporting detail:**
- Author lost money (specifically on bones) on DS2 release day despite the hype.
- Frames release-day flipping as psychologically gruelling.
- Honest framing: day-of-release can produce big wins or fast losses.

**Relevance to RSHelper:** For day-of-release items, present **expected profit with a wide confidence band** and a loss-tolerance prompt; don't show only the upside to an automated tool's user.

---

### WHAT ARE THE BEST ITEMS TO FLIP ON OSRS? - How To Find The Right Item - MAKE BANK!

**URL:** https://www.ge-tracker.com/guides/view/what-are-the-best-items-to-flip-on-osrs-how-to-find-the-right-item-make-bank

**Category:** Flipping Strategy

**Key claim/strategy:** (Thin text — mostly a viewer-engagement intro.) Premise is selecting the right item to flip; no specific item list in the on-page text.

**Supporting detail:**
- Asks viewers for item suggestions in comments; directs to a livestream.
- No concrete items or thresholds in the page text itself.

**Relevance to RSHelper:** Low-value as a source; signals that "what do I flip?" is the most-asked beginner question — the flip finder should answer it by default with a ranked, filterable list.

---

### OSRS How I Make 15-20M Per Day Flipping Items!

**URL:** https://www.ge-tracker.com/guides/view/osrs-how-i-make-15-20m-per-day-flipping-items

**Category:** Category Specialization

**Key claim/strategy:** The author's working high-liquidity item shortlist for ~15–20m/day flipping.

**Supporting detail:**
- Item list (verbatim): **blowpipe, serp helm, toxic staff, fury, zerker ring, archer ring, bgs, dfs, amulet of torture, anguish neck**, "etc."
- These are high-end PvP / BiS gear — mid-high value, decent volume.

**Relevance to RSHelper:** A ready-made "high-end PvP gear" watchlist category; useful as a seed list for the flip finder and a benchmark for which items sustain ~15–20m/day throughput.

---

### Is Flipping Expensive Items With 500m Worth it?

**URL:** https://www.ge-tracker.com/guides/view/is-flipping-expensive-items-with-500m-worth-it

**Category:** Capital Efficiency

**Key claim/strategy:** Tests whether short-horizon flipping of high-priced items with a 500m bank is viable — results-focused.

**Supporting detail:**
- Capital: **500m**; timeframe: short (single-session).
- Frames high-value flipping as a capital-efficiency question ("worth it?").
- No specific items/numbers in text — results are in the video.

**Relevance to RSHelper:** Build a capital-efficiency metric (GP/hr per gp deployed) so high-value flips are judged against the same denominator as volume flips, answering "worth it?" quantitatively.

---

### OSRS - Flipping Item Sets For One Hour With 7M Start! EASY MONEY

**URL:** https://www.ge-tracker.com/guides/view/osrs-flipping-item-sets-for-one-hour-with-7m-start-easy-money-oldschool-runescape

**Category:** Set Arbitrage

**Key claim/strategy:** Flip common item sets for one hour with a **7m** start — set arbitrage pitched as easy money.

**Supporting detail:**
- Uses item sets the author flips frequently.
- Capital tier: **7m start**; 1-hour test.
- "Easy money," incrementally scalable.

**Relevance to RSHelper:** Set arbitrage works at small banks (7m); include a low-capital set-arb finder tier so beginners get easy wins.

---

### OSRS- Flipping Most Traded Items For Easy Money! 20M Start

**URL:** https://www.ge-tracker.com/guides/view/osrs-flipping-most-traded-items-for-easy-money-20m-start

**Category:** Flipping Strategy

**Key claim/strategy:** Flip the most-traded items for easy (if not maximal) profit; 20m start.

**Supporting detail:**
- Method: stick to most-traded items.
- Author's usual items "were not flipping" that day — profit "good just not great."
- Capital: **20m.**

**Relevance to RSHelper:** Even liquid items have off-days (no margin); present a list ranked by **current** margin, not a static "always-good" item list.

---

### Easiest Money I'll Ever Make - OSRS Flipping 1-100m #3 (Ge-Tracker)

**URL:** https://www.ge-tracker.com/guides/view/easiest-money-i-ll-ever-make-osrs-flipping-1-100m-3-ge-tracker

**Category:** Flipping Strategy

**Key claim/strategy:** (Thin text — series episode.) Part of a "1–100m" flipping series; "another load of profit."

**Supporting detail:**
- Series premise: grow 1m → 100m by flipping using GE Tracker.
- No items/numbers in the page text; engagement/outro only.

**Relevance to RSHelper:** Low text value; useful only as the existence of a long-running 1m→100m case study — confirms compounding small flips is a viable user journey to support with a "growth" dashboard.

---

### [OSRS Flipping/Merching] Cleaning herbs for a profit

**URL:** https://www.ge-tracker.com/guides/view/osrs-flipping-merching-cleaning-herbs-for-a-profit

**Category:** Processing Arbitrage

**Key claim/strategy:** Clean grimy herbs to train Herblore **and** make a profit simultaneously (buy grimy → clean → sell clean).

**Supporting detail:**
- Buy→clean→sell pipeline; cleaning adds value and trains Herblore.
- Presented by staff member BenefitsOfaG.

**Relevance to RSHelper:** Implement herb cleaning as a processing-arbitrage recipe: margin = clean herb price − grimy herb price, gated by the player's Herblore level per herb.

---

### [OSRS Flipping/Merching] Decanting potions for money

**URL:** https://www.ge-tracker.com/guides/view/osrs-flipping-merching-decanting-potions-for-money

**Category:** Processing Arbitrage

**Key claim/strategy:** Use GE Tracker's decanting tool to find the most profitable potions; decant while other flips are pending (parallel passive income).

**Supporting detail:**
- Decanting = "a great way to make money while you have other flips waiting to buy and sell" — explicitly a **parallel** method.
- Tool-driven: find the most profitable potions via the decanting tool.

**Relevance to RSHelper:** Treat decanting as a background task that runs alongside flip offers, paging in capital between flip cycles — a duplexing strategy for paper-trading/backtest modes.

---

### [OSRS Flipping] Managing money and risks

**URL:** https://www.ge-tracker.com/guides/view/osrs-flipping-managing-money-and-risks

**Category:** Risk Management

**Key claim/strategy:** Allocate a fixed share of earnings to flipping capital; keep flipping money ring-fenced from spending to reduce risk and stress.

**Supporting detail:**
- Rule: designate a **percentage of daily earnings** to flipping and keep it as flipping money.
- Concrete example: **invest 50%; once at 100m spendable gp, hold at least 100m in the GE for flipping.**
- Dividing money eases "stress on any particular items" → reduces risk and increases earning potential.

**Relevance to RSHelper:** Add a bank-allocation guardrail: configurable reinvestment %, a spendable-vs-flipping split, and risk caps so a single item can't draw down the whole flipping pool.

---

### I Kept This Method A Secret For Over A Year (10M+ Per Day In 20 Minutes)

**URL:** https://www.ge-tracker.com/guides/view/i-kept-this-method-a-secret-for-over-a-year-10m-per-day-in-20-minutes

**Category:** Flipping Strategy

**Key claim/strategy:** (Teaser text — the actual method stays secret on the page.) Claims 10m+/day in ~20 minutes of active time.

**Supporting detail:**
- Headline economics: **10m+ per day in ~20 minutes** of work.
- Author no longer uses it personally (low source credibility for replication).
- No item names, categories, or mechanics in the text.

**Relevance to RSHelper:** Aspirational target (high GP/min for low active time) — a north-star benchmark for overnight/passive-strategy GP/hr, but no actionable tactics to implement.

---

### What We Can Learn From The Rise And Falls Of Raid Items (Merching Tips)

**URL:** https://www.ge-tracker.com/guides/view/what-we-can-learn-from-the-rise-and-falls-of-raid-items-merching-tips

**Category:** Game update effects

**Key claim/strategy:** Look back **9 months** at raid-item charts to find post-release price patterns and trends useful for future updates.

**Supporting detail:**
- Retrospective chart analysis of raid items ~9 months after release.
- Goal: extract investable trends/lessons for the next content cycle.
- Methodology: chart pattern + timeframe analysis, not live flipping.

**Relevance to RSHelper:** Backtest hook — run a **post-release reversion/decay study** on every major-update item cohort to learn the typical price curve and feed forward into pre-release investment scoring.

---

### Flipping Items Sets Is the Easiest Money In the Game! [OSRS] - A one Hour Flipping Challenge

**URL:** https://www.ge-tracker.com/guides/view/flipping-items-sets-is-the-easiest-money-in-the-game-osrs-a-one-hour-flipping-challenge

**Category:** Set Arbitrage

**Key claim/strategy:** Item set creation (esp. barrows equipment sets) plus two adjacent techniques — barrows armour repair and potion decanting — grouped as an "item sets and crafting" category.

**Supporting detail:**
- Primary sets: **barrows equipment sets**; a few other profitable sets also used.
- Bundles in **repairing barrows armour** and **decanting potions** as related techniques.
- Framed as "the easiest money in the game"; one-hour test.

**Relevance to RSHelper:** Group set-creation, barrows-repair, and decanting under one "construct processing" engine that prices sum-of-parts vs assembled product.

---

### Easily Make 2.3M/HR By Flipping These Everyday Items! - Flipping and Money Making For 1 Hour! [OSRS]

**URL:** https://www.ge-tracker.com/guides/view/easily-make-2-3m-hr-by-flipping-these-everyday-items-flipping-and-money-making-for-1-hour-osrs

**Category:** Category Specialization

**Key claim/strategy:** Unrestricted 1-hour flip with 115m, mixing high-volume rares with high-volume resources — the everyday-item sweet spot.

**Supporting detail:**
- Capital: **115m.**
- Mix: high-volume rares **(bandos godsword, fury, berserker ring, archer ring)** + resources **(battlestaff, magic log, dragon bone).**
- "These items tend to work better for me" for 1-hour challenges.

**Relevance to RSHelper:** Seed two starter watchlists — "high-volume rares" and "high-volume resources" — and a hybrid 1-hour strategy that blends both for balanced margin + throughput.

---

### [OSRS] The Ultimate Tool for Flipping In Runescape - Track Profits, G.E Limits, Suggested Items

**URL:** https://www.ge-tracker.com/guides/view/osrs-the-ultimate-tool-for-flipping-in-runescape-track-profits-g-e-limits-suggested-items

**Category:** Tool Usage

**Key claim/strategy:** Feature tour of GE Tracker comparing free vs premium tiers — effectively a feature checklist for a flipping tool.

**Supporting detail:**
- Free: 3 favourite items, price & buy/sell-quantity graphs, basic profit tracker, **5 suggested profitable items every 10 minutes (no refreshes)**, public merching logs.
- Premium: unlimited favourites, full/active-transaction profit tracker, **view most profitable items, GE-limit profit, ~50 suggested items (infinite refreshes), recently-added items, OSBuddy import, item sets & crafting, Karamja store, decant potions, high-alch calculator, herblore-for-profit, custom alerts (desktop/email/SMS).**

**Relevance to RSHelper:** A near-complete parity list: suggested-items feed, GE-limit-aware profit, item-sets/crafting, decant, alch calc, herblore-for-profit, alerts, and "recently added items" (fresh-content detection).

---

### [OSRS] INSANE PROFITS FLIPPING BARROW DROPS ONLY! 1M+ AN HOUR [ Episode #10 ] A Flipping Challenge

**URL:** https://www.ge-tracker.com/guides/view/osrs-insane-profits-flipping-barrow-drops-only-1m-an-hour-episode-10-a-flipping-challenge

**Category:** Category Specialization

**Key claim/strategy:** 1-hour flip restricted to Barrows drops (30m start); the barrows economy is liquid enough for 1m+/hr.

**Supporting detail:**
- Rules: **30m, 1 hour, Barrows drops only.**
- Full item universe listed: **Dharok's, Ahrim's, Guthan's, Karil's, Torag's, Verac's full sets** + bolt racks, loop/tooth key halves, dragon med helm.
- "Far surpasses any other episode."

**Relevance to RSHelper:** Barrows is a self-contained, well-supplied category; ship a "Barrows drops" preset universe with all six sets + misc drops pre-mapped.

---

### FLIPPING EVERY 3RD AGE ARMOUR! AFK Profit?! (CHALLENGE!) - Oldschool 2007 Runescape

**URL:** https://www.ge-tracker.com/guides/view/flipping-every-3rd-age-armour-afk-profit-challenge-oldschool-2007-runescape

**Category:** Category Specialization

**Key claim/strategy:** Flip every piece of 3rd-age armour in a single pass — the profit "makes this method very good," framed as AFK-friendly.

**Supporting detail:**
- Universe: **every 3rd-age armour piece** in one challenge.
- Pitched as **AFK profit** (offers sit, not high-touch).
- Author suggests future sweeps: all raids items, all 3rd-age weapons, all clue rewards.

**Relevance to RSHelper:** A full rare-set sweep is a benchmark mode — flip an entire category simultaneously and measure aggregate AFK profit; useful for a "category sweep" feature.

---

### Flipping Herbs/Herb Seeds With 100M for 1 Hour Test [Episode 4]

**URL:** https://www.ge-tracker.com/guides/view/flipping-herbs-herb-seeds-with-100m-for-1-hour-test-episode-4

**Category:** Category Specialization

**Key claim/strategy:** Flip clean + grimy herbs **and** herb seeds with 100m; explicit diversification framework across three dimensions.

**Supporting detail:**
- Items: **clean herbs, grimy herbs, herb seeds** — capital 100m.
- Series framework: diversify by (1) boss drops, (2) places/areas, (3) item types (swords, armour, farming supplies…).
- Goal: track stats per category to learn "where to look for good merchs."

**Relevance to RSHelper:** The drops/places/types axis is a clean taxonomy for flip categories; collect per-category stats so RSHelper can rank which categories historically produce best margins.

---

### Flipping THE BIGGEST MARGINS in Old School Runescape With 100M [EP 3]

**URL:** https://www.ge-tracker.com/guides/view/flipping-the-biggest-margins-in-old-school-runescape-with-100m-ep-3

**Category:** Tool Usage

**Key claim/strategy:** Flip the items GE Tracker reports as having the biggest margins, 100m start.

**Supporting detail:**
- Uses **GE Tracker's biggest-margin list** as the source-of-truth for item selection.
- Same diversification framework (drops/places/types).
- Capital: 100m.

**Relevance to RSHelper:** A "biggest margins" filter is core — but pair it with volume/risk so RSHelper doesn't chase thin-liquidity high-margin traps.

---

### [OSRS] FLIPPING THE HIGHEST MARGIN ITEMS IN F2P - EP #5 - Flipping to 100m using F2p Items Only!

**URL:** https://www.ge-tracker.com/guides/view/osrs-flipping-the-highest-margin-items-in-f2p-ep-5-flipping-to-100m-using-f2p-items-only

**Category:** Category Specialization

**Key claim/strategy:** F2P-only high-margin flip series; the **ring of nature** was the best F2P item, alongside several set items.

**Supporting detail:**
- Best F2P item: **ring of nature** (continuing to be #1 that episode).
- Other F2P high-margin items: **gilded armour sets, hill giant clubs, team capes** (+ trimmed armour).
- Capital arc: 50m → 100m.

**Relevance to RSHelper:** Provide a curated F2P high-margin shortlist (ring of nature, gilded sets, hill giant clubs, team capes) as a starter F2P watchlist, separate from members items.

---

### [OSRS] THE BIGGEST MARGIN ON A F2P ITEM I HAVE EVER GOTTEN! - High Risk/High Reward F2P Flipping

**URL:** https://www.ge-tracker.com/guides/view/osrs-the-biggest-margin-on-a-f2p-item-i-have-ever-gotten-high-risk-high-reward-f2p-flipping

**Category:** Category Specialization

**Key claim/strategy:** F2P high-risk flip of higher-level F2P items — one flip yielded nearly enough for a bond.

**Supporting detail:**
- Items tried: **monk robe (g), gilded armour, team capes.**
- Single best flip nearly equalled a bond's price ("I have never gotten a flip like that before").
- Framed as high-risk/high-reward F2P.

**Relevance to RSHelper:** F2P trimmed/cosmetic items can spike enormous single-flip margins; flag them as high-variance with wide confidence intervals, not steady-flip candidates.

---

### [OSRS] Ultimate 1GP to 1M Flipping Guide - How to Get Your First Mil By Flipping!

**URL:** https://www.ge-tracker.com/guides/view/osrs-ultimate-1gp-to-1m-flipping-guide-how-to-get-your-first-mil-by-flipping

**Category:** Capital Efficiency

**Key claim/strategy:** From 1 gp to 1m by flipping cheap **rare clue-scroll items**, which carry outsized margins for their price.

**Supporting detail:**
- Strategy: flip **cheap clue-scroll items** — "massive margins for their price."
- Focus on rarer items to compound the first million.
- Requires only basic GE understanding.

**Relevance to RSHelper:** Build a sub-1m "cheap clue items" category with high ROI% — ideal for the paper-trading/new-user on-ramp where capital is tiny.

---

### Flipping From a 10k Cash Start is Amazing! (800% RETURN) A One Hour Flipping Challenge [OSRS]

**URL:** https://www.ge-tracker.com/guides/view/flipping-from-a-10k-cash-start-is-amazing-800-return-a-one-hour-flipping-challenge-osrs

**Category:** Capital Efficiency

**Key claim/strategy:** A tiny 10k bank can produce ~100–200% returns per item because few competitors bother with cheap items.

**Supporting detail:**
- Capital: **10k.**
- Expected per-item returns: **100%–200%** (absolute GP low, percentage high).
- Edge thesis: few people bother with cheap items → "a lot of room for profit."

**Relevance to RSHelper:** ROI-% ranking shines at low capital; include a low-competition edge factor so the finder surfaces cheap, under-traded items where margins are loose.

---

### [OSRS] Ultimate 1GP - 2147M Flipping Guide - How to Get A Max Cash Stack From Flipping!

**URL:** https://www.ge-tracker.com/guides/view/osrs-ultimate-1gp-2147m-flipping-guide-how-to-get-a-max-cash-stack-from-flipping

**Category:** Capital Efficiency

**Key claim/strategy:** (Overview text.) Scale flipping 1gp → max-cash (2147m) by category, not by specific items.

**Supporting detail:**
- Teaches **which categories** to flip per bank-size tier rather than named items.
- Points viewers to a decanting guide and advanced flipping guides for depth.
- Target: max cash stack (2,147m).

**Relevance to RSHelper:** Support a tiered capital-to-category ladder so the recommended item universe adapts as the bank grows from cents to max-cash; cross-link decant/advanced recipes per tier.

---

### Flipping to Billions In Oldschool Runescape (50M to 1B) Episode #5 [OSRS]

**URL:** https://www.ge-tracker.com/guides/view/flipping-to-billions-in-oldschool-runescape-50m-to-1b-episode-5-osrs

**Category:** Capital Efficiency

**Key claim/strategy:** "50m→1bil" series: few flips per session but high quality; author notes high-volume flips are harder to track.

**Supporting detail:**
- Series scale: 50m → 1bil, slow and steady.
- Observation: **high-volume flips are "a lot harder to keep track of"** than slower, higher-margin flips.
- Considering moving to more high-volume flips for the series.

**Relevance to RSHelper:** At very large banks, fewer high-margin flips can out-earn many small ones; a tracker must scale monitoring without overwhelming — surface only the highest-signal offers when capital is large.

---

### [OSRS] Make 530k in 10 Minutes - Daily Oldschool Runescape Money Making Method!

**URL:** https://www.ge-tracker.com/guides/view/osrs-make-530k-in-10-minutes-daily-oldschool-runescape-money-making-method

**Category:** Buy Limit Mechanics

**Key claim/strategy:** Repeatable ~530k in ~10 minutes by flipping items on their **4-hour buy-limit cycle**; compounding daily hits ~1m/day in a few minutes.

**Supporting detail:**
- ~530k per 10-minute session; "flipped every 4 hours."
- Doing it daily → "over a mil every day with just a few minutes work."
- Beginner + advanced guides linked.

**Relevance to RSHelper:** A natural fit for buy-limit-aware scheduling: a daily, 4-hour-cadence flip routine that re-arms at limit reset and reports cumulative daily GP for minimal active time.

---

### [OSRS Flipping/Merching] A complete guide to flipping for beginners - part one

**URL:** https://www.ge-tracker.com/guides/view/osrs-flipping-merching-a-complete-guide-to-flipping-for-beginners-part-one

**Category:** Tool Usage

**Key claim/strategy:** An analytical, in-depth beginner series by BenefitsOfaG that tackles common beginner dilemmas.

**Supporting detail:**
- "Analytical and in-depth approach to merching."
- Targets players who have never flipped; focuses on common beginner dilemmas.
- Companion to the long "Benefits Complete" guide.

**Relevance to RSHelper:** Beginner onboarding should front-load common dilemmas (what to flip, how to find a margin, when to exit) — a guided first-flip flow, not a bare table.

---

### [OSRS Flipping] How to use our candlestick charts - part one

**URL:** https://www.ge-tracker.com/guides/view/osrs-flipping-how-to-use-our-candlestick-charts-part-one

**Category:** Chart Patterns

**Key claim/strategy:** Reading GE Tracker candlestick charts is intermediate/advanced; candlesticks show **short-term moving trends more visibly than line charts.**

**Supporting detail:**
- Candlesticks were in **BETA** but viable on many items.
- Value = short-term trend visibility exceeds line graphs.
- Warning: "beginners stay wary" — moves beyond the newbie stage.

**Relevance to RSHelper:** Candlestick rendering is a tier-2 chart feature; keep it optional and pair with line/log charts, surfacing short-term trend bars specifically for active flippers.

---

### [OSRS] How to Break Even High Alching - Oldschool Runescape High Alching Guide!

**URL:** https://www.ge-tracker.com/guides/view/osrs-how-to-break-even-high-alching-oldschool-runescape-high-alching-guide

**Category:** High Alchemy

**Key claim/strategy:** Find break-even/profitable high-alch items using GE Tracker's prices, margins, and alchemy values; "every gp saved is worth 2 gp earned."

**Supporting detail:**
- Uses GE Tracker for **prices, margins, and high-alch values.**
- Goal: find break-even items (a "money saving guide") and learn to find your own.
- 55 Magic implied (high alch).

**Relevance to RSHelper:** The alch module should rank by `Alch Value − Buy Price − Nature Rune Cost` and let users self-discover items — surface break-even as the zero-profit baseline.

---

### How to Make 1M+ GP Per Hour Using HIGH ALCH SPELL!! [Old School Runescape]

**URL:** https://www.ge-tracker.com/guides/view/how-to-make-1m-gp-per-hour-using-high-alch-spell-old-school-runescape

**Category:** High Alchemy

**Key claim/strategy:** A "quirky" alch method relying on **revenant bracelets** staying cheap; profit persists because competition self-eliminates.

**Supporting detail:**
- Item: **rev (revenant) bracelets** (when low in cost).
- Argument: low cost → margin "always there" because early competition burns out, else price rises via natural in-game demand.
- Requires 55 alch (Magic); more cash helps.

**Relevance to RSHelper:** Item-specific profitable-alch edge cases (rev bracelets) belong in an alch watchlist; model the self-correcting logic — if an alch margin exists, it closes via competition or the buy price rises, so margin is time-sensitive.

---

### 1 Hour of FLIPPING with 100m! G.E Flipping, MAKING BANK?! - Oldschool 2007 Runescape

**URL:** https://www.ge-tracker.com/guides/view/1-hour-of-flipping-with-100m-g-e-flipping-making-bank-oldschool-2007-runescape

**Category:** Capital Efficiency

**Key claim/strategy:** A self-described **novice** made bank flipping 100m for an hour — flipping has a low skill floor.

**Supporting detail:**
- Capital: **100m**, 1 hour; author had only watched a few videos.
- Tiers suggested by viewers: 10m, 1m, even 100k versions.
- "Seasoned flippers can probably make more."

**Relevance to RSHelper:** Confirms a low barrier-to-entry at 100m; offer capital-tier presets (100k / 1m / 10m / 100m) so novices get appropriate universes per bank.

---

### [OSRS] HOW TO SUCCEED AT FLIPPING IN RUNESCAPE!! - A Beginner Flipping Guide [2016]

**URL:** https://www.ge-tracker.com/guides/view/osrs-how-to-succeed-at-flipping-in-runescape-a-beginner-flipping-guide-2016

**Category:** Flipping Strategy

**Key claim/strategy:** Beginner curriculum: what flipping is, how it applies to RuneScape, how to find an item's margin, and what items to flip.

**Supporting detail:**
- Syllabus (verbatim): What is flipping? How this applies to RuneScape? **How to find an item's margin?** What items will be good to flip?
- Cross-links advanced flipping guide and a 0–100m flipping series.

**Relevance to RSHelper:** The beginner mental model is: find margin → pick item → execute. Expose "find this item's margin" as a first-class action (live margin check) before committing.

---

### [OSRS] Flipping Random Items Challenge? [Episode #4] Let the Random Number Generator Decide!

**URL:** https://www.ge-tracker.com/guides/view/osrs-flipping-random-items-challenge-episode-4-let-the-random-number-generator-decide

**Category:** Tool Usage

**Key claim/strategy:** A randomized self-training method: an RNG picks items, forcing the flipper to test arbitrary markets — a discovery/exploration technique.

**Supporting detail:**
- 1m start; 5 random flips/episode chosen by RNG; 2 lifelines (use a comment-suggested item, or re-roll and pick between the two).
- Rules: **item under 1m; never flip more than the buying limit; 2 skips per episode.**
- Comment-suggestion loop (prize for chosen item, e.g., red spider eggs).

**Relevance to RSHelper:** An exploration mode: randomly sample items within constraints (price < threshold, ≤ buy limit) to expand coverage and discover overlooked niches — also a backtest data-diversification tactic.

---

### Worthless To Wall Street Ep 1!! New Merching Series!! 5m To ???

**URL:** https://www.ge-tracker.com/guides/view/worthless-to-wall-street-ep-1-new-merching-series-5m-to

**Category:** Capital Efficiency

**Key claim/strategy:** Long-running merching series premise: a low-level account given **5m**, allowed to make money **only by merching** (jewelry-charging permitted) — measuring open-ended growth.

**Supporting detail:**
- Rules: **5m start, merching-only income, jewelry charging allowed, no endpoint.**
- Designed to teach merching from scratch on a low-level account.
- Series spans 17+ episodes (each video-narrated; little per-episode text).

**Relevance to RSHelper:** A 5m-start, merching-only sandbox is a perfect paper-trading default; RSHelper's "growth" mode should support an open-ended, rules-locked progression for teaching.

---

### [OSRS] Flipping the Top 100 Most Traded Items Only! [Episode #30] A one hour flipping challenge

**URL:** https://www.ge-tracker.com/guides/view/osrs-flipping-the-top-100-most-traded-items-only-episode-30-a-one-hour-flipping-challenge

**Category:** Volume Thresholds

**Key claim/strategy:** Flip only the **top 100 most-traded items** (from the official RuneScape exchange), using GE Tracker for buy limits and price trends.

**Supporting detail:**
- Item source: **top 100 most-traded** from the official exchange; GE Tracker for **buy limits & price trends.**
- Rules: 30m, 1 hour, top-100 items only.
- Repeat of an earlier challenge with different items.

**Relevance to RSHelper:** A "top-N most-traded" universe is a strong default filter; let users pick N and combine with current-margin ranking for a high-throughput workflow.

---

### Top 10 Grand Exchange Tips and Tricks! - Ep. 1 [OSRS]

**URL:** https://www.ge-tracker.com/guides/view/top-10-grand-exchange-tips-and-tricks-ep-1-osrs

**Category:** Flipping Strategy

**Key claim/strategy:** (Text describes the video's intent only.) Ten GE techniques with mixed money and skill requirements, mostly low-skill.

**Supporting detail:**
- Mix: most methods have **no skill requirements**; a few minor requirements; some need significant starting cash.
- Plans further tip videos including a QOL episode.
- No specific tips in the page text (all in the video).

**Relevance to RSHelper:** Low text value; a curated "tips" deck is a useful in-app help surface, but the substance must be authored, not scraped here.

---

### Flip Finders Tools, High Alch Calculator and Money Making - A Complete Guide to GE Tracker [OSRS]

**URL:** https://www.ge-tracker.com/guides/view/flip-finders-tools-high-alch-calculator-and-money-making-a-complete-guide-to-ge-tracker-osrs

**Category:** Tool Usage

**Key claim/strategy:** Comprehensive GE Tracker walk-through covering **every** tool (flipping tools + money-making calculators) and how the author uses each.

**Supporting detail:**
- Covers flip finder tools and money-making calculators.
- Aimed at "how to use the tool properly" questions.
- Sponsored but framed as a full product tour.

**Relevance to RSHelper:** Users expect a single guided tour across all tools — ship an integrated product tour, not isolated calculators.

---

### [OSRS] How to Search for Profitable Items to Flip with GE Tracker - A Guide to Using Search Filters!

**URL:** https://www.ge-tracker.com/guides/view/osrs-how-to-search-for-profitable-items-to-flip-with-ge-tracker-a-guide-to-using-search-filters

**Category:** Tool Usage

**Key claim/strategy:** Use GE Tracker **search filters** to surface unique items other users aren't watching; switch to **F2P-only mode** for F2P flipping.

**Supporting detail:**
- Search filters narrow to unique items others won't see — a competitive-edge thesis.
- Dedicated **F2P-only mode** toggle for free-to-play markets.
- Tutorial-style; encourages more GE Tracker tutorials.

**Relevance to RSHelper:** Powerful, composable filters are a core differentiator; include explicit F2P/members toggle and niche-filter presets so users find items outside the crowded default lists.

---

### Why Are Bonds Skyrocketing In Price? November Market Analysis for Oldschool Runescape [OSRS]

**URL:** https://www.ge-tracker.com/guides/view/why-are-bonds-skyrocketing-in-price-november-market-analysis-for-oldschool-runescape-osrs

**Category:** Market Mechanics

**Key claim/strategy:** A monthly market-analysis format: explain a macro move (bond prices) and item trends driven by that month's updates.

**Supporting detail:**
- Bond price analysis (November).
- Uses GE Tracker's **index page** for general item trends.
- Specific update-affected items: **ahrims staff, serpentine helm, bandos godsword.**

**Relevance to RSHelper:** A "market index / watchlist" view with per-item trend + update annotation is a premium surface; bonds are a macro proxy worth tracking alongside items.

---

### Invest Now Before Dragon Slayer 2 Comes Out! Market Analysis for Dragon Slayer 2 [OSRS]

**URL:** https://www.ge-tracker.com/guides/view/invest-now-before-dragon-slayer-2-comes-out-market-analysis-for-dragon-slayer-2-osrs

**Category:** Investment Timing

**Key claim/strategy:** Pre-release investment thesis: DS2 will make some items spike and some crash; pick which before release.

**Supporting detail:**
- Framing: updates "have the potential to make a lot of money" — pre-positioning.
- Items will spike or crash on release; author gives opinions (specifics in video).
- Companion to "Top 5 DS2 Investments."

**Relevance to RSHelper:** Pre-release strategy module: ingest the upcoming-update item list, score spike-vs-crash candidates, and surface pre-position recommendations before the dev-blog catalyst.

---

### Old School Mobile Is Coming! Here Is What You Need To Invest In!

**URL:** https://www.ge-tracker.com/guides/view/old-school-mobile-is-coming-here-is-what-you-need-to-invest-in

**Category:** Investment Timing

**Key claim/strategy:** Invest ahead of the **OSRS Mobile** launch — capitalize on beta hype even before full release.

**Supporting detail:**
- Thesis: invest now ("mobile may not be released for a while") to capture beta hype.
- Two waves: beta hype, then full-release hype.
- Author's overview of what he expects mobile to do to prices.

**Relevance to RSHelper:** Non-content events (mobile launch, beta waves, returning-player surges) are investable catalysts — track an "events calendar" beyond just game-content updates.

---

### [OSRS] HOW I LOST $500,000 USD ON MY BIGGEST FAILED FLIP - 7500 Subscriber Milestone

**URL:** https://www.ge-tracker.com/guides/view/osrs-how-i-lost-500-000-usd-on-my-biggest-failed-flip-7500-subscriber-milestone

**Category:** Trader Psychology

**Key claim/strategy:** A "biggest failed flip" reflection — the lost item was actually **Bitcoin** held since the old days (now ~$500k), not a GE flip; a holding-vs-selling object lesson.

**Supporting detail:**
- The "failed flip" = BTC sold/used too early (not a GE trade).
- Framed as a milestone reflection on regret and opportunity cost.
- No GE mechanics, items, or numbers.

**Relevance to RSHelper:** Low GE relevance, but supports **position discipline**: never encourage panic-selling a good thesis early; add a "thesis still intact?" re-evaluation prompt before exits.

---

### How to Casually Merch And Make 2M In A little Over 1 HOUR While Skilling/Slaying

**URL:** https://www.ge-tracker.com/guides/view/how-to-casually-merch-and-make-2m-in-a-little-over-1-hour-while-skilling-slaying

**Category:** Overnight Strategies

**Key claim/strategy:** Merch methods that don't need constant GE attention — good time/GP methods that can't be high-volume'd all at once, run while skilling/slaying.

**Supporting detail:**
- Many items "don't require you to constantly be at the GE."
- Good time/GP methods that **can't be done in high volume at once.**
- Aimed at growing the bank in spare time.

**Relevance to RSHelper:** A "passive/background" flip category — offers that don't need babysitting (long fill times, modest volume), distinct from active high-throughput flipping.

---

### [OSRS] Make 900k+ Overnight While Sleeping - Oldschool Runescape Money Making Method!

**URL:** https://www.ge-tracker.com/guides/view/osrs-make-900k-overnight-while-sleeping-oldschool-runescape-money-making-method

**Category:** Processing Arbitrage

**Key claim/strategy:** Overnight profit by **repairing damaged Barrows equipment** — buy damaged → repair → sell, using GE price info.

**Supporting detail:**
- Method: **repair damaged Barrows equipment** (buy → repair → sell).
- Requires GE price info; runs overnight.
- Easy method, ideal while asleep.

**Relevance to RSHelper:** Barrows repair = processing-arbitrage gated by the armour-repair mechanic; add to the processing engine alongside decanting and herb cleaning, scheduled for overnight windows.

---

### How To Not Waste Your G.E. Slots!! Easy Ways To Make Money With The Grand Exchange

**URL:** https://www.ge-tracker.com/guides/view/how-to-not-waste-your-g-e-slots-easy-ways-to-make-money-with-the-grand-exchange

**Category:** Tool Usage

**Key claim/strategy:** Most players underuse their GE slots; filling all slots is pure upside ("higher margins for me" when others don't).

**Supporting detail:**
- Thesis: too many players waste free GE slots.
- Self-interested: idle competitors → "higher margins for me," but they're losing profit.
- Uses a tracking site (link stripped).

**Relevance to RSHelper:** Slot-utilization is a free lever — surface "empty slots" alerts and auto-suggest offers to fill idle slots, prioritising the highest expected GP/hr per slot.

---

### TOP 5 DRAGON SLAYER 2 INVESTMENTS

**URL:** https://www.ge-tracker.com/guides/view/top-5-dragon-slayer-2-investments

**Category:** Investment Timing

**Key claim/strategy:** Short, punchy list of 5 items expected to rise on Dragon Slayer 2 hype; "get in before everyone else."

**Supporting detail:**
- Format: top-5 item list driven by DS2 quest hype.
- Thesis: new content release = "a money making method in itself."
- Asks for part-2 viewer suggestions.

**Relevance to RSHelper:** A "top-N catalyst investments" configurable ranking is a useful pre-release artefact; add a community-suggestion loop (like the random-items episode).

## External sources

### High Level Alchemy — OSRS Wiki

**URL:** https://oldschool.runescape.wiki/w/High_Level_Alchemy

**Category:** High Alchemy

**Key claim/strategy:** Authoritative alchemy mechanics: converts an item to coins = **60% of its store value**, 5-tick (3 s) cast, ~1,200 casts/hr, with a full break-even + profit item table.

**Supporting detail:**
- Mechanics: **level 55 Magic, 65 xp/cast, 5 ticks (3 s)/cast → ~1,200 casts/hr, ~78k xp/hr.** The valuable-item alch warning keys off **GE value**, not alch value (Ranger Boots: GE 33.3m vs alch 120 gp).
- Runes: **1 nature + 5 fire runes** (staff of fire or tome of fire eliminate fire runes); Explorer's ring 4 = 30 free alchs/day; Wilderness Fountain of Rune = free alchs but PK risk.
- Path to 99 = 197,967 casts. Money-making guide exists fletching profitable F2P alch items at **~480,280 gp/hr.**
- Big profit/loss table by item (rune/d'hide/dragon gear) with per-cast profit, buy limit, "invest 4 hrs" total — exactly the alch-throughput model.

**Relevance to RSHelper:** Canonical constants for the alch engine (60%, 3 s, 1200/hr, 65 xp) plus a sane valuable-item-alch safety warning keyed to GE value.

---

### RuneScape: Grand Exchange Market Watch/Alchemy — OSRS Wiki

**URL:** https://oldschool.runescape.wiki/w/RuneScape:Grand_Exchange_Market_Watch/Alchemy

**Category:** High Alchemy

**Key claim/strategy:** A maintained static calculator listing every GE item profitable to alch, with the exact per-item throughput formula factoring buy-limit × cast-rate × volume.

**Supporting detail:**
- Profit based on live **Nature rune = 147 coins.** **ROI % = profit / (item price + nature rune price).**
- **Max profit = profit × buying-limit, capped at 4,800 (= 1,200 alch/hr × 4 hours).**
- **Volume fallback: if volume < 6× buy limit AND volume < 28,800, max profit = profit × (volume / 6)** — you can only acquire volume/6 items, not the full limit.
- Columns: Item, GE Price, High Alch, Profit, ROI%, Limit, Volume, Max profit, Profit per Minute. A low value-drop warning threshold "severely reduces" profit/min on high-value items.

**Relevance to RSHelper:** This is the alch module's GP/hr formula: `max_profit = min(buy_limit, throughput) × profit/cast`, with `throughput` capped at 4,800 and floored by volume/6 when supply is thin. Implement the volume/6 cap and the valuable-warning interaction directly.

---

### OSRS High Alch Profit Guide 2026 — GE Margin (gemargin.com)

**URL:** https://gemargin.com/guides/high-alch-guide

**Category:** High Alchemy

**Key claim/strategy:** Live alch-profit guide (refreshed every 10 min) with the canonical formula and category-by-category risk/return guidance; nature rune 147 gp, ~1,200 casts/hr, hard GP/hr ceiling.

**Supporting detail:**
- Formula (verbatim): **`Alch Value − Buy Price − Nature Rune Cost = Profit`**; nature rune = **147 gp**; ~**1,200 casts/hr**; alch value = 60% of store price; equip fire staff/tome of fire to drop fire-rune cost.
- Categories: **rune equipment** (stable, generous buy limits, PvM supply) vs **dragon items** (higher profit/cast, more volatility) vs **jewelry/enchanted** (overlooked, profits when demand dips) vs **crafted** (battlestaves, dragonhide — steady skiller supply).
- Top live examples by profit/cast: **Amulet of the damned (full)** 2.7k/cast (limit 8), black d'hide body 1.4k, dragon med helm 1.3k, mystic lava staff 968, flamtaer hammer 861, dragon longsword 853.
- Alch vs flip: alch is **passive** (during agility/slayer/quests) with a **hard ~1,200 casts/hr ceiling**; flipping scales with bank; **combine both** (buy alch items while flip offers fill).

**Relevance to RSHelper:** Confirms the alch-vs-flip positioning and gives a category risk taxonomy + concrete top items; the "passive income with hard ceiling" framing should drive the alch module's UX (don't over-promise beyond ~1,200 casts).

---

### OSRS Flip Finder — Real-Time GE Margins (gemargin.com)

**URL:** https://gemargin.com/flip-finder

**Category:** Tool Usage

**Key claim/strategy:** A real-time flip finder exposing core scoring columns (Rating 1–10, Stability, Confidence, Trend, ROI%, Volume, Lock-up, Cap Eff) with budget-bracket presets — a model for a flip-finder's column set.

**Supporting detail:**
- Flip modes: **Quick Flips, Patient Flips, Overnight, Custom.** Budget presets: **100K / 500K / 1M / 5M / 10M / 50M / 100M+.**
- Filters: Min Volume, Max Buy Price, Min Margin, Type (F2P/Members). Sort by: **GP/hr, Margin, Potential, ROI%, Volume, Stability, Alch Profit, Cap Eff, Lock-up, Price.**
- Columns: **Rating (x/10), Stability (letter), Confidence (letter), Trend (%)**, Buy, Margin, ROI, Vol, Limit, GP/hr, Potential, **Cap Eff**, **Lock-up (e.g., 4hr)**.
- Live example rows: Sweetcorn (bowl) rating 10/10, ROI 1400%, vol 100, limit 13,000, GP/hr 145.3k, cap-eff 13.4m; Flamtaer bracelet 10/10, ROI 39.7%, vol 145, GP/hr 105.8k.

**Relevance to RSHelper:** A ready column vocabulary (Cap Efficiency, Lock-up, Stability, Confidence, Potential) to adopt and expose as sort keys and filters — particularly **Cap Eff** (capital efficiency) and **Lock-up** (expected fill time).

---

### 07Flip — OSRS Grand Exchange Flipping Tool

**URL:** https://07flip.com

**Category:** Tool Usage

**Key claim/strategy:** Real-time GE flipping tool with **30-second refresh**, organised into flip-relevant modules — a competitor feature map.

**Supporting detail:**
- Modules: **Flipping, Tracker, Alerts, High Alch, Barrows, Moons, Decanting, Creations, Categories, Item Sets, Optimiser**, plus Game Updates and a RuneLite plugin.
- Data from **OSRS Wiki Real-Time Prices API.** Cadence: live margins/profit math refreshed **every 30 seconds.**
- Guides: Flipping Guide, Beginner's Guide, Flipping with 10M, **GE Tax Guide, Buy Limits**, F2P Flipping, Merching Tips.

**Relevance to RSHelper:** Feature parity targets: 30s refresh, dedicated **Optimiser**, **Item Sets**, **Decanting**, **Creations**, alerts, RuneLite integration, and explicit GE-tax + buy-limit guides. The 30s cadence is a bar for "real-time" feel.

---

### OSRS Alchemy Profit Calculator (osrs-alchemy.com)

**URL:** https://osrs-alchemy.com

**Category:** High Alchemy

**Key claim/strategy:** A live alchemy calculator that takes **bankroll + time** and estimates profit against live GE prices, with explicit item-selection factors.

**Supporting detail:**
- Inputs: **bankroll (gp)** and **time (minutes)**; assumes a single item type bought up to bankroll within buy limit.
- Mechanics: **Low Alch = 40% of base value, 1 nature + 3 fire runes, level 21; High Alch = 60% of base value, 1 nature + 5 fire runes, level 55.** Staff of Fire waives fire runes (saves ~20–30 gp/cast).
- Item-selection factors: **Highest Profit** (most gp/cast but low returns + low buy limits), **Highest Return** (highest %), and a third rate factor.
- Pulls live prices from the OSRS Wiki API; warns prices/qty may be stale by offer time.

**Relevance to RSHelper:** Adopt the bankroll + time input model (project alch profit for a session before running) and the "profit vs return vs rate" three-factor item-selection framing.

---

### OSRS High Alch Calc (oldschool.tools)

**URL:** https://oldschool.tools/calculators/alchemy

**Category:** High Alchemy

**Key claim/strategy:** An alch calculator pulling official GE guide prices (with RuneLite fallback) and reminding users of buy limits and the cast-rate economics.

**Supporting detail:**
- Prices from **official GE guide prices**, with **RuneLite prices as fallback** when RuneLite lacks an item.
- Reminder: **buy limits every 4 hours.**
- Restated constants: **cast every 3 s → ~1,200 casts/hr → 65 xp/cast → ~78k xp/hr; 55 Magic required.**

**Relevance to RSHelper:** Use dual price sources (official GE guide price + RuneLite realtime) with graceful fallback; re-affirm these are the shared alch constants across the ecosystem.

---

### flipping.gg — highlights/profitable-alchs

**URL:** https://www.flipping.gg/highlights/profitable-alchs

**Category:** Other

**Key claim/strategy:** Client-side rendered alch-profits page (table loads via JS from the live price API) — **no extractable on-page text**, only the shell nav.

**Supporting detail:**
- Page is a JS-rendered SPA; raw HTML contains only nav/footer boilerplate (no item rows).
- Substantive content exists only after client-side fetch — not available to plain curl.
- Verified by fetching — treat as an interactive tool rather than a text guide.

**Relevance to RSHelper:** To extract flipping.gg data, a tool must use the **OSRS Wiki Real-Time Prices API** the same way the page does (client-side JSON), not scrape the static HTML.

---

### Adventures in Algorithmic Trading on the Runescape Grand Exchange — Tristan Rhodes

**URL:** https://tristanrhodes.com/blog/Adventures-in-Algorithmic-Trading-on-the-Runescape-Grand-Exchange

**Category:** Other

**Key claim/strategy:** A real ML market-making bot on the GE that ranks offers by forecasted gold/second, with baseline-vs-RF-vs-NN results — arguably the single most RSHelper-relevant source.

**Supporting detail:**
- GE constraints modelled: **4-hour per-item buy limit** (e.g., coal = 13,000); **GE tax** (author's older 1% form: `floor(0.01 * price) * quantity`, sell-side, per-item, rounded down, capped at 5m). **Note:** current rate is 2% since 29 May 2025 → update to `floor(0.02 * price) * quantity`, exempt under 50 gp.
- Architecture: JS client polls the **OSRS Wiki real-time price API every 5 min** (+hourly cron) recording price spreads, volume, buy limit → DB; Java client executes trades; Python ranks offers. Per-trade records: gold/second, profit, timestamp, item id. Train on 63→14 days ago, validate on latest 14 (anti-temporal-leakage).
- Baseline: per-item **ROI = (sell_total − tax − buy_total)/buy_total**, **volume ratio = 1h_volume_high/1h_volume_low**, 2-week avg gold/second; ROI z-score + volume-ratio z-score, filter historically-negative gold/second, sort descending.
- Results (1-week, mean profit/hr, 95% CI): **Random Forest 150,892 (129,140–172,643)**, Neural Net **123,923 (103,279–144,566)**, Baseline **87,353 (79,493–95,212)**. RF slightly beat NN; trades are high-frequency low-ROI.

**Relevance to RSHelper:** Directly applicable blueprint — adopt the OSRS-Wiki 5-min polling pipeline, the buy-limit + tax-aware ROI, the gold/second target, the train/validation time split, and the baseline (ROI-zscore + volume-ratio-zscore) as the floor any ML model must beat.

## Skipped / non-actionable

- **Video-only with no on-page text (22 ge-tracker pages).** Includes two of the user's key URLs explicitly: `osrs-flipping-profit-from-market-panic` and `flipping-1m-to-50m-in-f2p-1680k-profit-with-35mins-in-game-time`. Both pages contain only the author's credit block — no descriptive text. ~20 other low/no-text pages also skipped (e.g., "Grand Exchange Only Challenge #8–11", "10M to 1B with GE Tracker Ep 0–3", short "OSRS Flipping Guide For Beginners!", "Market Talk: BGS", several "Noob With a Mill" entries).
- **Pure PvM / skilling money-makers (reviewed and skipped, not GE):** the bulk of the 475-article set — fletching/farming/barrows-chest-loot/zulrah/wyvern/lava-dragon/shop-buying/speedrun loot guides. They carry GE-tracker referral links but no flipping/merching/alch mechanics in their text.
- **Vlog/series episodes with no new tactic:** many "Worthless to Wall Street," "P2P 0–100m," "Noob With a Mill," and "Road to 1B" episodes are narrative ("I made X this episode") with no extractable tactic beyond the series premise already captured in the Ep-1 / representative notes above.
- **External client-side SPAs:** `flipping.gg/highlights/profitable-alchs` returned only a JS shell (no item rows in static HTML); handled above as an interactive-tool note.

Raw HTML, parsed text per article, the relevance-scored manifest, and the candidate/focus review dumps are kept under `/Users/reidar/Documents/RSHelper/research/` for re-use.
***

## Competitor Landscape (pass 2 — competitive & similar-solution research)

Sources fetched fresh: GE Tracker pricing/feature pages, 07Flip site + 5 guides, gemargin (flip-finder, market-watch, calculators), Grand Flip Out (grandflipout.com) + RuneLite plugin-hub, RuneLite plugin hub (raw), OSRS Wiki Macroing + Real-Time Prices outreach, DreamBot home + forums, GitHub topics `osrs-flipping` & `osrs-bot`, Tristan Rhodes GitHub. Where pages were client-side SPAs (prices.runescape.wiki, RuneLite "show" pages, DreamBot forum threads), no static item rows were extractable — noted per entry.

### Summary table

| Competitor | Tier | Pricing | Automates GE offers? | Data source | Key differentiator |
|---|---|---|---|---|---|
| GE Tracker | Dashboard + mobile app | Free / £2/mo premium, 6mo £10.80, 12mo £20 | No — view only | RuneLite + OSRS Wiki | Reference incumbent; largest feature set; 4,627 items priced |
| 07Flip | Dashboard + RuneLite plugin | Free + paid premium | No — view only | OSRS Wiki Real-Time Prices API | 30s refresh; Optimiser; explicit GE-tax/buy-limit guides |
| GE Margin (gemargin.com) | Dashboard | Free + premium | No — view only | OSRS Wiki Real-Time Prices API | Cap Eff/Lock-up/Stability/Confidence columns; 9 sector indices; 17 calculators |
| Grand Flip Out | Intelligence engine + RuneLite plugin | Free + $4.99/mo Pro | **No — explicitly advisory only** | OSRS Wiki | Calibrated forecasts, DumpScanner, ripple/Weibull models, "falsifiable track record" |
| RuneLite plugin hub (Flipping Utilities, Flipping Copilot, Flipper2, FlipSmart, 07Flip plugin, Flipping Masterminds) | In-client plugins | Free | No — view/track only | RuneLite / per-plugin | Live inside the client; 7+ flip plugins compete |
| OSRS Wiki Real-Time Prices API | Data backbone (not a tool) | Free / fair-use API | n/a | RuneLite price-reporter crowd | Every tool above piggybacks on this; the supply-chain choke point |
| Tristan Rhodes ML bot (rhodesrt/ML_exercises) | Open-source research bot | Free / code | **Yes — full automation** | OSRS Wiki 5-min poll | RF 150,892 gp/hr beats NN 123,923 beats naive 87,353 |
| Open-source OSRS bots (runebot, colorbot, runescape-ML, osrs-yolov5) | Open-source bots | Free / code | Yes | varies | Colour-bot/ML-vision approaches; community code |
| DreamBot | Botting client (RSHelper's automation layer) | Free 2 bots / VIP $9.99-mo / Sponsor $49.99-6mo | **Yes — rule-violating automation** | injection into client | Most anti-ban-oriented bot client; "Covert Mode" + "Exclusive Injections" (paid) |

---

### GE Tracker — pricing & feature matrix

**URL:** https://www.ge-tracker.com/pricing

**Category:** Other (Competitor: Dashboard Tool)

**Key claim/strategy:** Reference incumbent. Free tier (2-day premium trial, 5 suggested items at 5-min intervals); **Premium £2/mo** (6mo £10.80 with 10% off, 12mo £20 with 2 months free). Currently prices **4,627 items** via RuneLite + OSRS Wiki.

**Supporting detail:**
- Free: Suggested Items tool (5 at a time), 5-minute pricing intervals, 2-day premium trial.
- Premium Flip Finder unlocks: Suggested Items (no limit), Favourite Items, **Highest Margins, High Volume, New Items, GE Limits** flip finders, exclusive day-timeline graphs, Market Watch Index.
- Premium money-making calculators: Blast Furnace, Cooking & Brewing, Tan Leather, Fletching, **Herblore Profit, Decant Potions, Enchanting, High Alchemy, Magic Tablet, Plank Making, Tree Sapling, Item Sets, Barrows Repair, Combination Items, Store Profit Calculator**.
- Premium profit tracker: Item page recording, public & private merchanting logs, most-profitable-items (personal), Active Transactions, **Import from RuneLite**, Mobile App, Price Alerts (Unlimited / Email 100 per month / SMS 30 per month). **API Access: "Public API temporarily disabled."**

**Relevance to RSHelper:** GE Tracker's premium confirms the standard dashboard price ceiling (~£2/mo ≈ $2.50/mo) and the full feature checklist RSHelper must match or undercut. Their **disabled public API** is a gap RSHelper could exploit (expose a clean API). The **Import from RuneLite** + **Price Alerts** + **Active Transactions** combo is the baseline for a profit tracker.

---

### 07Flip — flip finder + tax/buy-limit guides + Optimiser

**URL:** https://07flip.com (guides: https://07flip.com/guides/ge-tax, https://07flip.com/guides/buy-limits, https://07flip.com/guides/flipping, https://07flip.com/guides/f2p-flipping, https://07flip.com/guides/osrs-flipping-10m-method)

**Category:** Other (Competitor: Dashboard + RuneLite Plugin)

**Key claim/strategy:** Real-time GE flip finder with a **30-second refresh**, an explicit "Optimiser" tool, a RuneLite plugin, and the cleanest published GE-tax & buy-limit guides. Data from the **OSRS Wiki Real-Time Prices API.** Modules: Flipping, Tracker, Alerts, High Alch, Barrows, Moons, **Decanting, Creations, Categories, Item Sets, Optimiser**, Game Updates, Price Alerts.

**Supporting detail:**
- **GE tax mechanics (07flip's spec):** 2% on sales since Dec 2021, **capped at 5M/item**; **formula `Tax = min(SellPrice × 0.02, 5,000,000)`, `Profit = SellPrice − Tax − BuyPrice`**; items >250M effective rate <2% (Twisted Bow 1.2B → 5M tax ≈ 0.4%); **rule of thumb: subtract ~2pp from raw spread for post-tax; treat anything under ~2% spread as break-even/worse.** Worked example: 100k buy / 103k sell → tax 2,060 → profit 940 (a 3% spread becomes sub-1%).
- **Buy limits (07flip):** runes/arrows/bolts 13,000–20,000; common resources (ore, logs, herbs) 10,000–13,000; potions/food 2,000–10,000; standard weapons & armour 70–125; Barrows equipment 15; rare items (Twisted Bow, Scythe) 8. **Rolling 4-hr timer per item, account-wide, persists logout/world hop, selling not limited**, can be split across offers. **"Profit per limit" = post-tax profit × buy limit — the number that matters.** Optimiser sizes each slot to the lower of `limit × price` vs `what you can afford` automatically.
- **F2P:** 3 GE slots (not 8), smaller item pool, can't use members-only money makers (decanting, barrows repair) → membership "roughly triples throughput" by going 3→8 slots. Progression benchmarks: 0–100k (gather/sell), 100k–2M (high-volume cheap), 2M–10M (rune equipment), then bond.
- **10M method:** divide across 4–8 slots, allocate 1–2.5M/slot; realistic **300k–1M/day**; portfolio vs volume vs dip-buy strategies; sample items: Super Combat Pot, Sara Brew, Prayer Pot, Rune platebody, Slayer helm variants, Mahogany logs, Battlestaves, Broad arrows, Nature runes (13k limit × 5gp = 65k/cycle × 3 cycles × 4 items = 780k/day).

**Relevance to RSHelper:** 07Flip's guides are concrete test fixtures: the tax rule (≤2% spread = don't flip), the buy-limit-by-category table, the 10M 300k–1M/day benchmark, and the Optimiser sizing formula are all verifiable design targets for RSHelper's flip-finder and bankroll allocation. The 30s refresh sets the "real-time" bar.

---

### GE Margin (gemargin.com) — flip finder + 9 sector indices + 17 calculators

**URL:** https://gemargin.com (flip-finder: https://gemargin.com/flip-finder; market-watch: https://gemargin.com/market-watch)

**Category:** Other (Competitor: Dashboard Tool)

**Key claim/strategy:** A real-time flip finder whose scoring columns (Rating/10, Stability letter, Confidence letter, Trend %, Cap Eff, Lock-up) and **9 live sector indices** are the closest published model to an "intelligent" Finder without claiming intelligence.

**Supporting detail:**
- Flip modes: **Quick / Patient / Overnight / Custom.** Budget presets: 100K, 500K, 1M, 5M, 10M, 50M, 100M+. Sort keys: **GP/hr, Margin, Potential, ROI%, Volume, Stability, Alch Profit, Cap Eff, Lock-up, Price.**
- **9 sector indices** tracked in real time with 5m/1h/24h/7d/30d charts + top movers: Food & Consumables, Runes, Herbs & Potions, Ores & Bars, Logs & Planks, Weapons, Armour, Skilling Resources, **Raids & Boss Drops.**
- **17 calculators:** High Alch, Blast Furnace, Herblore, Cooking, Fletching, Tan Leather, Gem Cutting, Herb Cleaning, Plank Making, Bolt Enchanting, Decanting, Item Sets, **Buy Limit Timer**, GE Tax, Death's Coffer, NMZ Rewards, Raids Drops.
- High-alch guide restates the canonical formula `Alch Value − Buy Price − Nature Rune Cost = Profit` with nature = 147 gp, ~1,200 casts/hr, 60% of store value.

**Relevance to RSHelper:** gemargin's column vocabulary (**Cap Eff = capital efficiency, Lock-up = expected fill time, Stability, Confidence, Potential**) is de-facto industry diction RSHelper should adhere to. The "buy-limit timer" calculator and the sector-index view are both feature parity targets. The Live example row "Sweetcorn (bowl) ROI 1400%, vol 100, cap-eff 13.4m" shows how huge ROI% pairs with thin volume — exactly the trap RSHelper's risk-weighting must filter.

---

### Grand Flip Out — intelligence engine + open-source RuneLite plugin (advisory only)

**URL:** https://grandflipout.com (RuneLite plugin hub: https://runelite.net/plugin-hub/show/grand-flip-out)

**Category:** Other (Competitor: Intelligence Engine)

**Key claim/strategy:** The most direct competitor to RSHelper's *intelligence* ambition: a server-side analytics engine with **five published models** — and an explicit, prominent disclaimer that it **never places or automates Grand Exchange trades; the player always executes in-game.** Free core forever + Pro $4.99/mo. Open-source RuneLite plugin.

**Supporting detail:**
- Five engineering models (verbatim from site): **DumpScanner** (3-classifier dump scorer with recovery-odds ranking), **Calibrated buy/sell bands** (conformal-calibrated, targeting ~90% coverage; flags thin items before they waste a GE slot), **Ripple forecasting** (when one item moves, related items follow — second-order flips), **Rhythm** (CUSUM regime detection + per-item seasonal rhythm — separates a temporary dip from a structural shift), **Weibull hazard** (next-dump forecast — stages gp *before* the crash to buy the bottom, not the slide).
- **"Realizable, not fantasy"** — every GP figure is net of the 2% GE tax and **capped to what you can actually buy and sell** ("never margin × limit"). Opportunity-map bubble chart plotted by liquidity × realizable profit, bubble size = **JTI** (a composite score), colour = safety.
- **Head-to-head comparison table (verbatim) vs Flipping Copilot / Flipping Utilities / GE Tracker** — GFO-only features: published falsifiable track record, calibrated confidence ranges, realizable (tax-net, volume-capped) profit, pre-market patch-impact alerts (NLP, before the market). Shared with at least one rival: RuneLite plugin, dump alerts.
- Pricing: Free forever (all 23+ intelligence modules, dump alerts + recovery intervals, JTI scoring, open-source RuneLite plugin, web dashboard + trade log, capped watchlist alerts); **Pro $4.99/mo** for pre-market patch-impact calls, **Kelly-sized entries**, all-watchlist alerts.
- Disclaimer (verbatim): *"GrandFlipOut is a third-party analytics companion. It tracks prices, flags opportunities and fires alerts — it never places or automates Grand Exchange trades. You always execute in-game. Not affiliated with Jagex."*

**Relevance to RSHelper:** GFO is the closest analog to RSHelper's *analysis* half — and it deliberately stops short of the *execution* half RSHelper is building (DreamBot). Concrete steal-worthy techniques: conformal-calibrated buy/sell bands with thin-item flagging, **CUSUM regime detection**, **Weibull next-dump timing**, **ripple/second-order item models**, "realizable profit" (tax-net + volume-capped) instead of `margin × limit`, **Kelly sizing** on entries, and a **published falsifiable track record** (RSHelper's backtest should ship its own). RSHelper's differentiation must be the safe-but-passive (GFO) vs. risky-but-active (RSHelper+DreamBot) axis — and the user must be warned that the active axis carries Rule-7 ban + skill/bank rollback exposure.

---

### RuneLite Plugin Hub — 7+ in-client GE flipping plugins

**URL:** https://runelite.net/plugin-hub

**Category:** Other (Competitor: In-client Plugin Ecosystem)

**Key claim/strategy:** The RuneLite plugin hub ships a crowded field of **free, in-client** GE flipping plugins — the layer users reach before any web dashboard. Grep of the hub found seven relevant plugins.

**Supporting detail:**
- **Flipping Utilities** — flip tracking in client.
- **Flipping Copilot** — "Flip suggestions, price predictions, and pro…" — closest in-client analog to an intelligence layer.
- **Flipper2** — "Track your buys, sells, flips and in-progress Grand Exchange offers locally."
- **FlipSmart / Flip-Smart** — "A comprehensive tool for flipping items in the Grand Exchange."
- **Grand Flip Out** — "Free GE flipping assistant with real-time OSRS Wiki pric… tax math (2% capped at 5M GP), and local flip P&L tracking with session GP/hr. Local-only by default; optional grandflipout.com features."
- **07Flip - GE Flip Finder** — RuneLite client for 07flip.com ("Live Grand Exchange data from 07flip.com. Top flips, price dumps, per-item i…").
- **Flipping Masterminds** — "Grand Exchange market watch and flipping recommendations inside RuneLite."

**Relevance to RSHelper:** The in-client ecosystem sets a "free, always-available, no-context-switch" floor. RSHelper competes on (a) automation DreamBot provides that RuneLite plugins legally/politely cannot, and (b) the backtesting/paper-trading depth GFO hints at but plugins don't ship. If RSHelper ships a RuneLite-side hint companion (rather than DreamBot-only), it lives in this crowded field.

---

### OSRS Wiki Real-Time Prices API — the shared data backbone

**URL:** https://prices.runescape.wiki/osrs/ (the live price guide); docs hosted by Weird Gloop (the wiki's parent)

**Category:** Market Mechanics (Data Backbone)

**Key claim/strategy:** Every dashboard competitor (GE Tracker, 07Flip, gemargin, Grand Flip Out) and Tristan Rhodes's ML bot pull the **same** OSRS Wiki Real-Time Prices API, which is itself fed by RuneLite price-reporters. RSHelper would inherit the same single point of dependence.

**Supporting detail:**
- The hub lives at `prices.runescape.wiki/osrs/` and is referenced from the OSRS Wiki Grand Exchange Market Watch page as "The Old School Wiki's real-time price guide."
- Tristan Rhodes's bot pipelines this API **every 5 minutes** (price spreads, volume, buy limit) plus an hourly cron; fields per item: average price, volume, buy limit. The 5-min cadence matches his trade execution loop.
- 07Flip and gemargin both attribute data: "Price data from the OSRS Wiki Real-Time Prices API." GE Tracker attributes "live pricing data is provided by players using the RuneLite game client. Information is also collected from the OSRS Wiki."
- The hub pages themselves are **client-side SPAs** (returned ~533 bytes of static shell); item rows load via JSON fetch — not crawlable with plain curl. Any RSHelper ingestion must use the documented JSON API endpoints, not scrape HTML.

**Relevance to RSHelper:** RSHelper should design against the documented API directly (same endpoint everyone uses), build a 5-min polling pipeline like Rhodes's, and **gracefully degrade** if the API is rate-limited or the RuneLite reporter crowd thins (the whole ecosystem's supply chain). A multi-source fallback (Wiki API + RuneLite realtime + official GE guide prices, per oldschool.tools's pattern) is a defensibility move competitors haven't loudly made.

---

### DreamBot — RSHelper's automation layer (and the rule-violating botting market)

**URL:** https://dreambot.org

**Category:** Other (Competitor/Context: Botting Client)

**Key claim/strategy:** DreamBot is the **botting client** RSHelper's "in-game automation via Dreambot" rests on — an injection-based OSRS bot explicitly marketing itself as the "most anti-ban oriented bot on the market." Tiers: Free (2 bots), VIP **$9.99/mo** (unlimited bots, **Covert Mode**, Exclusive Injections, Discord webhooks), Sponsor $49.99/6mo.

**Supporting detail:**
- "Tired of getting banned with other bots? DreamBot is the most anti-ban oriented bot on the market." Marketing leans *hard* on ban avoidance — implying bans are the default expectation with rival botting clients.
- VIP-exclusive features: **Covert Mode** (anti-detection), **Exclusive Injections** (faster/evading-game-update detection). DreamBot is primarily an **injection bot** (modifies/hooks the client), not a colour bot — the bot type that is easier for Jagex to break with a code update but more capable.
- Disclaimers all over the site: "RuneScape® is a trademark of Jagex© 1999-2026 Jagex Ltd. DreamBot, Inc. is not in any way affiliated with Jagex Ltd." — every botting client loudly disclaims affiliation because none is permitted.
- Mac/Windows/Linux; "Completely free botting, no strings attached"; script marketplace with curated premium scripts.

**Relevance to RSHelper:** RSHelper inherits DreamBot's ban risk profile and pricing. Worth tracking: (a) DreamBot VIP ($9.99/mo) stacks on top of RSHelper's own price — budget this into RSHelper's positioning; (b) "Covert Mode" / "Exclusive Injections" are the anti-detection levers — RSHelper scripts that ignore them (default free tier, no Covert Mode) will ban faster; (c) a DreamBot game-update outage breaks RSHelper's whole execution layer in a way the dashboard-only competitors (GFO/07flip/gemargin) are immune to.

---

### OSRS Wiki: Macroing — Jagex's rules on botting (RSHelper's compliance exposure)

**URL:** https://oldschool.runescape.wiki/w/Macroing

**Category:** Risk Management (Compliance/Risk)

**Key claim/strategy:** Jagex treats third-party automation of user input as **Rule 7 violation (macroing/botting)** with bans and **skill/bank rollback**. Bot type matters: colour bots (no code read/write) are "almost undetectable" if scripted well; injection bots (DreamBot's primary mode) are more capable but breakable by game updates.

**Supporting detail:**
- "Usage of macros is not allowed under the RuneScape rules (Rule 7) and may result in action taken against that player's account, such as a temporary or permanent ban."
- "Jagex has the authority and power to **reset or rollback a player's skill levels and/or bank value before initiating a ban**" — so a caught botters's banked GP/items can be wiped, not just the account.
- Bot taxonomy: colour bots (recognise colours/images on screen and click — "if scripted well, they can be **almost undetectable to Jagex**"), injection bots (inject into the RuneScape client, read code, can act like a human — broken by game updates, e.g. the "Bot Nuke"), reflection bots, OpenGL/DirectX bots, packet bots.
- Historical enforcement waves: "ClusterFlutterer" (October 2011, disabled most injection/reflection bots), **Botwatch** (modern heuristic detection), repeated bot-nuke updates.

**Relevance to RSHelper:** This is RSHelper's headline *non-technical* risk and its single biggest differentiator from every dashboard competitor. Implication: every dashboard rivals (GFO/07Flip/gemargin/GE Tracker/RuneLite plugins) deliberately stays on the "advisory only, you execute" side of Rule 7 — RSHelper is on the other side. RSHelper should (a) surface an unambiguous in-app warning that automation violates Rule 7 and risks **bank rollback**, (b) favour human-like pacing + DreamBot Covert Mode, (c) keep an "advisory only" degraded mode (no DreamBot) as the safe-by-default path the user can choose — exactly the mode GFO ships as its *only* mode.

---

### Tristan Rhodes ML bot — open-source algorithmic trading code

**URL:** https://tristanrhodes.com/blog/Adventures-in-Algorithmic-Trading-on-the-Runescape-Grand-Exchange (code: https://github.com/rhodesrt/ML_exercises/tree/main/random_forest — `random_forest.ipynb`, `neural_net.ipynb`)

**Category:** Other (Competitor: Open-source ML bot)

**Key claim/strategy:** A full **automated** GE market-making bot with **public training code** — the closest published precedent to RSHelper's automated execution half. Results: RF 150,892 gp/hr > NN 123,923 > naive baseline 87,353 (1-week, 95% CI).

**Supporting detail:**
- Architecture (recap): JS client polls OSRS Wiki API every 5 min (+hourly cron) → DB (price spreads, volume, buy limit); Java client executes trades; Python ranks offers. Target = gold/second. Train on trades 63→14 days prior, validate on latest 14 (anti-temporal-leakage).
- Baseline: per-item **ROI = (sell_total − tax − buy_total)/buy_total**, **volume ratio = 1h_volume_high/1h_volume_low**, 2-week avg gold/second; ROI z-score + volume-ratio z-score; filter historically-negative gold/second; sort descending.
- **The model code is public** at `github.com/rhodesrt/ML_exercises/blob/main/random_forest/` (Random Forest and Neural Net notebooks) — so RSHelper can read the exact feature engineering and target definition.
- Note his tax form predates the May 2025 2% hike (`floor(0.01 * price) * qty`); RSHelper must use `floor(0.02 * price) * qty` with the 5M cap.

**Relevance to RSHelper:** RSHelper's backtest/ranking floor should reproduce Rhodes's baseline as a sanity check (and beat it). His public notebooks give a concrete starting feature set; his train/validate split (63→14d train, 14d validate, gold/second target) is a defensible evaluation protocol RSHelper's own backtesting mode should adopt or annotate.

---

### Open-source OSRS bot ecosystem on GitHub

**URL:** https://github.com/topics/osrs-bot and https://github.com/topics/osrs-flipping

**Category:** Other (Competitor/Context: Open-source bot ecosystem)

**Key claim/strategy:** A scattered open-source bot ecosystem already exists; not direct product competitors to RSHelper but a reference for *what techniques are public* and *how others approach Jagex detection*.

**Supporting detail:**
- Snapshot of repos under github.com/topics/osrs-bot (top hits): **tarranprior/runebot**, **ivan-guerra/colorbot** (a colour bot — the harder-to-detect family per the Macroing page), **kaiergin/runescape-ML**, **tarkojs/osrs-yolov5** (YOLOv5 vision-based bot), **pashpashpash/RunescapeBots**, **JHoweWowe/RuneLiteBot**, **JonneSaloranta/Epicbot-Quester**, **bottimaakari/osrs-gui-bots**, **beezyscriptsdreambot/pkheaven** (DreamBot script — same platform RSHelper uses), **Adept-Team-OS/OSRS.github.io**, **xsat/osrs**.
- Two technical families visible: **ML/vision bots** (runescape-ML, osrs-yolov5 — the colour/yolov angle) and **injection/script bots** (runebot, DreamBot scripts). GE-flipping topic page returned mostly topic-tag navigation, not clean repo rows.
- These are hobby projects (no clear product packaging, pricing, or support) — not the threat GE Tracker / GFO / 07Flip are.

**Relevance to RSHelper:** Worth a periodic watch — open-source bots publish techniques Jagex also reads, which raises detection risk for everyone injecting. The colour-bot/ML-vision approach (colorbot, osrs-yolov5) is the technically *harder-to-detect* alternative to DreamBot's injection; flag for RSHelper as a future detection-resistance option if DreamBot's injection breaks under a game update.

---

### Synthesis — what the competitor research teaches RSHelper

1. **Two distinct markets,** separated by Rule 7. Dashboard/intelligence tools (GE Tracker, 07Flip, gemargin, Grand Flip Out, RuneLite plugins) are advisory-only and safe; botting clients (DreamBot and the GitHub bot ecosystem) execute. **RSHelper sits in the botting lane by virtue of DreamBot integration** — every safe competitor deliberately avoids it. Treat "advisory-only mode" as a first-class product mode, not a degradation: it is the entire product of the strongest rival (Grand Flip Out).
2. **Grand Flip Out is the competitor to beat for "intelligence."** Steal its techniques (conformal-calibrated bands, CUSUM regime, Weibull next-dump, ripple/second-order, "realizable profit" = tax-net + volume-capped, JTI composite, Kelly entry sizing, published falsifiable track record). Match its pricing band (GFO Free + $4.99/mo Pro; GE Tracker ~£2/mo; Flipping Copilot ~$7/mo) — RSHelper should price automation as a premium tier above these (it carries ban risk no rival does).
3. **Adopt the industry column vocabulary.** Cap Eff (capital efficiency), Lock-up (expected fill time), Stability, Confidence, Potential, JTI, "realizable" vs "margin × limit", Rating/10 with letter grades — gemargin and GFO have de-facto standardised this diction; using a different vocabulary costs RSHelper users migrating from rivals.
4. **Tax arithmetic is now a competitive baseline,** not a feature: 07Flip, gemargin, and GFO all ship `Tax = min(SellPrice × 0.02, 5M)` net-of-tax by default. RSHelper's flip finder must show only tax-and-volume-capped "realizable" profit; raw margin × limit is now correctly described as "fantasy."
5. **Buy-limit × cycle budget is the right denominator,** per 07Flip's Optimiser: size each slot to `min(limit × price, what-you-can-afford)` and report "profit per limit" / "profit per 4-hr cycle," with realistic benchmarks (10m bank → 300k–1m/day; 6 cycles/day theoretical ceiling).
6. **Single data backbone = shared supply-chain risk.** All rivals read the OSRS Wiki Real-Time Prices API fed by RuneLite reporters. RSHelper's defensibility move is multi-source fallback (Wiki API + RuneLite realtime + official GE guide prices + a buy-limit dataset) — none of the rivals loudly sells this resilience.
7. **Risk disclaimer is a feature, not a cost.** GFO's prominent "advisory only, never automates, not affiliated with Jagex" copy is the safety posture every safe competitor ships. RSHelper must go further — an unambiguous Rule 7 + **bank-rollback** warning on first launch, default to advisory-only, and explicit opt-in for DreamBot execution. Without this, RSHelper's first user-facing sentence is materially riskier than any rival's.
8. **Backtest as a moat.** GFO publishes a "falsifiable track record"; Rhodes publishes train/validation split + 95% CIs. RSHelper's backtesting mode is one of the few features no lightweight dashboard ships — make its methodology public and reproducible (Rhodes's 63→14d train / latest-14d validate, gold/second target) so the numbers are defensible, not marketing.
9. **Open-source bots raise detection for everyone.** Public colour/yolov/injection repos on `github.com/topics/osrs-bot` are read by Jagex too. RSHelper's DreamBot scripts inherit detection improvements Jagex builds against *those* — keep scripts human-paced and use DreamBot's paid Covert Mode; budget VIP into RSHelper's cost model.

Raw HTML and parsed text for this pass are kept under `/Users/reidar/Documents/RSHelper/research/raw/external/` and the competitor review dumps alongside the original pass. The client-side SPA pages (prices.runescape.wiki, RuneLite "show" pages, DreamBot forum threads, flipping.gg) returned only JS shells and are noted as such per entry — full content would require the OSRS Wiki's documented JSON API rather than static scraping.
