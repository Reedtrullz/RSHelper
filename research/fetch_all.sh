#!/usr/bin/env bash
set -u
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
outdir="$2"
mkdir -p "$outdir"
while IFS= read -r url; do
  while [ "$(jobs -r | wc -l)" -ge 8 ]; do sleep 0.2; done
  (
    fname="$outdir/$(echo "$url" | sed 's|https://||; s|http://||; s|?|__|; s|=|_|g; s|/|_|g').html"
    if curl -sS --max-time 40 -A "$UA" "$url" -o "$fname" 2>/dev/null; then
      echo "OK $(wc -c <"$fname") $fname"
    else
      echo "FAIL $url"
    fi
  ) &
done < "$1"
wait
