#!/usr/bin/env python3
"""Bulk extract YouTube auto-captions and clean them to plain text."""

import os
import re
import subprocess
import sys
import time
from pathlib import Path

IDS_FILE = "/tmp/all_yt_ids.txt"
OUT_DIR = Path("/Users/reidar/Documents/RSHelper/transcripts")
TIMEOUT_S = 30
MIN_CHARS = 500

VTT_CUE_RE = re.compile(r"<[^>]+>")
VTT_HEADER_RE = re.compile(r"^NOTE|^WEBVTT|^Kind:|^Language:|^\d+$|^\d{2}:\d{2}")


def load_ids(path: str) -> list[str]:
    with open(path) as f:
        return [line.strip() for line in f if line.strip()]


def download_subs(video_id: str) -> bool:
    """Returns True if a .en.vtt file was produced."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--no-warnings",
        "--cookies-from-browser", "chrome",
        "--skip-download",
        "--write-auto-subs",
        "--sub-lang", "en",
        "--convert-subs", "vtt",
        "--remote-components", "ejs:github",

        "--output", str(OUT_DIR / "%(id)s"),
        url,
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S + 10)
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass
    return (OUT_DIR / f"{video_id}.en.vtt").exists()


def clean_vtt_text(raw: str) -> str:
    """Remove VTT timing/cue markup and collapse into readable paragraphs."""
    lines = raw.splitlines()
    clean: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            clean.append("")
            continue
        if VTT_HEADER_RE.match(stripped):
            continue
        if re.match(r"^\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[.,]\d{3}$", stripped):
            continue
        text = VTT_CUE_RE.sub("", stripped)
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'")
        if text.strip():
            clean.append(text.strip())
        else:
            clean.append("")
    collapsed: list[str] = []
    prev_blank = False
    for line in clean:
        if line == "":
            if not prev_blank:
                collapsed.append("")
            prev_blank = True
        else:
            collapsed.append(line)
            prev_blank = False
    return "\n".join(collapsed).strip()


def parse_and_clean(video_id: str) -> tuple[str, int]:
    """Parse VTT, clean it, save .txt, return (clean_text, char_count)."""
    vtt_path = OUT_DIR / f"{video_id}.en.vtt"
    txt_path = OUT_DIR / f"{video_id}.txt"
    try:
        raw = vtt_path.read_text(encoding="utf-8")
    except Exception:
        return "", 0
    clean = clean_vtt_text(raw)
    char_count = len(clean)
    txt_path.write_text(clean, encoding="utf-8")
    return clean, char_count


def main():
    video_ids = load_ids(IDS_FILE)
    total = len(video_ids)
    succeeded = 0
    with_text: list[tuple[str, int]] = []
    print(f"Processing {total} video IDs...")
    start_time = time.time()
    for i, vid in enumerate(video_ids):
        idx = i + 1
        print(f"[{idx:3d}/{total}] {vid} ... ", end="", flush=True)
        ok = download_subs(vid)
        if not ok:
            print("SKIP (no subs)")
            continue
        succeeded += 1
        clean_text, char_count = parse_and_clean(vid)
        if char_count >= MIN_CHARS:
            with_text.append((vid, char_count))
            print(f"OK ({char_count} chars)")
        else:
            print(f"OK ({char_count} chars, below threshold)")
    elapsed = time.time() - start_time
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    print()
    print("=" * 60)
    print(f"Total attempted:  {total}")
    print(f"Succeeded (VTT):  {succeeded}")
    print(f"With >= {MIN_CHARS} chars: {len(with_text)}")
    print(f"Elapsed:          {minutes}m {seconds}s")
    print()
    if with_text:
        with_text.sort(key=lambda x: x[1], reverse=True)
        print("Top 10 by transcript length:")
        for vid, chars in with_text[:10]:
            url = f"https://www.youtube.com/watch?v={vid}"
            print(f"  {chars:6d} chars — {vid} — {url}")
    report_path = OUT_DIR / "extraction_report.txt"
    with open(report_path, "w") as f:
        f.write(f"Extraction Report\n{'=' * 60}\n")
        f.write(f"Total attempted:  {total}\n")
        f.write(f"Succeeded (VTT):  {succeeded}\n")
        f.write(f"With >= {MIN_CHARS} chars: {len(with_text)}\n")
        f.write(f"Elapsed:          {minutes}m {seconds}s\n\n")
        if with_text:
            f.write("Top 10 by transcript length:\n")
            for vid, chars in with_text[:10]:
                f.write(f"  {chars:6d} chars — {vid}\n")
        f.write("\nAll succeeded IDs:\n")
        for vid, chars in with_text:
            f.write(f"  {vid} ({chars} chars)\n")
    print(f"\nReport saved to {report_path}")


if __name__ == "__main__":
    main()
