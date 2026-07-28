#!/usr/bin/env bash
url="$1"; n=$(echo "$url" | sed 's|https://www.ge-tracker.com/blog/|getracker-blog-|; s|https://www.reddit.com/||; s|/|_|g; s|?|__|; s|=|_|g; s|https://||' ) && n="${n%.html}.html"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
curl -sSL --max-time 30 -A "$UA" "$url" -o "$n" 2>/dev/null && echo "OK $(wc -c <"$n") $n"
