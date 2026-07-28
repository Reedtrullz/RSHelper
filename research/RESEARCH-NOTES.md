# OSRS Grand Exchange Flipping Research Notes
# Compiled for RSHelper automated trading tool

---

## Key Individual Articles

### Benefits Complete OSRS Flipping Guide

**URL:** https://www.ge-tracker.com/guides/view/benefits-complete-osrs-flipping-guide-old-school-runescape

**Category:** Flipping Strategy

**Key claim/strategy:** Comprehensive merchanting guide covering GE mechanics, margin analysis, volume classification, merchant psychology, chart analysis, bubble detection, and game update effects — treating RS markets with the same rigor as real-world financial trading.

**Supporting detail:**
- GE matching mechanics: oldest buy offer gets priority when prices match; new sell offers match against highest existing buy offer (allowing accidental overpayment). This means order placement timing matters.
- Volume classification system: High volume (runes, logs, food, potions, ore, bars) = safest for margin checks, thin margins. Average volume (whips, ranger boots, barrows) = gray area, margin check at own risk. Low volume = avoid unless rare/new items with demonstrated demand.
- Bubble detection: If an item hits its historic high with no game update to justify it, it's likely a bubble and should be avoided. The long-term moving average line on charts shows the true trend direction.
- Merchant skill tiers: Beginners (uncreative, mimic others, quit after losses), Average merchants (1m-500m profit, herd mentality, flip common items, emotionally reactive), Masterminds (500m-2bil+, long-term planners, read every dev blog/Q&A, patient with months-long holds, comfortable with big risks).
- Game update investing: Buy before dev blogs when community + JMod support is strong. NEVER invest a few days before an update — players dump items on release day. New items are most volatile and profitable flips because buy/sell offers are scattered.
- No item sinks in OSRS: items with declining player base will naturally depreciate. AGS cited as example of long-term decline due to niche PK use + new item introductions.
- DWH case study: crashed from ~70m to ~40m after release (failed as PK weapon), then recovered when discovered as best Corporeal Beast weapon — illustrating the importance of finding hidden utility.
- Candlestick charts: hollow bodies = downward movement, solid bodies = upward. Collection of same-type bodies indicates bullish/bearish trend. Wick length indicates speed of price movement.
- ROI interpretation: Low-valued cosmetics can show 0-99% ROI but require long hold times. High-valued in-demand items show 0-30% ROI with faster transactions.

**Relevance to RSHelper:** This guide provides the foundational framework for RSHelper's flip scoring: volume classification tiers, margin analysis methodology, bubble detection signals, game update timing windows, and the importance of chart-based trend analysis over raw margin numbers.

---

### OSRS High Alch Profit Guide 2026 (GE Margin)

**URL:** https://gemargin.com/guides/high-alch-guide

**Category:** High Alchemy

**Key claim/strategy:** High alchemy converts items to gold at 60% of store value; with live price data, 143 items are currently profitable to alch with nature runes at 150 GP.

**Supporting detail:**
- Profit formula: Alch Value - Buy Price - Nature Rune Cost = Profit
- Cast rate: ~1,200 alchs per hour at maximum speed
- Fire staff/tome eliminates fire rune cost (saves 20-30gp per cast)
- Explorer's Ring 4: 30 free high alchs per day (no runes, no XP)
- Top profit/cast: Dragon med helm (4.3k profit, but only 8 buy limit), Amulet of the damned full (2.7k profit, 8 limit)
- Best GP/hour: Mystic water staff (660k/hr, 18,000 buy limit), Earth battlestaff (555.6k/hr, 18,000 limit), Onyx bolts(e) (555.6k/hr, 11,000 limit)
- Budget alch items under 5k: Rune dagger(p+) 1.1k profit/cast, Flamtaer hammer 858 profit/cast
- Buy limit is the real bottleneck: high profit/cast items often have 8-70 limits; high GP/hr items need 10,000+ limits
- Alching is best combined with other activities (agility rooftop courses, slayer)
- Alching has a hard GP/hour ceiling; flipping scales with bank size

**Relevance to RSHelper:** RSHelper's high alch module should rank items by profit/hour (not just profit/cast), account for buy limits as a hard constraint, factor in nature rune cost fluctuations, and surface the Explorer's Ring free alch opportunity. The 1,200 casts/hour rate is the throughput ceiling.

---

### High Level Alchemy (OSRS Wiki)

**URL:** https://oldschool.runescape.wiki/w/High_Level_Alchemy

**Category:** High Alchemy

**Key claim/strategy:** Official wiki reference for alchemy mechanics — 65 Magic XP per cast, 60% of store value, 5-tick cast speed, with specific profit/loss tables for crafting chains.

**Supporting detail:**
- Cast speed: 5 ticks (3.0 seconds) = 1,200 casts/hour theoretical max
- 65 Magic XP per cast; 197,967 casts needed from 55 to 99 Magic
- Explorer's Ring 4: 30 free casts/day, no XP gained
- Fountain of Rune (Wilderness): free casts, no XP, but PK risk
- Tome of Fire + Burnt Pages: alternative fire rune elimination
- Bryophyta's Staff: saves nature runes (1/15 chance), but costs more than Staff of Fire savings
- Profit/loss tables show items like Rune platebody (alch 37,800), Adamant platebody (alch 16,800)
- Crafting+Smithing+Fletching+High Alch chains create compounding profit opportunities

**Relevance to RSHelper:** The 5-tick cast speed and 197,967 cast count for 55-99 are hard constraints for the alch simulator. The wiki's profit tables should be cross-referenced with live GE prices. The Fountain of Rune and Explorer's Ring are edge cases worth flagging.

---

### Grand Exchange Market Watch/Alchemy (OSRS Wiki)

**URL:** https://oldschool.runescape.wiki/w/RuneScape:Grand_Exchange_Market_Watch/Alchemy

**Category:** High Alchemy

**Key claim/strategy:** Live alchemy profit table with nature rune cost at 147 GP, showing maximum profit calculated as profit * min(buy_limit, 4800) capped by volume.

**Supporting detail:**
- Nature rune price: 147 GP (live from GE Market Watch)
- Max profit formula: profit * min(buying_limit, 4800) — where 4800 = 1200 casts/hr * 4 hours
- Volume adjustment: if volume < 6x buy limit AND volume < 28,800, use profit * (volume / 6)
- Top items by profit/cast: Eclipse moon helm broken (1,700 profit, 15 limit), Dragon med helm (1,347, 8 limit), Ancient ceremonial legs (1,225, 8 limit)
- Profit per minute column accounts for buy limit bottlenecking
- Warning: high-value item alching with valuable drop warning set too low causes delays
- Specific items with data: Mystic lava staff (968 profit, 8 limit, 2,156 volume), Verac's flail (881 profit, 15 limit, 18 volume)

**Relevance to RSHelper:** The volume-adjusted max profit formula is directly implementable: `profit * min(buy_limit, 4800)` with volume correction when `volume < 6 * buy_limit AND volume < 28800`. This is the exact calculation RSHelper should use for alch profitability scoring.

---

### 07Flip — OSRS Grand Exchange Flipping Tool

**URL:** https://07flip.com

**Category:** Tool Usage

**Key claim/strategy:** Real-time GE flipping tool updating every 30 seconds via OSRS Wiki Real-Time Prices API, providing live margins, profit math, and confidence scores.

**Supporting detail:**
- Data source: OSRS Wiki Real-Time Prices API (official, not third-party scraping)
- Update frequency: every 30 seconds
- 4,500+ items tracked with 50+ tools and filters
- Each flip shows: buy price, sell price, profit, ROI percentage, and confidence score
- Confidence score based on: trade volume, price volatility, and data freshness
- 2% GE tax automatically factored into profit calculations
- RuneLite plugin integration for in-game features
- Example top flips: Harmonised orb +5.6M GP, Imbued heart +2.2M GP, Torva armour set +1.6M GP

**Relevance to RSHelper:** The confidence score concept (trade volume + volatility + freshness) is directly applicable to RSHelper's flip scoring. RSHelper should implement a similar composite confidence metric. The 30-second update cycle from the Wiki API is the recommended data refresh rate.

---

### Tristan Rhodes — Adventures in Algorithmic Trading on the Runescape Grand Exchange

**URL:** https://tristanrhodes.com/blog/Adventures-in-Algorithmic-Trading-on-the-Runescape-Grand-Exchange

**Category:** Tool Usage

**Key claim/strategy:** ML-powered market making bot using random forest and neural network models to rank GE offers by forecasted profitability, outperforming a naive baseline significantly.

**Supporting detail:**
- System architecture: JavaScript API (Wiki price stream) + Java client (character actions) + Python API (offer ranking)
- Data pipeline: two cron jobs polling OSRS Wiki API every 5 minutes and every hour, recording price spreads and volumes to database
- Baseline model variables: ROI Z-score, volume ratio Z-score, average gold/second over last 2 weeks
- Baseline algorithm: compute ROI Z-score + volume ratio Z-score per item, filter out historically negative gold/second, sort descending
- Training data: 63 days prior to 14 days prior (training), most recent 14 days (validation) — prevents temporal leakage
- ML results: random forest performed best, edging out neural network; both significantly outperformed baseline
- GE tax: 1% on sell offers for items >100 GP, capped at 5M per offer, applied per-item rounded down
- Buy limit example: coal ore = 13,000 per 4 hours
- Trade data fields: gold/second generated, absolute profit, timestamp, item ID
- Model target: gold/second generated (not raw profit)

**Relevance to RSHelper:** This is the closest published research to RSHelper's backtesting engine. The baseline model (ROI Z-score + volume ratio Z-score) is a simple starting point for RSHelper's flip scoring. The gold/second target metric is more useful than raw profit for comparing flips across different time horizons. The 5-minute data polling cadence matches the Wiki API's update frequency.

---

### Top 10 Bad Habits You Should Avoid While Flipping

**URL:** https://www.ge-tracker.com/guides/view/top-10-bad-habits-you-should-avoid-while-flipping-osrs

**Category:** Trader Psychology

**Key claim/strategy:** Common flipping mistakes that cost money, many driven by time pressure and impatience — awareness of these habits is the first step to avoiding them.

**Supporting detail:**
- Time pressure from content creation kills patience, leading to rushed and bad flips
- The 10 bad habits are personal observations from a prolific flipper (no specific list in text — video content)
- Impatience leads to cutting losses too early or chasing margins
- Rushing margin checks leads to overpaying
- Key insight: many bad habits stem from treating flipping as a race rather than a patient practice

**Relevance to RSHelper:** RSHelper should automate the patience-dependent aspects: margin checking (use API data instead of manual checks), offer placement timing, and loss management. The tool should prevent human psychological biases from affecting trade decisions.

---

### How to Decant Potions for Consistent High Margin Flips

**URL:** https://www.ge-tracker.com/guides/view/osrs-how-to-decant-potions-for-consistent-high-margin-flips-an-advanced-flipping-guide-4

**Category:** Processing Arbitrage

**Key claim/strategy:** Decanting potions into 4-dose versions is a consistent, low-effort profit method due to high demand for 4-dose potions.

**Supporting detail:**
- Buy potions in various dose configurations (1, 2, 3 dose), decant to 4-dose for profit
- Works at any starting cash amount
- Consistent demand because players prefer 4-dose potions for efficiency
- GE Tracker has a dedicated decanting potions tool for finding profitable decant opportunities
- Works as a background flip while waiting for other offers to fill

**Relevance to RSHelper:** RSHelper should implement a decanting calculator that compares per-dose prices across 1-dose, 2-dose, 3-dose, and 4-dose versions, factoring in the decanting process time and any noted potion-specific quirks.

---

### Profit from Market Panic

**URL:** https://www.ge-tracker.com/guides/view/osrs-flipping-profit-from-market-panic

**Category:** Investment Timing

**Key claim/strategy:** Market panics create buying opportunities — when players dump items in fear, prices drop below fair value, creating profitable entry points for patient merchants.

**Supporting detail:**
- Panics are driven by herd psychology, not fundamental value changes
- Average merchants are "single handedly responsible for skyrockets and crashes"
- Masterminds profit by buying during panics and selling during recovery
- Key: distinguish between panic-driven drops and fundamental value declines (e.g., new item replacing old one)
- Game updates are the most common panic trigger

**Relevance to RSHelper:** RSHelper's backtesting should model panic detection: rapid price drops without corresponding fundamental news (new item, Q&A announcement) should trigger "panic discount" signals. The tool should differentiate between temporary panics and permanent value declines.

---

### [OSRS Flipping] Managing Money and Risks

**URL:** https://www.ge-tracker.com/guides/view/osrs-flipping-managing-money-and-risks

**Category:** Risk Management

**Key claim/strategy:** Designate a fixed percentage of daily earnings toward flipping capital; maintain a 1:1 ratio between spendable GP and GE flipping capital to manage risk.

**Supporting detail:**
- If investing 50% of cash earnings into flipping, by the time you have 100m spendable GP, you should also have 100m in the GE
- This division eases stress on individual item positions
- Reduces risk by not over-committing to any single flip
- Increases earning potential by keeping capital deployed
- Apply this rule consistently regardless of current market conditions

**Relevance to RSHelper:** RSHelper should implement position sizing rules: never commit more than X% of total bank to a single flip, and maintain a target ratio between liquid GP and GE-locked capital. The 50% rule is a reasonable default for the risk management module.

---

### [OSRS Flipping/Merching] Cleaning Herbs for a Profit

**URL:** https://www.ge-tracker.com/guides/view/osrs-flipping-merching-cleaning-herbs-for-a-profit

**Category:** Processing Arbitrage

**Key claim/strategy:** Cleaning herbs (removing grimy herbs to clean versions) trains Herblore while making a profit — a dual-benefit processing arbitrage.

**Supporting detail:**
- Buy grimy herbs from GE, clean them for profit + Herblore XP
- Works because cleaned herbs often sell for more than grimy versions
- Dual benefit: GP profit + skill training
- Herblore requirement varies by herb level

**Relevance to RSHelper:** RSHelper should include a herb cleaning calculator that compares grimy vs clean herb prices across all herb types, factoring in Herblore level requirements and net profit per click.

---

### [OSRS Flipping/Merching] Decanting Potions for Money

**URL:** https://www.ge-tracker.com/guides/view/osrs-flipping-merching-decanting-potions-for-money

**Category:** Processing Arbitrage

**Key claim/strategy:** Use GE Tracker's decanting tool to find the most profitable potions to invest in; decanting is a great background money-maker while other flips are filling.

**Supporting detail:**
- Dedicated decanting potions tool available on GE Tracker
- Works as a background activity alongside active flipping
- Potion demand is consistent and high
- Can be done at any cash level

**Relevance to RSHelper:** Confirms decanting as a viable background activity for the automated trading system. RSHelper should run decanting calculations passively while primary flips are pending.

---

### Spotting Short-Term Bubbles (Part 2) — The Importance of Game Knowledge

**URL:** https://www.ge-tracker.com/guides/view/osrs-flipping-merching-spotting-short-term-bubbles-pt-2-the-importance-of-game-knowledge

**Category:** Market Mechanics

**Key claim/strategy:** Staying consistently informed on game updates, developer blogs, and Q&A streams is essential for detecting bubbles and making informed investments.

**Supporting detail:**
- "There's nothing worse than an uninformed merchant trying to make uninformed investments"
- Game knowledge is the primary edge over other merchants
- Developer blogs and Q&A streams contain forward-looking information
- Bubble detection requires understanding WHY an item's price is moving

**Relevance to RSHelper:** RSHelper should incorporate game update tracking (polls, dev blogs, Q&A transcripts) as input signals for flip scoring. Items near upcoming content changes should have adjusted risk scores.

---

### Spotting Mini Short-Term Self-Imploding Bubbles

**URL:** https://www.ge-tracker.com/guides/view/osrs-merching-flipping-spotting-mini-short-term-self-imploding-bubbles

**Category:** Market Mechanics

**Key claim/strategy:** Learn to spot potential price crashes before they happen by identifying mini bubbles — short-term self-imploding price spikes.

**Supporting detail:**
- Mini bubbles are smaller, shorter-lived versions of major bubbles
- They "self-implode" when the buying pressure exhausts
- Detection requires monitoring price velocity relative to historical norms
- These are exploitable for quick profit if you can sell before the implosion

**Relevance to RSHelper:** RSHelper's real-time monitoring should flag items with abnormal price velocity (rapid increases inconsistent with volume) as potential mini-bubble candidates, suggesting reduced position sizes or sell signals.

---

### How to Make 1M+ GP Per Hour Using High Alch Spell

**URL:** https://www.ge-tracker.com/guides/view/how-to-make-1m-gp-per-hour-using-high-alch-spell-old-school-runescape

**Category:** High Alchemy

**Key claim/strategy:** A specific high alch method using rev bracelets can achieve 1M+ GP/hr as long as bracelet prices stay low.

**Supporting detail:**
- Requires only 55 Magic (minimum for High Alchemy)
- Uses rev bracelets as the alch target
- Profit depends on rev bracelet GE price staying low
- "More cash more helpful obviously though"
- Early competition will thin out, improving margins over time
- Margins are self-correcting: if profit disappears, price naturally recovers due to in-game mechanics

**Relevance to RSHelper:** RSHelper should monitor item-specific alch methods that exploit temporary price dislocations (like rev bracelet pricing) and flag them as time-sensitive opportunities.

---

### How to Flip Super Rare Items for Insane Overnight Profits (Advanced Guide #6)

**URL:** https://www.ge-tracker.com/guides/view/how-to-flip-super-rare-items-for-insane-overnight-profits-an-advanced-flipping-guide-6-osrs

**Category:** Flipping Strategy

**Key claim/strategy:** Super rare items (master clue rewards, items trading <100/day) offer insane overnight margins but require 10-20m starting capital and days of patience.

**Supporting detail:**
- "Super rare" = items trading less than 100 per day (not just expensive items like Pegasian boots)
- Master clue scroll rewards are prime targets
- Minimum 10-20m starting capital needed
- Flips can take days to complete
- Patience is the key requirement
- Overnight offers are essential because these items trade infrequently

**Relevance to RSHelper:** RSHelper should have a "super rare" flip mode that targets items with <100 daily volume, uses overnight offer strategies, and adjusts expected completion time to days rather than hours.

---

### How to Use Our Candlestick Charts — Part One

**URL:** https://www.ge-tracker.com/guides/view/osrs-flipping-how-to-use-our-candlestick-charts-part-one

**Category:** Tool Usage

**Key claim/strategy:** Candlestick charts show short-term moving trends more visibly than line charts; learning to read them provides an edge over other merchants.

**Supporting detail:**
- Candlestick charts are in beta — don't work with all items/timeframes
- Hollow bodies = downward movement, solid bodies = upward
- They show: high (highest offer), open (where offers placed), body (trades completed), close (where offers completed), low (lowest offer)
- Collective same-type bodies indicate bullish/bearish trends
- More useful than line charts for short-term trend detection
- Referenced external resources: Investopedia candlestick guide, StockCharts school

**Relevance to RSHelper:** RSHelper's chart visualization should include candlestick mode for short-term analysis. The open/close/high/low data points from GE Tracker's candlestick format map directly to OHLC candlestick data.

---

### How to Pick Profitable Items and Flip Them Correctly (Advanced Guide)

**URL:** https://www.ge-tracker.com/guides/view/osrs-how-to-pick-profitable-items-and-flip-them-correctly-an-advanced-flipping-guide-2016

**Category:** Flipping Strategy

**Key claim/strategy:** Read exchange charts (RSBuddy/GE Tracker) to determine which items flip quickly and at what price point, using chart data rather than gut instinct.

**Supporting detail:**
- RSBuddy Exchange charts were the original data source (now GE Tracker)
- Buy limits page: https://oldschool.runescape.wiki/w/Grand_Exchange/Buying_limits
- Read charts to determine item liquidity and fair price ranges
- Expensive items need different approach than cheap items
- Chart reading is the fundamental skill for advanced flipping

**Relevance to RSHelper:** This confirms that chart-based analysis (volume, price history, buy limits) is the foundational methodology for automated flip identification. RSHelper should replicate this chart-reading logic programmatically.

---

### Flipping High Volume Items for Easy and Low Risk Profit (Advanced Guide #5)

**URL:** https://www.ge-tracker.com/guides/view/osrs-how-to-flip-high-volume-items-for-easy-and-low-risk-profit-an-advanced-flipping-guide-5

**Category:** Category Specialization

**Key claim/strategy:** High volume items (500,000+ traded/day) are the safest flipping category with very small chance of losing money if done correctly.

**Supporting detail:**
- Definition of high volume: 500,000+ items traded per day
- Very small chance of losing money with correct execution
- Perfect for beginners or those seeking low-risk profit
- Margins are thin but consistent
- Volume ensures quick buy/sell completion

**Relevance to RSHelper:** RSHelper should classify items with 500k+ daily volume as "high volume" tier, assign them lower risk scores, and recommend them as starting points for new users or conservative strategies.

---

### Flipping Overnight and Taking Advantage of Bot Dumps (Advanced Guide #2)

**URL:** https://www.ge-tracker.com/guides/view/osrs-how-to-flip-items-overnight-and-take-advantage-of-bot-dumps-an-advanced-flipping-guide-2

**Category:** Flipping Strategy

**Key claim/strategy:** Place offers overnight to catch bot dumps and price dips that occur during off-peak hours; requires a GE tracking tool for 24-hour price history.

**Supporting detail:**
- Can start with any amount of money
- Must use a GE tracking tool to view 24-hour price history
- Bot dumps create temporary price dips exploitable by patient flippers
- Overnight offers typically complete while you sleep
- Price patterns repeat daily — off-peak hours offer better buy prices

**Relevance to RSHelper:** RSHelper should implement overnight offer scheduling: place buy offers below current price during off-peak hours (typically 2-6 AM game time), targeting items with demonstrated overnight price dips. The 24-hour price history is essential for setting appropriate offer prices.

---

### Make 1000k Overnight While Sleeping — Page Set Combining

**URL:** https://www.ge-tracker.com/guides/view/osrs-make-1000k-overnight-while-sleeping-oldschool-runescape-money-making-method

**Category:** Set Arbitrage

**Key claim/strategy:** Buy individual pages (1, 2, 3, 4) overnight and combine into page sets for profit — requires 10m minimum (30m recommended).

**Supporting detail:**
- Buy page 1, 2, 3, and 4 individually from GE
- Leave offers in overnight — they typically complete while sleeping
- Combine into complete page sets for profit
- 10m minimum starting capital, 30m recommended
- Low effort, passive income method
- Relies on individual pages being cheaper than the set value

**Relevance to RSHelper:** RSHelper's set arbitrage calculator should include page sets alongside armor sets. The overnight scheduling feature should be able to place multi-item set component offers simultaneously.

---

### Make 700k Overnight in F2P — Armor Set Combinations

**URL:** https://www.ge-tracker.com/guides/view/osrs-make-700k-overnight-in-f2p-oldschool-runescape-money-making-method

**Category:** Set Arbitrage

**Key claim/strategy:** Combining armor sets in F2P is extremely profitable overnight, using green d'hide and saradomin rune armor sets.

**Supporting detail:**
- F2P set combining is viable and profitable
- Main sets: green d'hide, saradomin rune armor
- GE Tracker has a F2P setting for finding item combinations
- Similar method to P2P page sets but adapted for free-to-play items
- Overnight passive income

**Relevance to RSHelper:** RSHelper should support F2P mode for set arbitrage calculations, filtering to only F2P-tradeable items. The set component finder should work across both P2P and F2P item databases.

---

### How I Made 2.3m in 1 Hour Flipping Dagannoth King Drops Only

**URL:** https://www.ge-tracker.com/guides/view/osrs-how-i-made-2-3m-in-1-hour-of-flipping-dagannoth-king-drops-only-episode-15

**Category:** Category Specialization

**Key claim/strategy:** Flipping by boss-specific item category (Dagannoth King drops) yielded 2.3m in one hour — category specialization works.

**Supporting detail:**
- Items: archer ring, berserker ring, seers ring, warrior ring
- Category: Dagannoth King drops only
- 2.3m profit in 1 hour (described as "mostly due to luck")
- Boss-specific item categories have concentrated demand
- Suggestion: other boss categories could be similarly profitable

**Relevance to RSHelper:** RSHelper should organize flip suggestions by boss/PvM category, allowing users to focus on item ecosystems they understand. Boss drop tables are natural category boundaries for flipping.

---

### 1 Hour Merching with 30M on 5 Accounts

**URL:** https://www.ge-tracker.com/guides/view/1-hour-merching-with-30m-on-5-accounts-insane-results

**Category:** Multi-Account

**Key claim/strategy:** Running 5 accounts simultaneously with 30m each (150m total) dramatically increases flipping throughput beyond what a single account can achieve.

**Supporting detail:**
- 150m total across 5 accounts (30m each)
- Multiple accounts bypass the 8 GE slot limitation
- "Merching is the best way to make money in the game" — most efficient method
- Results described as potentially 5M+ per hour
- 10 minutes spent finding items at start (would be less if already in a rhythm)
- Final 5 minutes of merching thrown away (still profitable)

**Relevance to RSHelper:** RSHelper should support multi-account operation as a scaling mechanism. The tool should be able to manage flip portfolios across multiple GE slot pools (8 per account), optimizing capital allocation across accounts.

---

### Building an Insane 100 Account Flipping Farm

**URL:** https://www.ge-tracker.com/guides/view/building-an-insane-100-account-flipping-farm-accounts-21-to-25-flipping-on-100-accounts-osrs

**Category:** Multi-Account

**Key claim/strategy:** Scaling to 100 accounts requires careful item selection (high volume, low cost items like empty jugs and fishing bait) and at least 3m per account for optimal operation.

**Supporting detail:**
- 100 accounts = 800 GE slots
- Items used: empty jug, fishing bait (very low cost, very high volume)
- Dropped rune essence because "takes way too long to sell"
- Target: at least 3m per account for adequate capital
- Requires 1-2 week breaks to generate more capital
- Item selection is critical — items that don't sell fast enough create bottlenecks

**Relevance to RSHelper:** RSHelper's item selection algorithm should penalize items with slow sell-through rates, even if margins are high. Capital efficiency at scale requires items that cycle quickly. The 3m/account minimum is a useful benchmark for multi-account mode.

---

### Flipping Item Sets for One Hour with 7M Start

**URL:** https://www.ge-tracker.com/guides/view/osrs-flipping-item-sets-for-one-hour-with-7m-start-easy-money-oldschool-runescape

**Category:** Set Arbitrage

**Key claim/strategy:** Flipping common item sets (especially Barrows equipment sets) is consistently profitable, with 7m being sufficient starting capital.

**Supporting detail:**
- Barrows equipment sets are the primary targets
- Also includes repairing barrows armor and decanting potions
- "Item sets and crafting category" is a reliable profit zone
- 7m starting capital is sufficient
- Set combining is a well-established, repeatable method

**Relevance to RSHelper:** RSHelper should include Barrows set arbitrage as a default strategy, calculating the spread between individual pieces and the complete set price.

---

### Day of Release Flipping (Dragon Slayer 2)

**URL:** https://www.ge-tracker.com/guides/view/day-of-release-flipping-is-the-only-thing-that-keeps-me-alive-dragon-slayer-2

**Category:** Investment Timing

**Key claim/strategy:** Day-of-release flipping is extremely high risk but potentially very high reward — "when you hit big its lit, when you don't, its not."

**Supporting detail:**
- Dragon Slayer 2 release items were the target
- Can lose money when bone prices spike against you
- Most volatile trading environment in the game
- Requires quick decision-making and tolerance for losses
- New content releases create the widest margins but also the biggest risks

**Relevance to RSHelper:** RSHelper should have a "release day" mode with wider margin tolerance, faster offer adjustment, and explicit risk warnings. The tool should track upcoming content releases as calendar events.

---

### What We Can Learn From the Rise and Falls of Raid Items

**URL:** https://www.ge-tracker.com/guides/view/what-we-can-learn-from-the-rise-and-falls-of-raid-items-merching-tips

**Category:** Investment Timing

**Key claim/strategy:** Looking at 9-month charts of raid items reveals predictable patterns in how new content items behave over time.

**Supporting detail:**
- Raid items follow predictable lifecycle: hype spike → correction → stabilization
- 9-month lookback reveals long-term trends
- Items that find niche uses (DWH for Corp) can recover from initial crashes
- Items without sustained demand continue declining
- Historical chart analysis is essential for predicting future behavior

**Relevance to RSHelper:** RSHelper's backtesting should model item lifecycle phases: hype, correction, stabilization. Items in the "correction" phase may be buying opportunities; items in the "stabilization" phase are safer flips.

---

### Is Flipping Expensive Items with 500M Worth It?

**URL:** https://www.ge-tracker.com/guides/view/is-flipping-expensive-items-with-500m-worth-it

**Category:** Capital Efficiency

**Key claim/strategy:** Testing whether high-capital flipping (500m) outperforms proportionally — video content with minimal text.

**Supporting detail:**
- Tests flipping high-priced items with 500m capital
- Video-only with minimal text explanation
- Presumably shows that higher capital enables higher per-flip profit

**Relevance to RSHelper:** RSHelper should model expected returns at different capital levels (10m, 50m, 100m, 500m) to help users understand how their bank size affects viable item selection and expected GP/hr.

---

### What Are the Best Items to Flip on OSRS?

**URL:** https://www.ge-tracker.com/guides/view/what-are-the-best-items-to-flip-on-osrs-how-to-find-the-right-item-make-bank

**Category:** Flipping Strategy

**Key claim/strategy:** Links to a Google spreadsheet with flip recommendations — item selection is the most important decision in flipping.

**Supporting detail:**
- References a Google Sheets spreadsheet with item data
- Finding the right item is more important than execution
- Item selection drives the majority of flipping success

**Relevance to RSHelper:** RSHelper's flip finder should be the core value proposition — automated item selection based on the criteria outlined across all these guides.

---

### Flipping 1M to 50M in F2P

**URL:** https://www.ge-tracker.com/guides/view/flipping-1m-to-50m-in-f2p-1680k-profit-with-35mins-in-game-time

**Category:** Capital Efficiency

**Key claim/strategy:** Starting with just 1m in F2P, it's possible to reach 50m through disciplined flipping — 1,680k profit in 35 minutes of in-game time.

**Supporting detail:**
- 1m starting capital in F2P
- 1,680k profit in 35 minutes of actual game time
- F2P flipping is viable and profitable
- Growth from small capital is possible with patience

**Relevance to RSHelper:** RSHelper should support a "growth mode" that starts with minimal capital and progressively unlocks higher-value items as the bank grows. F2P mode should be a first-class feature.

---

### Flipping Most Traded Items for Easy Money (20M Start)

**URL:** https://www.ge-tracker.com/guides/view/osrs-flipping-most-traded-items-for-easy-money-20m-start

**Category:** Category Specialization

**Key claim/strategy:** Flipping the most traded items is easy money with a 20m start — volume is king.

**Supporting detail:**
- 20m starting capital
- Focus on most traded (highest volume) items
- Profit is "good just not great" when main items aren't available
- Volume ensures quick turnover
- Easy and low-risk approach

**Relevance to RSHelper:** Confirms that volume-based item selection is the safest strategy. RSHelper should default to sorting by volume for new users.

---

### How I Make 15-20M Per Day Flipping Items

**URL:** https://www.ge-tracker.com/guides/view/osrs-how-i-make-15-20m-per-day-flipping-items

**Category:** Flipping Strategy

**Key claim/strategy:** 15-20M per day is achievable through consistent flipping — minimal text, video-driven content.

**Supporting detail:**
- 15-20M daily profit target
- Consistent daily flipping routine
- Video content with no specific method details in text

**Relevance to RSHelper:** Provides a benchmark daily profit target for RSHelper users with mid-to-high capital levels.

---

## External Sources

### GE Margin — Flip Finder (tool page)

**URL:** https://gemargin.com/flip-finder

**Category:** Tool Usage

**Key claim/strategy:** Live flip finder that scores every tradeable item with a composite rating and exposes the full scoring feature set a flip-finding tool should compute.

**Supporting detail:**
- Flip modes: Quick Flips, Patient Flips, Overnight, Custom. Budget presets: 100K, 500K, 1M, 5M, 10M, 50M, 100M+.
- Filters: Min Volume, Max Buy Price, Min Margin, F2P/Members.
- Sort dimensions: GP/hr, Margin, Potential ROI %, Volume, Stability, Alch Profit, Cap Eff (capital efficiency), Lock-up time.
- Per-item columns (verbatim): Rating x/10, Stability grade (A-F), Confidence, Trend %, Buy price, Margin, ROI %, Volume, Buy Limit, GP/hr, Potential, Cap Eff, Lock-up (e.g. "4hr", "32min").
- Example rows (2026-07-26 snapshot): Bolt of canvas — 10/10, stab C, margin 232, ROI 7.5%, vol 2,392, limit 13,000, GP/hr 453.1k; Pure essence — vol 1,290,143, limit 30,000; White platebody — margin 3.9k, ROI 146.2%, vol 13, limit 125 (classic low-volume high-ROI profile).
- Stability grades and confidence flags (warning icons) are shown per item; low-volume items get F grades even at high ROI.

**Relevance to RSHelper:** This is essentially a competitor feature spec for RSHelper's flip finder: adopt the same scoring columns (margin, ROI%, volume, buy limit, GP/hr, stability grade, lock-up time) and the Quick/Patient/Overnight mode split, which maps directly to RSHelper's active vs passive trading strategies.

---

### OldSchool.tools — High Alch Calc

**URL:** https://oldschool.tools/calculators/alchemy

**Category:** High Alchemy

**Key claim/strategy:** Alchemy profit calculator pulling live prices from the official Grand Exchange with RuneLite price fallback.

**Supporting detail:**
- "High Alchemy requires 55 magic and converts items into coins. It can be cast every 3 seconds, giving roughly 1,200 casts per hour. At 65 experience per cast, this yields about 78k xp/hour."
- Prices are official GE guide prices (may not perfectly represent paid price); RuneLite prices used when available, GE guide price as fallback.
- Notes that GE buy limits restrict purchases to a fixed amount every 4 hours.

**Relevance to RSHelper:** Confirms the 1,200 casts/hr ceiling and 3-second cast time used in RSHelper's alch GP/hr formula, and validates a dual-source price strategy (official GE API with RuneLite/wiki prices as fallback).

---

### 07Flip (https://07flip.com)

(Covered above under Key Individual Articles)

---

### OSRS Alchemy Calculator (https://osrs-alchemy.com)

**URL:** https://osrs-alchemy.com

**Category:** High Alchemy

**Key claim/strategy:** Interactive alchemy calculator that factors in bankroll, time, and buy limits to recommend personalized alching sessions.

**Supporting detail:**
- Three optimization targets: Highest Profit (per cast), Highest Return (ROI%), High Limit (sustained sessions)
- Composite score balances profitability, efficiency, and convenience
- Dynamic adjustment based on bankroll and time constraints
- Tips: always use Staff of Fire, consider Tome of Fire, use Explorer's Ring for free alchs
- Alch + Agility combo is most popular (cast between rooftop obstacles)
- Rotate between items to avoid 4-hour buy limit bottleneck
- Buy overnight so items are ready when you return
- Common mistakes: forgetting nature rune costs, ignoring buy limits, not refreshing prices

**Relevance to RSHelper:** The three-factor optimization (profit per cast, ROI%, buy limit) is the exact model RSHelper should implement. The dynamic adjustment based on bankroll and time is directly applicable to RSHelper's session planner.

---

### Flipping.gg — Profitable Alchs

**URL:** https://www.flipping.gg/highlights/profitable-alchs

**Category:** High Alchemy

**Key claim/strategy:** Empty/JS-rendered page — no text content extracted.

**Supporting detail:**
- Page appears to require JavaScript rendering
- No extractable text content

**Relevance to RSHelper:** Skip — no actionable data extracted.

---

## Research Dimensions Summary

---

## Pass 2 — Remaining Key Articles and Listing-Page Scan (2026-07-26)

Method note: all 47 listing pages (advanced-flipping 1-5, flipping-guides, all guides 1-41) were fetched and catalogued — 470 unique articles. Every flipping/merching/alching-relevant guide page not already covered in Pass 1 was fetched and read. The large majority of remaining entries are video-log episodes ("1 hour flipping challenge", "Worthless to Wall Street", "0-100m series") with 1-3 paragraphs of description and no strategy text; they are listed as skipped at the end of this section.

### Insane Margins Flipping 3rd Age Items — High Risk/High Reward

**URL:** https://www.ge-tracker.com/guides/view/osrs-insane-margins-flipping-3rd-age-items-high-risk-high-reward-flipping

**Category:** Investment Timing

**Key claim/strategy:** Buy ultra-rare items after a content-driven crash, on the thesis that prestige items recover once the panic seller cohort is exhausted.

**Supporting detail:**
- "When raids came out, nearly all of the 3rd age items crashed in price. My guess is that most people sold these to get money for raids... This is a perfect time to buy them, since I believe that 3rd age prices will recover eventually."
- Two-pronged play: long-term investment in one piece (3rd age mage hat) while actively flipping other 3rd age armor pieces on the side.

**Relevance to RSHelper:** Suggests an event-driven signal for RSHelper: when a major PvM update launches, watch unrelated prestige/rare items for liquidation crashes and flag them as recovery candidates.

---

### Insane Margins Flipping New Raid Reward Drops — Day 2

**URL:** https://www.ge-tracker.com/guides/view/osrs-insane-margins-flipping-new-raid-reward-drops-day-2-high-risk-high-reward-flipping

**Category:** Investment Timing

**Key claim/strategy:** Brand-new GE items have scattered buy/sell offers while prices settle, producing extreme margins for flippers willing to absorb the risk.

**Supporting detail:**
- "The raid rewards have just been released on the G.E and the prices are still settling. Flipping brand new items like this can be extremely risky, but also very profitable."
- Day-2 session started with 50m; affordable new items at that capital: dragon sword, dragon harpoon, dragon thrownaxe, ancestral hat, dragon hunter crossbow, twisted buckler; Dinh's bulwark still out of reach.

**Relevance to RSHelper:** RSHelper should detect newly-listed item IDs and treat their first days as a distinct high-risk regime with widened spread expectations, matching the backtester's "new item" category.

---

### How to Get the Largest Margins By Flipping Rare Items (Advanced Flipping Guide #3)

**URL:** https://www.ge-tracker.com/guides/view/osrs-how-to-get-the-largest-margins-by-flipping-rare-items-an-advanced-flipping-guide-3

**Category:** Category Specialization

**Key claim/strategy:** Rare items carry the largest margins in the game, but the process must be followed carefully because mistakes are expensive.

**Supporting detail:**
- "Flipping rare items is not extremely difficult, but it is possible to lose a lot of money if done incorrectly."
- Mostly video content; the process itself (margin-checking rares, patience on fills) is not in the text. Companion piece to Advanced Guides #2 (bot dumps) and #6 (super rare overnight flips) already covered in Pass 1.

**Relevance to RSHelper:** Reinforces gating the rare-item lane behind stricter risk limits in RSHelper — the margin ceiling is highest here, but so is per-trade loss potential.

---

### Complete Guide to Flipping for Beginners — Game Updates (pt. 2)

**URL:** https://www.ge-tracker.com/guides/view/osrs-flipping-complete-guide-to-flipping-for-beginners-game-updates-pt-2

**Category:** Game Update Effects

**Key claim/strategy:** Game updates are the single most influential force on prices, and the edge comes from tracking Q&As before official blog posts.

**Supporting detail:**
- "Updates to the game are by far the most influential forces behind price changes."
- "A good merchant will keep tabs of Q&As in anticipation of their official blog posts."

**Relevance to RSHelper:** Supports adding a dev-blog/Q&A watch input to RSHelper's event signals; price-impact anticipation happens before the official announcement, not after.

---

### The Different Types of Merchants — Beginners to Masterminds

**URL:** https://www.ge-tracker.com/guides/view/osrs-flipping-the-different-type-of-merchants-beginners-to-masterminds

**Category:** Trader Psychology

**Key claim/strategy:** Merchants fall into three skill tiers — beginners, average, and masterminds — and tier behavior is what moves markets.

**Supporting detail:**
- Three main categories explicitly named: beginners, average, masterminds (same taxonomy as the Benefits guide covered in Pass 1).
- Video-driven; text adds no further detail beyond the tier framing.

**Relevance to RSHelper:** Confirms the herd-behavior model: the "average merchant" majority is the crowd RSHelper's contrarian signals (panic buying, bubble avoidance) should trade against.

---

### Ultimate 1GP to 1M Flipping Guide

**URL:** https://www.ge-tracker.com/guides/view/osrs-ultimate-1gp-to-1m-flipping-guide-how-to-get-your-first-mil-by-flipping

**Category:** Capital Efficiency

**Key claim/strategy:** At tiny bankrolls, cheap clue scroll items are the fastest first-million route because margins are enormous relative to item price.

**Supporting detail:**
- "I am going to be focusing on how to flip cheap clue scroll items, as they can have massive margins for their price."
- Requires only basic GE understanding; positioned as the entry rung before the 1GP-2147M guide.

**Relevance to RSHelper:** For RSHelper's low-budget mode, clue-scroll uniques and other cheap low-volume items should rank above thin-margin volume staples because ROI% dominates at small capital.

---

### Ultimate 1GP — 2147M Flipping Guide

**URL:** https://www.ge-tracker.com/guides/view/osrs-ultimate-1gp-2147m-flipping-guide-how-to-get-a-max-cash-stack-from-flipping

**Category:** Capital Efficiency

**Key claim/strategy:** The path from 1 GP to max cash is about cycling through item *categories* as capital grows, not finding one magic item.

**Supporting detail:**
- "This guide is going to be a brief overview of what types of items you should be flipping... more focused on certain categories of items that will be good."
- Cross-references the decanting guide and advanced flipping guides as the capital ladder progresses.

**Relevance to RSHelper:** Validates budget-tiered item selection in RSHelper: the viable item universe should be a function of current bankroll, re-evaluated as capital compounds.

---

### How to Break Even High Alching

**URL:** https://www.ge-tracker.com/guides/view/osrs-how-to-break-even-high-alching-oldschool-runescape-high-alching-guide

**Category:** High Alchemy

**Key claim/strategy:** Break-even or profitable alching is a search problem: compare GE buy price against alch value minus nature rune cost across the whole item set.

**Supporting detail:**
- Method: use a price tracker to compare live prices, margins, and high alchemy values rather than memorizing a static item list.
- Framing: "every gp saved is worth 2 gp earned" — alching as a money-saving tool (Magic XP at zero net cost), not only a money maker.

**Relevance to RSHelper:** RSHelper's alch scanner should recompute profitable/break-even sets from live prices continuously (as it does) rather than relying on static item lists, and should surface "free XP" break-even alchs as a separate tier from profit alchs.

---

### Alching for Profit (Part 2 — Just Items)

**URL:** https://www.ge-tracker.com/guides/view/osrs-alching-for-profit-part-2-just-items

**Category:** High Alchemy

**Key claim/strategy:** Names a concrete starter list of reliably profitable alch items.

**Supporting detail:**
- Item list: "D'hide bodies - sometimes alch for 1k profit, Rune Axe, Rune sq Shield, Rune Full Helm, Adamant Platebodies, Lava Battlestaffs."

**Relevance to RSHelper:** Historical sanity-check items for the alch scanner — these classic profitable alchs should consistently appear in RSHelper's results when margins allow.

---

### Making Unfinished Potions — 600k/hour

**URL:** https://www.ge-tracker.com/guides/view/osrs-flipping-merching-making-unfinished-potions-600k-hour

**Category:** Processing Arbitrage

**Key claim/strategy:** Buying clean herbs plus vials and combining them into unfinished potions yields ~600k/hour, with a dedicated tool to find profitable herb/potion pairs.

**Supporting detail:**
- "Making upwards of 600k/hour" via the unfinished-potion route; GE Tracker ships a dedicated unfinished potion money-making tool.
- Herblore framed as profitable to train when driven by buy→process→sell arbitrage.

**Relevance to RSHelper:** Unfinished potion making is a third processing-arbitrage lane (alongside decanting and herb cleaning) RSHelper should model: `(unf potion price) - (clean herb price + vial price) - tax`, times craft rate.

---

### Make 900k+ Overnight While Sleeping — Barrows Repair

**URL:** https://www.ge-tracker.com/guides/view/osrs-make-900k-overnight-while-sleeping-oldschool-runescape-money-making-method

**Category:** Processing Arbitrage

**Key claim/strategy:** Buy damaged Barrows equipment, repair it, and resell — an overnight-capable processing arbitrage worth 900k+.

**Supporting detail:**
- Method: "repairing damaged barrows equipment" — buy broken pieces on the GE, repair, sell the fixed version.
- Explicitly positioned as passive/overnight income; needs live GE price data to find which pieces are profitable.

**Relevance to RSHelper:** Barrows repair is a fourth processing-arbitrage pattern (buy degraded → repair → sell) with a checkable formula: `repaired price - broken price - repair cost - tax`.

---

### Make 500k+ Overnight / At Work Every Day (#2 High Volume Traded Items)

**URL:** https://www.ge-tracker.com/guides/view/osrs-make-500k-overnight-at-work-every-day-2-high-volume-traded-items

**Category:** Overnight Strategies

**Key claim/strategy:** Passive daily income from leaving offers in high-volume items overnight or while at work, using a tracker to pick candidates.

**Supporting detail:**
- 500k+ per overnight/work session; candidates chosen from high-volume traded items via GE Tracker.
- Method 2 in an overnight series (method 1 = page sets, covered in Pass 1).

**Relevance to RSHelper:** Confirms the overnight lane should prefer high-volume items where unattended offers reliably fill, rather than high-margin low-volume items that may not trade.

---

### How I Used 6 Accounts to Make 7M+ in Under One Hour

**URL:** https://www.ge-tracker.com/guides/view/how-i-used-6-accounts-to-make-7m-in-under-one-hour-with-no-skill-requirements

**Category:** Multi-Account

**Key claim/strategy:** When an exceptional margin appears, scaling across many accounts multiplies the capture before the window closes.

**Supporting detail:**
- "I've never multilogged like this, but once I saw these margins I knew I had to."
- 6 accounts, 7M+ in under one hour, no skill requirements.

**Relevance to RSHelper:** Multi-account scaling in RSHelper should be margin-triggered: exceptional spreads justify spinning up additional account capacity, normal spreads do not.

---

### How to Casually Merch and Make 2M in ~1 Hour While Skilling/Slaying

**URL:** https://www.ge-tracker.com/guides/view/how-to-casually-merch-and-make-2m-in-a-little-over-1-hour-while-skilling-slaying

**Category:** Flipping Strategy

**Key claim/strategy:** Passive merching runs in the background of other play: leave offers in slow, good-margin items instead of actively camping the GE.

**Supporting detail:**
- "Many of these items don't require you to constantly be at the GE waiting and changing price offers."
- "Many of these methods allow for good time/gp methods that can not be done in high volume at one time" — slow lanes deliberately accepted.

**Relevance to RSHelper:** Supports a background/passive strategy tier in RSHelper where offer maintenance cost is near zero and slow fills are acceptable — distinct from the active flip loop.

---

### How to Not Waste Your G.E. Slots

**URL:** https://www.ge-tracker.com/guides/view/how-to-not-waste-your-g-e-slots-easy-ways-to-make-money-with-the-grand-exchange

**Category:** Flipping Strategy

**Key claim/strategy:** Idle GE slots are lost profit; all 8 slots should always be working.

**Supporting detail:**
- "Too many people don't utilize their G.E. slots... ya'll are losing out on mad profits."

**Relevance to RSHelper:** RSHelper should track slot utilization as a first-class metric and always have candidate offers queued for empty slots, even at lower expected margins.

---

### Invest Now Before Dragon Slayer 2 Comes Out / Top 5 Dragon Slayer 2 Investments

**URL:** https://www.ge-tracker.com/guides/view/invest-now-before-dragon-slayer-2-comes-out-market-analysis-for-dragon-slayer-2-osrs and https://www.ge-tracker.com/guides/view/top-5-dragon-slayer-2-investments

**Category:** Investment Timing

**Key claim/strategy:** Pre-position in items a major update will affect, because the update reprices both winners (spike) and losers (crash).

**Supporting detail:**
- "The new Dragon Slayer 2 update will cause some items to spike in price, and some items to crash."
- "When new content comes out it is a great chance to make money... You just gotta get in before everyone else!"

**Relevance to RSHelper:** Update watchlists in RSHelper should map announced content to affected item lists ahead of release, with entry timed before the crowd, not on release day.

---

### Old School Mobile Is Coming — What to Invest In

**URL:** https://www.ge-tracker.com/guides/view/old-school-mobile-is-coming-here-is-what-you-need-to-invest-in

**Category:** Investment Timing

**Key claim/strategy:** Platform-level releases (OSRS Mobile) create tradeable hype cycles before launch, including around the beta.

**Supporting detail:**
- "You want to invest soon because while mobile may not be released for a while, there will be a ton of hype around the beta as well that you can capitalize."

**Relevance to RSHelper:** Event signals should include platform/release milestones and their betas, not just in-game content patches; hype itself is a tradeable wave with an earlier entry point.

---

### Why Are Bonds Skyrocketing? — November Market Analysis

**URL:** https://www.ge-tracker.com/guides/view/why-are-bonds-skyrocketing-in-price-november-market-analysis-for-oldschool-runescape-osrs

**Category:** Market Mechanics

**Key claim/strategy:** Monthly market reviews using index-level data and update-affected items reveal macro trends invisible at single-item level.

**Supporting detail:**
- Reviews general item trends via the GE Tracker index page plus update-affected items: Ahrim's staff, serpentine helm, bandos godsword.
- Bond price inflation explained via demand-side reasoning.

**Relevance to RSHelper:** A market-index feature (basket of items tracked as one line) would let RSHelper detect market-wide inflation/deflation regimes and adjust strategy aggressiveness accordingly.

---

### OSRS Talk About F2P Market — What to Flip in F2P

**URL:** https://www.ge-tracker.com/guides/view/osrs-talk-about-f2p-market-what-to-flip-in-f2p

**Category:** Category Specialization

**Key claim/strategy:** The F2P flippable universe is small and known: ores, runes, bars, logs, plus gilded items for margin.

**Supporting detail:**
- "Items to flip in F2P: Ores, runes, bars, logs. Gilded armour/weapons."

**Relevance to RSHelper:** RSHelper's F2P mode can ship with a curated default watchlist (ores, runes, bars, logs, gilded armor/weapons) instead of scanning the full item set.

---

### GE Tracker Feature Set (from three tool-showcase guides)

**URL:** https://www.ge-tracker.com/guides/view/osrs-the-ultimate-tool-for-flipping-in-runescape-track-profits-g-e-limits-suggested-items (plus /osrs-how-to-search-for-profitable-items-to-flip-with-ge-tracker-a-guide-to-using-search-filters and /flip-finders-tools-high-alch-calculator-and-money-making-a-complete-guide-to-ge-tracker-osrs)

**Category:** Tool Usage

**Key claim/strategy:** GE Tracker's feature list is the competitive baseline for flipping tooling — RSHelper should match or exceed it.

**Supporting detail:**
- Free tier: 3 favourite items, price graphs, buy/sell quantity graphs, basic profit tracker, 5 suggested profitable items every 10 minutes (no refreshes), public merchanting logs, high volume items list.
- Premium tier: unlimited favourites, full profit tracker with drag-and-drop active transactions, most profitable items view, GE limit profit view, custom price alerts (desktop/email/SMS), 50 suggested items with infinite refreshes, recently added items, OSBuddy import, item sets & crafting, profitable Karamja store, decant potions, high alchemy calculator, herblore for profit (cleaning, unf. pots, full pots).
- Search filters "help filter down unique items that other people will not be seeing"; F2P-only mode toggle exists.

**Relevance to RSHelper:** Direct feature checklist for RSHelper: suggested-items refresh cadence, price alerts, profit tracking with active transactions, buy-limit-aware profit view, and the processing-arbitrage calculators (decant, alch, herblore) are all table stakes.

---

### Video-only or near-empty pages (checked and skipped)

The following requested key articles and scanned guides were fetched and contained only video embeds or 1-3 sentences with no extractable strategy:

- https://www.ge-tracker.com/guides/view/easiest-money-i-ll-ever-make-osrs-flipping-1-100m-3-ge-tracker — video only, no text content
- https://www.ge-tracker.com/guides/view/i-kept-this-method-a-secret-for-over-a-year-10m-per-day-in-20-minutes — video only, method never described in text
- https://www.ge-tracker.com/guides/view/advanced-osrs-flipping-guide-how-to-make-bills — video only
- https://www.ge-tracker.com/guides/view/best-osrs-grand-exchange-flipping-merching-guide-updated-2015 — video only (links dead site lets-flip.com)
- https://www.ge-tracker.com/guides/view/how-to-flip-merch-3rd-age-old-school-runescape — video only
- https://www.ge-tracker.com/guides/view/osrs-how-to-succeed-at-flipping-in-runescape-a-beginner-flipping-guide-2016 — video outline only (what is flipping, finding margins, picking items)
- https://www.ge-tracker.com/guides/view/osrs-flipping-merching-a-complete-guide-to-flipping-for-beginners-part-one — video only
- https://www.ge-tracker.com/guides/view/how-to-find-good-margins-for-flipping-and-examples — one-liner: examples of merches at different bank-value tiers, finding obscure items
- https://www.ge-tracker.com/guides/view/osrs-alching-for-profit — video only (three methods listed with profits 1k/50k/70k, methods not described)
- https://www.ge-tracker.com/guides/view/osrs-flipping-merching-overview-of-suggested-items-tool — video only
- https://www.ge-tracker.com/guides/view/osrs-flipping-merching-profit-from-collections — video only
- https://www.ge-tracker.com/guides/view/market-talk-why-isn-t-the-bgs-10m-bgs-vs-dwh-ags — video only (comparative valuation BGS vs DWH vs AGS)
- https://www.ge-tracker.com/guides/view/top-10-grand-exchange-tips-and-tricks-ep-1-osrs — video only (10 tips promised, none in text)
- https://www.ge-tracker.com/guides/view/my-top-10-flips-of-all-time-a-look-back-at-my-highest-margin-flips-osrs — video only; notes he never used more than a 100m stack
- https://www.ge-tracker.com/guides/view/osrs-how-i-lost-500-000-usd-on-my-biggest-failed-flip-7500-subscriber-milestone — story is about early Bitcoin, not GE flipping
- All ~200 episode-log entries ("1 hour flipping challenge" #1-31, "Worthless to Wall Street" #1-17, "0-100m P2P" #1-22, "F2P 0gp to bond" #1-8, "1-100m Road to Bank" #1-36, "Flipping to Billions" #1-5, "Grand Exchange Only" #1-11, etc.) — video logs with rules recaps (starting cash, time limit, category) but no transferable strategy text. Common structure observed: 10-50m starting cash, 1-hour limit, category-restricted item pools.

---

## Pass 2 — Dimension Updates

Additions to the Research Dimensions Summary above from pass-2 sources:

### GP/hr formulas (additions)
- Unfinished potions: `(unf potion price - clean herb price - vial price - tax) * combines per hour`; cited at 600k/hour
- Barrows repair: `repaired price - broken price - repair cost - tax`

### Tool/scoring model (new, from gemargin.com/flip-finder)
- Composite item rating out of 10 plus stability grade A-F and confidence flag per item
- Core columns: Margin, ROI %, Volume, Buy Limit, GP/hr, Potential profit, Capital Efficiency, Lock-up time (e.g. 4hr = buy-limit reset window)
- Mode split: Quick Flips vs Patient Flips vs Overnight — maps to fill-speed vs margin tradeoff
- Low-volume items show triple-digit ROI% (e.g. 146%, 588%) with F stability grades — ROI% alone must be discounted by stability/volume

### Alchemy mechanics (additions)
- Cast time 3 seconds (oldschool.tools) — consistent with 5-tick/1,200 casts per hour figure
- ~78k Magic XP/hour at max cast rate
- Dual price sourcing: official GE guide prices with RuneLite price fallback

### Investment timing (additions)
- Content-release crashes hit *unrelated* prestige items too (3rd age sold to fund raids gear) — cross-category liquidation signal
- Hype waves begin at beta/announcement, before release day ("get in before everyone else")

### Capital efficiency (additions)
- Sub-1m: cheap clue scroll items preferred (massive margin-to-price ratio)
- Category ladder: viable item universe is a function of bankroll; re-rank as capital compounds

### Multi-account (additions)
- Margin-triggered scaling: 6 accounts spun up specifically because exceptional margins appeared (7M+/hour capture)

### GP/hr formulas
- Alch: `Alch Value - Buy Price - Nature Rune Cost = Profit per cast`, then `Profit * min(1200, buy_limit/4)` for hourly
- Flip: `Margin per flip * flips per hour` (limited by buy limits and offer fill time)
- ML baseline: `(roi_zscore + volume_ratio_zscore)` sorted descending

### Volume thresholds
- High volume: 500,000+ traded/day (safest, thinnest margins)
- Average volume: moderate trading (gray area, margin check cautiously)
- Low volume: <100/day (avoid unless rare/new items with demand)
- Super rare: <100/day, requires days of patience

### Buy limit mechanics
- 4-hour cycles per item, different limits per item
- Coal: 13,000; Dragon items: 70; Rune items: 70-125; Battlestaves: 18,000
- Max alch profit uses `min(buy_limit, 4800)` (4800 = 1200 casts * 4 hours)

### GE tax effects
- 1% tax on sell offers for items >100 GP (wiki says 1%, some sources say 2%)
- Capped at 5M per offer
- Applied per-item, rounded down
- Formula: `math.floor(0.01 * price) * quantity`

### Margin checking
- Safe for high volume items (runes, logs, food)
- Risky for average volume (can be manipulated)
- Dangerous for low volume (one-off margins, not sustainable)
- Use charts for average/low volume instead of in-game checks

### Risk classification
- High volume = low risk, thin margins
- Average volume = medium risk, moderate margins
- Low volume = high risk, big margins but hard to exit
- New items = highest risk, highest reward
- Bubbles = avoid at all costs

### Market timing
- Buy before dev blogs when community + JMod support is strong
- NEVER invest days before an update (players dump on release)
- New items: most volatile, most profitable
- Overnight: place buy offers below market for bot dump recovery

### Item categories
- Runes, logs, food, potions, ore, bars = high volume staples
- Barrows, whips, ranger boots = average volume
- 3rd age, clue rewards, cosmetics = low volume, high margin
- Boss drops = category-specific opportunities
- Sets (armor, pages) = set arbitrage opportunities

### Trader psychology
- Beginners quit after losses; first experience determines retention
- Average merchants = herd, responsible for crashes and spikes
- Masterminds = patient, informed, comfortable with risk
- Bad habits: impatience, rushing margin checks, overcommitting

### Multi-account strategies
- 5 accounts = 40 GE slots, 150m total capital
- 100 accounts = 800 GE slots, 3m/account minimum
- Items must sell fast enough to cycle capital
- Rune essence example: too slow, creates bottlenecks

### Alchemy mechanics
- 55 Magic required, 65 XP per cast, 5-tick speed
- 1,200 casts/hour max
- 197,967 casts for 55->99
- Explorer's Ring: 30 free/day
- Fountain of Rune: free, no XP, PK risk
- Staff of Fire: eliminates fire rune cost

### Processing arbitrage
- Decanting: buy multi-dose potions, decant to 4-dose
- Herb cleaning: buy grimy, clean for profit + XP
- Set combining: buy pieces, combine into sets
- Page combining: buy pages 1-4, combine into sets
- Barrows repair: buy broken, repair for profit

### Bot dumps and market panics
- Exploitable during off-peak hours (2-6 AM game time)
- Distinguish panic from fundamental value decline
- Buy during panic, sell during recovery
- 24-hour price history essential for detection

### Overnight strategies
- Page set combining (10-30m start)
- Armor set combining (F2P viable)
- Buy offers below market for overnight completion
- Leave offers in while sleeping

### Capital efficiency
- 1m F2P: viable starting point, focus on volume
- 7m: sufficient for Barrows sets
- 20m: good for most traded items
- 30m per account: multi-account minimum
- 100m: high-volume rares become viable
- 500m: expensive items with thin absolute margins

### Chart patterns
- Candlestick: hollow=sell pressure, solid=buy pressure
- Long-term moving average: trend direction indicator
- Bubble detection: historic high with no fundamental cause
- Volume analysis: buy/sell ratio from GE Tracker

### Game update effects
- New items: most volatile period, biggest margins
- Item dumps: existing best-in-slot items crash when replaced
- DWH case study: crash then recovery based on discovered utility
- Raids: increased demand for all combat style gear
