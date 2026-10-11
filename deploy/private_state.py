#!/usr/bin/env python3
import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
from uuid import UUID, uuid4

MAX_PACKET_BYTES = 64 * 1024 * 1024
REPOSITORY = 'ghcr.io/reedtrullz/rshelper'
APP_DIR = Path('/opt/apps/rshelper')


def _module(path, name):
    if path.is_symlink() or not path.is_file():
        raise ValueError('installed artifact helper must be a regular file')
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError('installed artifact helper cannot be loaded')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _running(root, verifier, release):
    if (root / 'data').is_symlink():
        raise ValueError('private state volume must not be a symlink')
    image_id = verifier.docker_json(['container', 'inspect', '--format', '{{json .Image}}', 'rshelper'])
    running = verifier.docker_json(['container', 'inspect', '--format', '{{json .State.Running}}', 'rshelper'])
    mounts = verifier.docker_json(['container', 'inspect', '--format', '{{json .Mounts}}', 'rshelper'])
    home = [mount for mount in mounts if mount['Destination'] == '/home/rshelper']
    if (running is not True or len(home) != 1 or home[0]['Type'] != 'bind'
            or Path(home[0]['Source']).resolve() != (root / 'data').resolve()
            or home[0]['RW'] is not True):
        raise ValueError('running private volume identity differs')
    inspected = verifier.docker_json(['image', 'inspect', image_id])[0]
    previous = release.previous_release(inspected, image_id, REPOSITORY)
    baked = verifier.copy_build_metadata(image_id)
    return release.validate_candidate(previous['image'], previous['revision'], inspected, baked)


def _run_image(verifier, image_id, root, stage, arguments):
    name = 'rshelper-state-' + uuid4().hex
    command = ['run', '--name', name, '--network', 'none', '--read-only',
               '--user', '1000:1000', '--mount',
               'type=bind,src=' + str(root / 'data') + ',dst=/home/rshelper',
               '--entrypoint', 'python']
    if stage is not None:
        command += ['--mount', 'type=bind,src=' + str(stage) + ',dst=/state-stage,readonly']
    try:
        return json.loads(verifier._docker_bytes(command + [image_id, *arguments]))
    finally:
        verifier._docker_bytes(['rm', '--force', name])


def perform(root, action, origin, selected_profile, *, source=None, incoming=None):
    root = Path(root)
    if root != APP_DIR or root.is_symlink():
        raise ValueError('private apply destination must be the installed application')
    if ((action not in ('legacy', 'contract') and (type(origin) is not str or str(UUID(origin)) != origin))
            or not re.fullmatch('[A-Za-z0-9_-]{1,32}', selected_profile)):
        raise ValueError('invalid private state identity')
    lock = os.open(root / 'production.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(lock).st_mode):
            raise ValueError('production lease must be a regular file')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        verifier = _module(root / 'verify-artifact.py', 'rshelper_artifact')
        release = _module(root / 'release-validation.py', 'rshelper_release')
        identity = _running(root, verifier, release)
        stage = None
        owned_stage = None
        try:
            if action == 'receipt':
                arguments = ['-m', 'rshelper', '--profile', selected_profile, 'state', 'receipt', '--origin', origin, '--json']
            elif action == 'contract':
                arguments = ['-m', 'rshelper', '--profile', selected_profile, 'state', 'check', '--json']
            elif action == 'apply':
                if incoming is None:
                    raise ValueError('private packet input is required')
                raw = incoming.read(MAX_PACKET_BYTES + 1)
                if not raw or len(raw) > MAX_PACKET_BYTES:
                    raise ValueError('private packet exceeds transfer budget')
                parent = root / 'state-transfers'
                if parent.is_symlink():
                    raise ValueError('private staging directory must not be a symlink')
                parent.mkdir(mode=0o700, exist_ok=True)
                stage = parent / uuid4().hex
                stage.mkdir(mode=0o700)
                owned_stage = stage
                os.chown(stage, 1000, 1000)
                fd = os.open(stage / 'state-packet.zip', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                    os.fchown(stream.fileno(), 1000, 1000)
                arguments = ['-m', 'rshelper', '--profile', selected_profile, 'state', 'apply', '--input', '/state-stage/state-packet.zip', '--json']
            elif action == 'legacy':
                if not source:
                    raise ValueError('legacy staging path is required')
                stage = Path(source)
                if stage.is_symlink() or not stage.is_dir():
                    raise ValueError('legacy staging must be a regular directory')
                arguments = ['/app/deploy/merge_state.py', '/state-stage', '/home/rshelper/.config/rshelper', '--application']
            else:
                raise ValueError('unknown private state operation')
            return _run_image(verifier, identity['image_id'], root, stage, arguments)
        finally:
            if owned_stage is not None:
                shutil.rmtree(owned_stage)
    finally:
        os.close(lock)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--action', choices=('receipt', 'apply', 'legacy', 'contract'), required=True)
    parser.add_argument('--origin')
    parser.add_argument('--profile', default='default')
    parser.add_argument('--destination', default='/opt/apps/rshelper')
    parser.add_argument('--stage')
    args = parser.parse_args(argv)
    try:
        receipt = perform(args.destination, args.action, args.origin, args.profile,
                          source=args.stage, incoming=sys.stdin.buffer)
        print(json.dumps(receipt, sort_keys=True))
        return 0
    except (OSError, ValueError):
        print('private state operation failed; source packet retained; no receipt acknowledged', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
