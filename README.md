# RSHelper

OSRS Grand Exchange profit scanner.

## Usage

```bash
python -m rshelper alch-scan
python -m rshelper alch-scan --members-only --top 20
python -m rshelper alch-scan --nature-rune-cost 150 --json
```

## Development

```bash
python -m pytest tests/
# or
python tests/test_scanner.py
```

v0.1 scope: alch-profit scanner only. Flip finder and backtester planned for v0.2+.
