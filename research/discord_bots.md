# OSRS Flipping/Trading Discord Bot Research
*Researched: 2026-07-27*

## Active Commercial/SaaS Services

### 1. flipping.gg
- **URL:** https://flipping.gg
- **Discord:** `discord.gg/Y4mabAWSGk`
- **What it does:** OSRS flipping web app with integrated Discord bot. Active and live.
- **Tech stack:** Nuxt.js + PrimeVue
- **Status:** ✅ ACTIVE (confirmed 2026-07-27)

### 2. GE-Tracker (ge-tracker.com)
- **URL:** https://www.ge-tracker.com
- **Discord:** `discord.gg/AhHfkW8`
- **What it does:** Commercial OSRS GE tracking/flipping service. Offers market watch dashboard, price tracking, Discord integration, and features like price alerts.
- **Status:** ✅ ACTIVE (confirmed 2026-07-27)

### 3. Flipping Utilities (RuneLite Plugin + Discord)
- **URL:** RuneLite Plugin Hub (Flipping Utilities)
- **Discord:** `discord.gg/fu`
- **What it does:** Popular RuneLite plugin for flipping with a large Discord community. Tracks flip history, margins, ROI. The Discord serves as a community hub.
- **Status:** ✅ ACTIVE (confirmed 2026-07-27)

### 4. PlatinumTokens
- **URL:** https://platinumtokens.com
- **Discord:** Unknown
- **What it does:** Previously a commercial OSRS flipping service. 
- **Status:** ❌ POSSIBLY DEFUNCT (HTTP 525 SSL error, 2026-07-27)

---

## Open-Source Discord Bots (GitHub)

### Major / Popular

#### 5. Old School Bot (oldschoolgg/oldschoolbot)
- **GitHub:** https://github.com/oldschoolgg/oldschoolbot
- **Invite:** https://invite.oldschool.gg/
- **Website:** https://www.oldschool.gg/oldschoolbot
- **Stars:** 155 | **Forks:** 149 | **Issues:** 397
- **What it does:** Comprehensive fan-made OSRS Discord bot covering skills, monster killing, clues, hiscores, world checking, minigames. Uses oldschooljs for OSRS features.
- **Tech stack:** TypeScript, MIT license
- **Status:** ✅ VERY ACTIVE (last updated 2026-07-26)

### Dedicated Flipping/GE Bots

#### 6. OSRS-Flipping-Discord-Bot (UZ9/OSRS-Flipping-Discord-Bot)
- **GitHub:** https://github.com/UZ9/OSRS-Flipping-Discord-Bot
- **Stars:** 2
- **What it does:** Dedicated OSRS flipping Discord bot. Commands: `lookup` (item lookup with GE margins), `flips` (query items by margin/price/members), `savedflips` (personal flip tracking), `addflip`/`removeflip`, `stats` (hiscores), `xptolevel`
- **Tech stack:** Node.js
- **Status:** Active-ish (updated 2025-07-27, TODO items remain)

#### 7. osrsmarketscanner (xines/osrsmarketscanner)
- **GitHub:** https://github.com/xines/osrsmarketscanner
- **Stars:** 1
- **What it does:** Discord bot with GE lookup (`!ge item name`) and market scan showing current margins. Feeds database over time for accuracy.
- **Tech stack:** Go (discordgo + objectbox)
- **Status:** ✅ ACTIVE (last updated 2026-07-15)

#### 8. osrs-ge-bot (mini-gromit/osrs-ge-bot)
- **GitHub:** https://github.com/mini-gromit/osrs-ge-bot
- **Stars:** 1
- **What it does:** Tracks OSRS Grand Exchange flipping and high alchemy opportunities. Sends alerts to configured Discord channels. Has standalone CLI (`ge_tracker.py`) for analysis without Discord.
- **Tech stack:** Python 3.13.5
- **Status:** ✅ ACTIVE (last updated 2026-07-21, currently refactoring to modular structure)

### Smaller / Less Active Projects

#### 9. osrs-ge-discord-alerts (NCG-RS/osrs-ge-discord-alerts)
- **GitHub:** https://github.com/NCG-RS/osrs-ge-discord-alerts
- **Stars:** 0
- **What it does:** Discord bot sending price alerts for configured items at user-set thresholds.
- **Status:** Less active (updated 2026-01-10)

#### 10. OSCompanionBot (codyorr/OSCompanionBot)
- **GitHub:** https://github.com/codyorr/OSCompanionBot
- **Stars:** 0
- **What it does:** Discord bot for OSRS Grand Exchange.
- **Status:** Less active (updated 2026-02-28)

#### 11. osrs-dump-scanner (SymphonicTone/osrs-dump-scanner)
- **GitHub:** https://github.com/SymphonicTone/osrs-dump-scanner
- **Stars:** 0
- **What it does:** Discord bot finding "dump" items on the GE (items being sold off rapidly at low prices) and posting to Discord channel.
- **Status:** Somewhat active (updated 2026-06-17)

#### 12. python-rspricebot (svescuso/python-rspricebot)
- **GitHub:** https://github.com/svescuso/python-rspricebot
- **Stars:** 0
- **What it does:** RuneScape Grand Exchange item price bot using web scraping (BeautifulSoup) and RS API.
- **Tech stack:** Python
- **Status:** Older / inactive

#### 13. GE-Tracker (ElwinCoding/GE-Tracker)
- **GitHub:** https://github.com/ElwinCoding/GE-Tracker
- **Stars:** 1
- **What it does:** Discord bot tracking OSRS GE.
- **Status:** Unknown activity

#### 14. flipping-tracker (GilliCode/flipping-tracker)
- **GitHub:** https://github.com/GilliCode/flipping-tracker
- **Stars:** 0
- **What it does:** JSON editor for Flipping Utilities plugin data. Not a Discord bot itself, but a companion tool for the Flipping Utilities ecosystem.
- **Tech stack:** React, TypeScript

---

## Related Ecosystem Projects (Not Discord Bots)

### Wise Old Man (wise-old-man/wise-old-man)
- **GitHub:** https://github.com/wise-old-man/wise-old-man
- **Stars:** 349
- **What it does:** Open source OSRS progress tracker with web app + API. Tracks player/group progress.
- **Has Discord integration:** Not a Discord bot per se, but some groups use it alongside Discord.
- **Status:** ✅ VERY ACTIVE (updated 2026-07-26)

### OSRSBox Database (osrsbox/osrsbox-db)
- **GitHub:** https://github.com/osrsbox/osrsbox-db
- **Stars:** 242
- **What it does:** Complete up-to-date database of OSRS items, monsters, prayers. Used as data source by many bots/tools.
- **Status:** ✅ ACTIVE

---

## Key Findings Summary

| Bot/Service | Type | Active? | Source |
|---|---|---|---|
| flipping.gg | Commercial + Discord bot | ✅ Yes | Live site |
| GE-Tracker | Commercial + Discord bot | ✅ Yes | Live site |
| Flipping Utilities | RuneLite Plugin + Discord | ✅ Yes | Discord invite live |
| PlatinumTokens | Commercial | ❌ Likely dead | SSL error |
| Old School Bot | Open-source Discord bot | ✅ Yes (155 stars) | GitHub |
| OSRS-Flipping-Discord-Bot | Open-source Discord bot | ⚠️ Moderate | GitHub |
| osrsmarketscanner | Open-source Discord bot | ✅ Yes | GitHub |
| osrs-ge-bot | Open-source Discord bot | ✅ Yes | GitHub |
| osrs-ge-discord-alerts | Open-source Discord bot | ⚠️ Low | GitHub |
| OSCompanionBot | Open-source Discord bot | ⚠️ Low | GitHub |
| osrs-dump-scanner | Open-source Discord bot | ⚠️ Moderate | GitHub |

### Gaps for RSHelper

The existing bots fall into two categories:
1. **Commercial services** (flipping.gg, GE-Tracker) — Closed source, premium features likely behind paywalls
2. **Open-source bots** — Small projects (0-2 stars), limited feature sets, some abandoned

The **Old School Bot** (oldschoolgg/oldschoolbot) is the only large open-source OSRS Discord bot at 155 stars, but it's a general OSRS bot, not specifically focused on GE flipping/trading.

**Opportunity:** There is no mature, well-maintained open-source Discord bot specifically for OSRS Grand Exchange flipping with price alerts, margin tracking, and trade history. An RSHelper Discord bot could fill this gap.
