#!/usr/bin/env python3
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import sys
from uuid import uuid4

REPO = Path(os.environ.get('RSHELPER_REPO', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(REPO / 'src'))
from rshelper import persistence, profile as profiles, state_replication, state_transaction
from rshelper.backup import _read_file


def _ssh(host, destination, mode, origin, selected_profile, packet=None):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@-]*', host):
        raise ValueError('invalid SSH host alias')
    if (not destination.startswith('/') or '..' in Path(destination).parts
            or not re.fullmatch(r'/[A-Za-z0-9_/.-]+', destination)):
        raise ValueError('invalid private application destination')
    spec = importlib.util.spec_from_file_location('rshelper_sync_process', REPO / 'scripts/sync-and-push-state.py')
    if spec is None or spec.loader is None:
        raise ValueError('installed bounded sync helper unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    command = ['sudo', '-n', 'python3', destination + '/private-state.py',
               '--action', mode, '--origin', origin, '--profile', selected_profile,
               '--destination', destination]
    result = module.run_command(['ssh', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
                                '-o', 'IdentityAgent=none', '-o', 'StrictHostKeyChecking=yes',
                                host, shlex.join(command)],
                               data=_read_file(packet) if packet else None,
                               timeout=180 if mode == 'apply' else 60, output_limit=65536)
    if result.returncode:
        raise OSError('private SSH transfer or pinned apply failed; pending packet retained')
    return persistence.decode_json(result.stdout)


def _match(receipt, manifest):
    state_replication._validate_receipt(receipt)
    return (receipt['status'] in ('applied', 'no_op')
            and receipt['profile_uuid'] == manifest['profile_uuid']
            and receipt['origin_uuid'] == manifest['origin_uuid']
            and receipt['requested_revision'] == manifest['source_revision']
            and receipt['applied_revision'] == manifest['source_revision']
            and receipt['requested_hash'] == manifest['packet_hash']
            and receipt['applied_hash'] == manifest['packet_hash'])


def _read_outbox(outbox):
    pending = persistence.read_state(outbox / 'pending.json', 'generic')
    acknowledged = persistence.read_state(outbox / 'acknowledged.json', 'generic')
    if pending and (set(pending) != {'schema_version', 'host', 'destination', 'profile', 'packet', 'manifest'}
                    or type(pending['schema_version']) is not int or pending['schema_version'] != 1
                    or any(type(pending[field]) is not str for field in ('host', 'destination', 'profile', 'packet'))
                    or not re.fullmatch(r'[0-9a-f]{32}\.zip', pending['packet'])
                    or not isinstance(pending['manifest'], dict)):
        raise ValueError('invalid private pending metadata')
    if acknowledged:
        if (set(acknowledged) != {'schema_version', 'packet', 'receipt'}
                or type(acknowledged['schema_version']) is not int or acknowledged['schema_version'] != 1
                or type(acknowledged['packet']) is not str
                or not re.fullmatch(r'[0-9a-f]{32}\.zip', acknowledged['packet'])):
            raise ValueError('invalid private acknowledgement metadata')
        state_replication._validate_receipt(acknowledged['receipt'])
        receipt = acknowledged['receipt']
        if (receipt['status'] not in ('applied', 'no_op')
                or receipt['requested_revision'] != receipt['applied_revision']
                or receipt['requested_hash'] != receipt['applied_hash']):
            raise ValueError('invalid exact private acknowledgement')
    return pending, acknowledged


def run_sync(selected_profile, host, destination, outbox, *, dry_run=False, status=False):
    if not Path(state_replication.__file__).resolve().is_relative_to((REPO / 'src/rshelper').resolve()):
        raise ValueError('loaded private state implementation differs from configured repository')
    root = profiles.resolve_config_path('', selected_profile)
    outbox = Path(outbox).absolute()
    if outbox.is_symlink() or outbox.resolve().is_relative_to(root):
        raise ValueError('private outbox must be outside profile state')
    pending_path = outbox / 'pending.json'
    if status:
        pending, acknowledged = _read_outbox(outbox)
        return {'pending': bool(pending), 'acknowledged': acknowledged.get('receipt') or None,
                'transport': 'authenticated-ssh', 'outbox': str(outbox)}
    with state_transaction.profile_transaction(selected_profile, root):
        activation = state_replication._activation(root)
        if dry_run:
            return {'profile_uuid': activation['profile_uuid'], 'origin_uuid': activation['origin_uuid'],
                    'transport': 'authenticated-ssh', 'host': host, 'destination': destination,
                    'classes': ['financial', 'shared', 'informational'], 'capture': False}
    outbox.mkdir(parents=True, mode=0o700, exist_ok=True)
    if outbox.stat().st_uid != os.getuid():
        raise ValueError('private outbox has a different owner')
    os.chmod(outbox, 0o700)
    with persistence.locked_state(outbox / '.sync'):
        pending, acknowledged = _read_outbox(outbox)
        if not pending and acknowledged.get('packet'):
            if not re.fullmatch(r'[0-9a-f]{32}\.zip', acknowledged['packet']):
                raise ValueError('invalid owned packet cleanup identity')
            (outbox / acknowledged['packet']).unlink(missing_ok=True)
        if pending:
            if (set(pending) != {'schema_version', 'host', 'destination', 'profile', 'packet', 'manifest'}
                    or pending['host'] != host or pending['destination'] != destination
                    or pending['profile'] != selected_profile
                    or not re.fullmatch(r'[0-9a-f]{32}\.zip', pending['packet'])):
                raise ValueError('pending private target differs; packet preserved')
            packet = outbox / pending['packet']
        else:
            packet = outbox / (uuid4().hex + '.zip')
            pending = {'schema_version': 1, 'host': host, 'destination': destination,
                       'profile': selected_profile, 'packet': packet.name,
                       'manifest': {'capture_pending': True, 'profile_uuid': activation['profile_uuid'],
                                    'origin_uuid': activation['origin_uuid']}}
            state_transaction._durable_write(pending_path, state_replication._json(pending), 0o600)
        reservation = pending['manifest']
        if not isinstance(reservation, dict):
            raise ValueError('invalid private pending manifest')
        if reservation.get('capture_pending') is True:
            if (set(reservation) != {'capture_pending', 'profile_uuid', 'origin_uuid'}
                    or reservation['profile_uuid'] != activation['profile_uuid']
                    or reservation['origin_uuid'] != activation['origin_uuid']):
                raise ValueError('pending capture source identity differs')
            if packet.exists():
                manifest, _, _ = state_replication._read_packet(packet)
                with state_transaction.profile_transaction(selected_profile, root) as txn:
                    metadata = state_replication._metadata(root)
                    previous = metadata['outgoing']
                    if previous != manifest:
                        if (manifest['parent_revision'] != (previous['source_revision'] if previous else 0)
                                or manifest['parent_hash'] != (previous['packet_hash'] if previous else None)
                                or manifest['profile_uuid'] != activation['profile_uuid']
                                or manifest['origin_uuid'] != activation['origin_uuid']):
                            raise ValueError('pending capture cursor ancestry differs; packet preserved')
                        metadata['outgoing'] = manifest
                        txn.stage('replication-state.json', metadata)
                        txn.commit(str(uuid4()))
            else:
                manifest = state_replication.capture_packet(selected_profile, packet)
            pending['manifest'] = manifest
            state_transaction._durable_write(pending_path, state_replication._json(pending), 0o600)
        else:
            manifest, _, _ = state_replication._read_packet(packet)
            if manifest != reservation:
                raise ValueError('pending packet differs from durable manifest')
        if (manifest['profile_uuid'] != activation['profile_uuid']
                or manifest['origin_uuid'] != activation['origin_uuid']):
            raise ValueError('pending packet no longer belongs to selected source')
        receipt = _ssh(host, destination, 'receipt', manifest['origin_uuid'], selected_profile)
        if receipt == {}:
            receipt = None
        if receipt is not None:
            state_replication._validate_receipt(receipt)
            if receipt['profile_uuid'] != manifest['profile_uuid'] or receipt['origin_uuid'] != manifest['origin_uuid']:
                raise ValueError('private destination receipt identity differs')
        if receipt is None or not _match(receipt, manifest):
            receipt = _ssh(host, destination, 'apply', manifest['origin_uuid'], selected_profile, packet)
        if not _match(receipt, manifest):
            raise ValueError('private destination did not acknowledge exact packet')
        state_transaction._durable_write(outbox / 'acknowledged.json', state_replication._json(
            {'schema_version': 1, 'receipt': receipt, 'packet': packet.name}), 0o600)
        pending_path.unlink()
        packet.unlink()
        directory = os.open(outbox, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description='Replicate one identified profile over private SSH')
    parser.add_argument('--profile', default='default')
    parser.add_argument('--host', default='Racknerd-Deploy')
    parser.add_argument('--destination', default='/opt/apps/rshelper')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--status', action='store_true')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    try:
        report = run_sync(args.profile, args.host, args.destination,
                          profiles.resolve_cache_path('private-sync', args.profile),
                          dry_run=args.dry_run, status=args.status)
        print(json.dumps(report, sort_keys=True) if args.json else 'Private state: ' + json.dumps(report, sort_keys=True))
        return 0
    except (OSError, ValueError):
        print('[sync] private replication failed; source and pending packet preserved; inspect --status', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
