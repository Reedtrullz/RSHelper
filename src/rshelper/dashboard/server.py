"""Dashboard server — launch a local HTTP server for the RSHelper dashboard."""

import errno
import sys
import time
from http.server import ThreadingHTTPServer

from rshelper.cli import _fetch_bootstrap
from rshelper.scanner import FlipScanner
from rshelper.dashboard.handlers import make_handler
from rshelper.signals import detect_signals


def run(bind: str = "127.0.0.1", port: int = 5555) -> None:
    """Start the dashboard HTTP server.

    Prints the dashboard URL to stdout. All status/log messages go to stderr.
    Blocks until interrupted. Handles KeyboardInterrupt for graceful shutdown.
    Data re-fetches from the API every 120 seconds (ponytail TTL cache).
    """
    # Initial fetch — seed the TTL cache
    _mapping, _latest, _vol_5m, items = _fetch_bootstrap()

    from rshelper.tuning import record_if_changed
    record_if_changed()

    # ponytail: closure-based TTL cache, re-fetch every 120s.
    # Add configurable --refresh N flag when needed.
    cache = {"items": items, "last_fetch": time.time()}

    def get_items():
        now = time.time()
        if (now - cache["last_fetch"]) > 120:
            print("[dashboard] Re-fetching GE data...", file=sys.stderr)
            _m, _l, _v, fresh = _fetch_bootstrap()
            cache["items"] = fresh
            cache["last_fetch"] = now
        return list(cache["items"])

    scanner = FlipScanner(direction="arbitrage")

    def get_signals():
        _m, _l, vol_data, fresh_items = _fetch_bootstrap()
        flip_scanner = FlipScanner(direction="arbitrage")
        flips = flip_scanner.scan(fresh_items)
        return detect_signals(flips, vol_data)

    scanner = FlipScanner(direction="arbitrage")
    handler = make_handler(scanner, get_items, signal_detector=get_signals)

    # Warn on non-loopback bind
    if bind not in ("127.0.0.1", "localhost", "::1"):
        print(f"[dashboard] WARNING: binding to {bind} exposes the dashboard on "
              f"all network interfaces with no authentication", file=sys.stderr)

    try:
        server = ThreadingHTTPServer((bind, port), handler)
    except OSError as e:
        if e.errno == errno.EADDRINUSE:
            print(f"[dashboard] Port {port} is already in use", file=sys.stderr)
        elif e.errno == errno.EACCES:
            print(f"[dashboard] Permission denied for port {port} "
                  f"(try a port >= 1024)", file=sys.stderr)
        else:
            print(f"[dashboard] Cannot bind to {bind}:{port}: {e}", file=sys.stderr)
        sys.exit(1)

    server.daemon_threads = True

    url = f"http://{bind}:{port}"
    print(url)
    print(f"[dashboard] Dashboard running at {url}", file=sys.stderr)
    print(f"[dashboard] Press Ctrl-C to stop", file=sys.stderr)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[dashboard] Shutting down...", file=sys.stderr)
    finally:
        server.server_close()
        print("[dashboard] Stopped", file=sys.stderr)
