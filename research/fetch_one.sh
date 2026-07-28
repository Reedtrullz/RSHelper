#!/usr/bin/env bash
url="$1"
fn="raw/articles/$(echo "$url" | sed 's|https://||; s|?|__|; s|=|_|g; s|/|_|g').html"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
curl -sS --max-time 40 -A "$UA" "$url" -o "$fn" 2>/dev/null && echo "OK $(wc -c <"$fn") $fn"
