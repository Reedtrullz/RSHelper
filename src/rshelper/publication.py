"""Default-deny publication preview and explicit demo-field serialization.

This module performs no filesystem, Git or network operations. The active
private replication feed is changed only by the separately reviewed cutover.
"""
from rshelper.persistence import StateCorruptionError, validate_state

SCHEMA_VERSION = 1
MAX_DEMO_RECORDS = 10_000
# Only non-label economics have a public-demo representation. Notes, account
# labels, names, configuration and operational timestamps stay private.
PUBLIC_FIELDS = {
    'trades.json': frozenset({'item_id', 'qty', 'buy_price', 'sell_price',
                              'tax_paid', 'profit', 'timestamp', 'hold_minutes'}),
    'positions.json': frozenset({'item_id', 'qty', 'buy_price', 'direction', 'opened_at'}),
}
KNOWN_FIELDS = {
    'trades.json': PUBLIC_FIELDS['trades.json'] | frozenset({
        'id', 'name', 'note', 'strategy', 'exit_reason', 'fill_guard',
        'quote_sell', 'entry_spread_pct', 'entry_sell', 'entry_offer'}),
    'positions.json': PUBLIC_FIELDS['positions.json'] | frozenset({
        'id', 'name', 'note', 'entry_sell', 'entry_offer'}),
}
PRIVATE_FILES = frozenset({'watchlist.json', 'alerts.json', 'config.toml',
    'active_profile', 'tuning_log.json', 'volume_baseline.json',
    'signal_cooldowns.json', 'trader_state.json', 'recent_exits.json'})


class PublicationError(ValueError):
    """A profile, file or field has no approved public representation."""


def _check(profile, policy, state):
    if not isinstance(policy, dict) or policy.get('schema_version') != SCHEMA_VERSION:
        raise PublicationError('unsupported publication policy')
    if set(policy) != {'schema_version', 'mode', 'approved_profiles', 'files'}:
        raise PublicationError('unknown or missing policy fields')
    if type(policy['schema_version']) is not int or policy['mode'] != 'public-demo':
        raise PublicationError('policy is not an approved public-demo policy')
    profiles = policy['approved_profiles']
    if not isinstance(profiles, list) or any(type(p) is not str for p in profiles) or profile not in profiles:
        raise PublicationError('profile has no public-demo approval')
    files = policy['files']
    if not isinstance(files, dict) or not files or not isinstance(state, dict):
        raise PublicationError('no approved demo files')
    if set(state) - (set(PUBLIC_FIELDS) | PRIVATE_FILES):
        raise PublicationError('unknown source file; publication denied')
    for filename, fields in files.items():
        if (filename not in PUBLIC_FIELDS or not isinstance(fields, list) or not fields
                or any(type(field) is not str for field in fields)
                or len(set(fields)) != len(fields) or set(fields) - PUBLIC_FIELDS[filename]):
            raise PublicationError('unapproved public field class')
        data = state.get(filename)
        key = filename.removesuffix('.json')
        if not isinstance(data, dict) or set(data) - {key, 'schema_version'}:
            raise PublicationError('unknown source schema fields')
        try:
            validate_state(data, key, filename)
        except StateCorruptionError as exc:
            raise PublicationError(str(exc)) from exc
        rows = data[key]
        if len(rows) > MAX_DEMO_RECORDS:
            raise PublicationError('demo record budget exceeded')
        for row in rows:
            if set(row) - KNOWN_FIELDS[filename]:
                raise PublicationError('unknown source row fields; publication denied')
    return files


def preview_publication(profile: str, policy: dict, state: dict) -> dict:
    """Describe the exact approved export schema/counts without record values."""
    files = _check(profile, policy, state)
    return {'schema_version': SCHEMA_VERSION, 'mode': 'public-demo', 'files': [
        {'path': filename, 'fields': sorted(fields),
         'records': len(state[filename][filename.removesuffix('.json')])}
        for filename, fields in sorted(files.items())]}


def export_demo(state: dict, policy: dict, *, profile: str) -> dict:
    """Return only explicitly approved fields; never mutate or publish input."""
    files = _check(profile, policy, state)
    return {filename: {'schema_version': SCHEMA_VERSION,
                      filename.removesuffix('.json'): [
                          {key: row.get(key) for key in sorted(fields)}
                          for row in state[filename][filename.removesuffix('.json')]]}
            for filename, fields in sorted(files.items())}
