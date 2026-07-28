import re, os, glob, html

# credit labels: remove whole line if it (case-insensitive) matches one of these
CREDIT_LABELS = [
    r"OSRS best merching tool:?",
    r"Discord:?",
    r"Subreddit:?",
    r"GT Forums:?",
    r"Clan chat:?",
    r"Our friends channels:?",
    r"Ge Tracker Twitter:?",
    r"My Twitter:?",
    r"Twitter:?",
    r"Buy Merchandise to Support the Channel:?",
    r"Grand Exchange Tracker",
    r"Support me on Patreon",
    r"Support the Author",
    r"View Author on YouTube",
    r"View on YouTube",
    r"Thank you for watching",
    r"Follow me on \w+",
    r"Check out my \w+",
    r"Subscribe (to )?((my )?channel|for more)",
    r"https?://\S+",                      # bare URL lines
    r"^\w[\w ]{0,30}:\s*$",                # short "label:" lines (channel names under friends channels)
]
CREDIT_RE = re.compile("|".join("(?:%s)" % p for p in CREDIT_LABELS), re.I)

URL_RE = re.compile(r"https?://\S+")
files = glob.glob("raw/articles/*.html")
rows = []
for f in files:
    h = open(f, encoding="utf-8", errors="replace").read()
    mtitle = re.search(r"<title>(.*?)</title>", h, re.S)
    title = html.unescape(mtitle.group(1).strip()) if mtitle else os.path.basename(f)
    title = re.sub(r"\s*-\s*GE Tracker\s*$", "", title).strip()
    mdate = re.search(r"\[(\d{2}/\d{2}/\d{4})\]", h)
    date = mdate.group(1) if mdate else ""
    start = -1
    mo = re.search(r'class="video-guide-description">', h)
    if mo:
        start = mo.end()
    else:
        mo = re.search(r'class="main-content">', h)
        if mo: start = mo.end()
    end = h.find('class="section related-guides"', start if start > 0 else 0)
    if end < 0: end = len(h)
    body = h[start:end] if start > 0 else ""
    # to text
    body = re.sub(r"<script.*?</script>", " ", body, flags=re.S)
    body = re.sub(r"<style.*?</style>", " ", body, flags=re.S)
    body = re.sub(r"<br\s*/?>", "\n", body)
    body = re.sub(r"</li>", "\n", body)
    body = re.sub(r"<li[^>]*>", "- ", body)
    body = re.sub(r"</p>", "\n", body)
    body = re.sub(r"<p[^>]*>", "\n", body)
    body = re.sub(r"</?(h[1-6]|div|span|ul|ol|a|strong|b|i|em|section|article|img)[^>]*>", "\n", body)
    body = re.sub(r"<[^>]+>", " ", body)
    body = html.unescape(body)
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in body.split("\n")]
    # remove credit/url/label lines
    kept = []
    for ln in lines:
        if not ln: continue
        if URL_RE.search(ln) and len(URL_RE.search(ln).group(0)) > len(ln) - 5:
            # line is essentially just a URL
            continue
        if CREDIT_RE.fullmatch(ln):
            continue
        if CREDIT_RE.search(ln) and len(ln) < 45:
            continue
        kept.append(ln)
    text = "\n".join(kept)
    slug = os.path.basename(f).replace("www.ge-tracker.com_guides_view_", "").replace(".html", "")
    open(f"text/{slug}.txt", "w", encoding="utf-8").write(text)
    rows.append((slug, date, len(text), title))

rows.sort(key=lambda r: -r[2])
with open("manifest.tsv", "w", encoding="utf-8") as out:
    out.write("slug\tdate\tlen\ttitle\n")
    for slug, date, ln, title in rows:
        out.write(f"{slug}\t{date}\t{ln}\t{title}\n")
# counts
empty = [r for r in rows if r[2] < 80]
print(f"parsed={len(rows)}  flagged_video_only(<80 chars)={len(empty)}")
print("top 15 by length:")
for slug, date, ln, title in rows[:15]:
    print(f"  {ln:6} {date} {title[:70]}")
print("\nfirst 15 video-only:")
for slug, date, ln, title in rows[-15:]:
    print(f"  {ln:4} {date} {title[:70]}")
