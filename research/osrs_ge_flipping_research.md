# OSRS Grand Exchange Flipping Research — RSHelper Actionable Insights

> **TAX CORRECTION (2026-07-31):** The GE tax is **2%** on sells, capped at
> 5M per item, since the 29 May 2025 update (OSRS Wiki). The "1%" lines in
> this file predate that change and are stale. RSHelper's code uses 2%
> everywhere. Do not trust the 1% claims below.

**Research date:** 2026-07-26
**Sources:** 30+ ge-tracker.com articles, OSRS Wiki, gemargin.com, 07flip.com, osrs-alchemy.com, tristanrhodes.com
**Agents used:** 5 parallel research agents fetching 40+ URLs

---

## PART 1: KEY ALGORITHMIC / FORMULA FINDINGS

### GP/hr Formula for Flipping (from gemargin.com flip-finder)
```
GP/hr = margin × min(buy_limit, daily_volume) / 4
```
- `margin` = sell_price - buy_price (after 2% GE tax on sell)
- `buy_limit` = 4-hour cycle limit per item
- `daily_volume` = total units traded per day
- Divide by 4 because the cycle is 4 hours
- GE tax: 2% on sell, capped at 5M GP per transaction

### Confidence Score Formula (from 07flip.com)
```
confidence = 0.4×volume + 0.3×volatility + 0.2×spread + 0.1×freshness
```
- Higher = more reliable flip opportunity
- All profit calculations include 2% GE tax (capped at 5M)

### GE Tax Formula (from Tristan Rhodes / OSRS Wiki)
```
tax = floor(0.01 × price) × quantity
```
- 1% on sells over 100 GP (note: some sources say 2% — wiki says 1%)
- Capped at 5M GP per transaction
- Tax-exempt items: bonds

### Alchemy Profit Formula (from gemargin.com + OSRS Wiki)
```
profit = alch_value - buy_price - nature_rune_cost
```
- Nature rune cost: ~147-149 GP (varies by source date)
- Cast rate: ~1,200 casts/hr (5 ticks = 3 seconds per cast)
- XP/hr: ~78k (65 XP per cast)
- Staff of Fire saves ~20-30 GP/cast
- Bryophyta's staff + Tome of fire = 137 GP/cast total

### Volume-Adjusted Alch Profit (from OSRS Wiki Market Watch)
```
max_profit = profit × min(buy_limit, 4800)
# BUT if volume < 6× limit AND volume < 28,800:
max_profit = profit × (volume / 6)
```

---

## PART 2: VOLUME THRESHOLDS & RISK CLASSIFICATION

### High Volume (Low Risk)
- **Threshold:** ≥500,000 units traded per day
- Examples: coal, gold bar, lobster, astral rune, rune essence
- Safest for margin checks; very small chance of losing money
- Margin checks are reliable (prices move slowly)

### Average Volume (Medium Risk)
- Examples: abyssal whip, ranger boots, Dharok's platebody
- Borderline for margin checks; margins can be manipulated
- Requires more careful margin testing

### Low Volume (High Risk)
- Examples: hunter's potion, slayer's respite, dragon bitter
- Only for experienced merchants
- Low-volume items with no use = avoid entirely
- Exceptions: rare items with demand (twisted bow, 3rd age sets, elysian spirit shield)

### Super Rare (<100 trades/day)
- Requires 10-20M+ capital minimum
- Flips can take days to complete
- Scored differently than standard flips — patience-weighted ROI

---

## PART 3: ITEM-SPECIFIC STRATEGIES

### Core PvM Flipping List (from "15-20M/day" guide)
Default high-volume, stable-margin items:
- Blowpipe, serp helm, toxic staff, fury, berserker ring, archer ring
- BGS, DFS, amulet of torture, anguish neck
- Consistent demand from bossing/PvM community
- Expected: 15-20M/day with ~2-3 hours active flipping

### Set Arbitrage Items
- Barrows equipment sets (buy individual pieces → sell complete set)
- God page sets (page 1+2+3+4 → complete god book)
- F2P armor sets: Green d'hide set, Saradomin rune armor set
- Minimum capital: 7-30M GP depending on set tier

### High-Alchemy Best Items (from gemargin.com)
- Amulet of the damned full: 2.7k GP/cast
- Runite crossbow (u): 574.8k GP/hr (10,000 buy limit)
- Onyx bolts (e): 556.8k GP/hr (11,000 buy limit)
- 148 currently profitable alch items

### Top Alch Items by Max Profit (from OSRS Wiki)
- Dragon platelegs: 55,020 per cycle
- Rune halberd: 53,620 per cycle
- Red d'hide body: 53,270 per cycle

### 3rd Age / Rare Items
- Crash during major content releases (players liquidate to fund new gear)
- Recovery play: buy during panic, sell during recovery
- Very wide spreads, very high capital requirements
- Extreme risk / extreme reward

### New Item Launch Items (Day 1-2)
- Dragon sword, dragon harpoon, dragon thrownaxe
- Ancestral hat, dragon hunter crossbow, twisted buckler, dinh's bulwark
- Requires 50M+ starting capital
- Extreme volatility; prices still settling

---

## PART 4: PROCESSING ARBITRAGE

### Potion Decanting
- Buy 1/2/3-dose potions → decant via NPC → sell as 4-dose
- Always in demand (combat + skilling potions)
- Low-risk, consistent earner
- Great "filler" activity while other flips pending

### Herb Cleaning
- Buy grimy herbs → clean into clean herbs
- Dual benefit: GP profit + Herblore XP
- Consistent demand from PvMers and skillers

### Page Set Assembly
- Buy individual god pages (1, 2, 3, 4) → combine into complete set
- Set premium over sum of individual pieces
- Works overnight (leave buy offers)

### Barrows Repair
- Buy degraded Barrows armor → repair → sell at premium
- Combined with set arbitrage for higher margins

---

## PART 5: CAPITAL EFFICIENCY & PROGRESSION

### Capital Tiers (from multiple guides)
| Tier | Capital | Recommended Items | Expected GP/hr |
|------|---------|-------------------|----------------|
| Beginner | 1-10M | High-volume runes, food, ore | 100-500k |
| Intermediate | 10-30M | PvM gear, potions, sets | 500k-2M |
| Advanced | 30-100M | Barrows sets, high-tier PvM | 2-5M |
| Expert | 100-500M | Rare items, overnight flips | 5-15M |
| Master | 500M+ | 3rd age, raid drops, new releases | 15M+ (high variance) |

### Key Insight: Capital Efficiency Curves
- More capital ≠ linearly better returns
- At 500M+, GE tax on expensive items (1% on >5M) significantly eats margins
- Optimal strategy shifts from "more items" to "better items" as capital grows
- RSHelper should calculate GP/hr efficiency curves across capital tiers

### Multi-Account Scaling
- 5 accounts × 30M each = 150M total → 5M+/hr achievable
- 100 accounts tested; capital management is the binding constraint
- Minimum 3M per account for functional flipping
- Sell-through speed matters more than margin at scale
- Items that fill slowly become bottlenecks (e.g., rune essence removed from 100-account roster)

---

## PART 6: MARKET TIMING & EVENTS

### Game Update Effects
- No item sinks exist → items devalue over time if player base doesn't grow
- New items are most volatile and most profitable to flip early
- DWH example: released ~70m → crashed to 40m → surged when BIS discovered for corp
- Players dump luxury items (3rd Age) to fund new content

### Investment Timing Rule
- Invest when community + JMods strongly back an idea BUT BEFORE dev blog drops
- Never invest 1-3 days before an update — players dump on release day
- Day-of-release flipping is extremely high-variance

### Bot Dump Detection
- Sudden volume + price drops indicate bot dumping
- Price depression reverses; buying during dump window yields recovery profit
- Requires 24h price history analysis

### Overnight Strategies
- Place offers before bed, complete by morning
- Items with predictable 24h price patterns are best targets
- Can start with any capital amount
- Page sets and armor sets work well overnight

---

## PART 7: TRADER PSYCHOLOGY & BAD HABITS

### Common Mistakes (from "Top 10 Bad Habits" guide)
- Rushing under time pressure
- Over-leveraging on single items
- Not checking margins before trading
- Panic selling during dips
- Ignoring GE tax in profit calculations
- Habits form through repetition, not single events

### Trader Skill Tiers (from "Benefits Complete Guide")
- **Beginners:** Uncreative, mimic others, quit easily after first loss
- **Average:** Flip common Barrows/PvM drops, herd behavior, emotional
- **Masterminds:** 500M-2B+ profit, long-term planners, read dev blogs/Q&As, hold investments for months

### Risk Management Rule
- Designate fixed % of earnings for reinvestment
- Separate "flipping capital" from "spendable GP"
- If you invest 50% of earnings, by 100M spendable you should have 100M in GE
- Reduces emotional stress on individual flip outcomes

### Method Freshness / Decay
- When a strategy gets shared publicly, margins shrink over time
- "Secret" methods that stay private maintain margins longer
- RSHelper should track when strategies were last shared publicly

---

## PART 8: TOOL & FEATURE RECOMMENDATIONS FOR RSHELPER

### Must-Have Features (derived from research)
1. **Volume-tiered risk scoring** — classify items as high/avg/low/ultra-low volume with risk ratings
2. **GP/hr calculator** — `margin × min(limit, volume) / 4` with GE tax factored in
3. **Set arbitrage scanner** — detect component-vs-set price gaps across all item families
4. **Potion decanting profit calculator** — compare 1/2/3-dose buy prices vs 4-dose sell prices
5. **Alchemy profit module** — formula: `alch_value - buy_price - nature_rune`, cast rate 1200/hr
6. **Overnight flip mode** — items with reliable 24h patterns, one-click offer setup guidance
7. **Game update event detector** — flag upcoming updates, track newly released items
8. **Bot dump detection** — sudden volume/price drops = potential buy opportunity
9. **Capital-progression framework** — recommend items based on current bank value tier
10. **Portfolio allocator** — track invested vs liquid GP, prevent over-exposure

### Advanced Features
11. **Confidence scoring** — 0.4×volume + 0.3×volatility + 0.2×spread + 0.1×freshness
12. **F2P dedicated mode** — filtered item pool for free-to-play
13. **Multi-account capital planner** — allocate capital across accounts
14. **Margin-check safety rating** — high volume = safe, low volume = risky
15. **Historical price-cycle recognition** — rise/fall patterns of raid-tier items
16. **New item launch mode** — real-time tracking for items <48h old
17. **Herd vs independent signal** — items where mass sentiment diverges from fundamentals
18. **Method freshness decay score** — how recently a strategy was publicized
19. **Flip audit / habit tracker** — log common mistakes
20. **Alchemy session planner** — bankroll-aware, time-constrained composite scoring

### Data Pipeline Recommendations (from Tristan Rhodes algorithmic trading)
- Poll OSRS Wiki real-time prices every 5 min + hourly
- Record price spreads, volumes, buy limits
- Trade log: gold/sec, absolute profit, timestamp, item ID
- Training: 63-day lookback, 14-day validation (prevents temporal leakage)
- Random forest outperformed neural net for GE market-making (73% better than heuristic baseline)
- Optimization target: gold/second (not margin %)

---

## PART 9: ALCHABLE ITEM DATABASES

### Sources with item data
- osrs-alchemy.com: 1,740 alchable items, bankroll-aware calculator
- oldschool.tools/calculators/alchemy: 1,740 items, GE + RuneLite prices
- flipping.gg/highlights/profitable-alchs: JS-rendered, not scrapable
- OSRS Wiki Market Watch/Alchemy: comprehensive live table

### Alchemy Cost Tiers
| Equipment | Cost per cast |
|-----------|--------------|
| Bare (no staff) | 172 GP |
| Staff of Fire | 147 GP |
| Bryophyta's staff + Tome of fire | 137 GP |
| Explorer's Ring 4 | Free (30/day) |

---

## PART 10: SKIPPED / LOW-VALUE SOURCES

- **flipping.gg** — JS-rendered, no content extractable
- **Many ge-tracker video-only articles** — tactical detail in YouTube embeds, not written text
- **ge-tracker listing pages (1-41)** — mostly video embeds with brief descriptions
- **"Flipping to Billions" series** — video-first, minimal written content
- **"Flipping Everything W/ 10M"** — video challenge, no written methodology

---

*Research compiled by 5 parallel agents. Total URLs attempted: ~50. Substantive content extracted from ~30 sources.*
