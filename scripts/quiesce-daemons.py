#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'src'))
from rshelper import persistence, state_transaction

LABELS = ('com.reidar.rshelper-trader', 'com.reidar.rshelper-monitor',
          'com.reidar.rshelper-state-sync')


def command(*args):
    return subprocess.run(['launchctl', *args], capture_output=True, timeout=10)


def loaded(domain, label):
    result = command('print', domain + '/' + label)
    if result.returncode == 0:
        return True
    if result.returncode == 113 and b'Could not find service' in result.stderr:
        return False
    raise OSError('owned daemon load status could not be verified')


def manage(action, home):
    home = Path(home)
    folder = home / 'Library/LaunchAgents'
    checkpoint = home / 'Library/Application Support/RSHelper/quiescence.json'
    domain = 'gui/' + str(os.getuid())
    with persistence.locked_state(checkpoint):
        saved = persistence.read_state(checkpoint, 'generic')
        if saved:
            if (set(saved) != {'schema_version', 'domain', 'jobs'} or saved['schema_version'] != 1
                    or saved['domain'] != domain or not isinstance(saved['jobs'], dict)
                    or set(saved['jobs']) - set(LABELS)):
                raise ValueError('invalid owned daemon handoff checkpoint')
            jobs = saved['jobs']
        elif action == 'resume':
            raise ValueError('no owned daemon quiescence checkpoint')
        else:
            jobs = {}
            for label in LABELS:
                path = folder / (label + '.plist')
                if not path.exists():
                    continue
                raw = _plist(path, label)
                jobs[label] = {'sha256': hashlib.sha256(raw).hexdigest(),
                               'loaded': loaded(domain, label)}
            saved = {'schema_version': 1, 'domain': domain, 'jobs': jobs}
            state_transaction._durable_write(checkpoint, json.dumps(saved, sort_keys=True).encode(), 0o600)
        for label, prior in jobs.items():
            path = folder / (label + '.plist')
            raw = _plist(path, label)
            if (not isinstance(prior, dict) or set(prior) != {'sha256', 'loaded'}
                    or type(prior['loaded']) is not bool
                    or hashlib.sha256(raw).hexdigest() != prior['sha256']):
                raise ValueError('owned daemon configuration changed during handoff')
        for label, prior in jobs.items():
            path = folder / (label + '.plist')
            is_loaded = loaded(domain, label)
            if action == 'quiesce' and is_loaded:
                if command('bootout', domain + '/' + label).returncode:
                    raise OSError('owned daemon bootout failed')
                if loaded(domain, label):
                    raise OSError('owned daemon remains loaded')
            elif action == 'resume' and prior['loaded'] and not is_loaded:
                if command('bootstrap', domain, str(path)).returncode:
                    raise OSError('owned daemon bootstrap failed')
                if not loaded(domain, label):
                    raise OSError('owned daemon did not reload')
        if action == 'resume':
            checkpoint.unlink()
            descriptor = os.open(checkpoint.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        return {'status': 'quiesced' if action == 'quiesce' else 'resumed', 'jobs': sorted(jobs)}


def _plist(path, label):
    if path.is_symlink() or not path.is_file() or path.stat().st_uid != os.getuid():
        raise ValueError('owned daemon plist must be a regular user-owned file')
    from rshelper.backup import _read_file
    raw = _read_file(path, 65536)
    data = plistlib.loads(raw)
    if data.get('Label') != label or not isinstance(data.get('ProgramArguments'), list):
        raise ValueError('owned daemon plist identity differs')
    return raw


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('quiesce', 'resume'))
    args = parser.parse_args(argv)
    try:
        print(json.dumps(manage(args.action, Path.home()), sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.TimeoutExpired, plistlib.InvalidFileException):
        print('daemon handoff failed; checkpoint retained; inspect owned jobs before continuing', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
