#!/usr/bin/env bash
set -u
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
cnt=0
fetch_one() {
  local url="$1" outdir="$2"
  local fname
  fname="$outdir/$(echo "$url" | sed 's|https://www.ge-tracker.com/||; s|?|__|; s|/|_|g').html"
  if curl -sS --max-time 40 -A "$UA" "$url" -o "$fname" 2>/dev/null; then
    echo "OK $(wc -c <"$fname") $fname"
  else
    echo "FAIL $url"
  fi
}
export -f fetch_one
export UA
while IFS= read -r url; do
  while [ "$(jobs -r | wc -l)" -ge 8 ]; do sleep 0.2; done
  fetch_one "$url" raw/articles &
done < "$1"
wait
