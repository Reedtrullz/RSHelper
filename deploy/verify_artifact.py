#!/usr/bin/env python3
"""Verify digest/revision receipts without exposing container environment."""
import argparse
import importlib.util
import json
import io
import tarfile
import uuid
from pathlib import Path
import subprocess
import selectors
import os
import time
import sys


def bounded_command(command, *, limit=65536, timeout=45):
    """Drain a child through a byte budget and absolute deadline, then reap it."""
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + timeout
    output = bytearray()
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0: raise subprocess.TimeoutExpired(command, timeout)
                if not selector.select(remaining): raise subprocess.TimeoutExpired(command, timeout)
                chunk = os.read(process.stdout.fileno(), min(4096, limit+1-len(output)))
                if not chunk: break
                output.extend(chunk)
                if len(output) > limit: raise ValueError('Artifact query exceeded its response budget')
        remaining = deadline - time.monotonic()
        if remaining <= 0: raise subprocess.TimeoutExpired(command, timeout)
        if process.wait(timeout=remaining): raise ValueError('Docker artifact query failed')
        return bytes(output)
    finally:
        process.stdout.close()
        if process.poll() is None: process.kill()
        process.wait(timeout=5)


def _docker_bytes(arguments):
    return bounded_command(['docker', *arguments])


def docker_json(arguments):
    return json.loads(_docker_bytes(arguments))


def copy_build_metadata(image):
    """Read one bounded regular file from an unstarted, disposable container."""
    name = 'rshelper-artifact-' + uuid.uuid4().hex
    try:
        _docker_bytes(['create', '--name', name, '--network', 'none',
            '--read-only', '--entrypoint', '/bin/false', image])
        copied = _docker_bytes(['cp', name+':/app/src/rshelper/_build.json', '-'])
        with tarfile.open(fileobj=io.BytesIO(copied), mode='r:') as archive:
            members = archive.getmembers()
            if (len(members) != 1 or members[0].name != '_build.json'
                    or not members[0].isreg() or not 0 < members[0].size <= 4096):
                raise ValueError('Candidate metadata must be one bounded regular file')
            with archive.extractfile(members[0]) as stream:
                return json.loads(stream.read(4097))
    except tarfile.TarError as exc:
        raise ValueError('Invalid candidate metadata archive') from exc
    finally:
        _docker_bytes(['rm', '--force', name])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('candidate', 'previous', 'running'), required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--revision')
    parser.add_argument('--repository')
    parser.add_argument('--container', default='rshelper')
    parser.add_argument('--expected-image-id')
    parser.add_argument('--validation-module', required=True)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('release_validation', args.validation_module)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    # Select only identity fields, never runtime Env (which could contain secrets).
    if args.mode == 'running':
        identity = docker_json(['container', 'inspect', '--format', '{{json .Image}}', args.container])
        if identity != args.expected_image_id: raise ValueError('Running image ID differs from the verified artifact')
        print(json.dumps({'image_id': identity, 'image': args.image, 'revision': args.revision}))
        return
    inspected = docker_json(['image', 'inspect', args.image])
    if not isinstance(inspected, list) or len(inspected) != 1: raise ValueError('Ambiguous image inspection')
    if args.mode == 'previous':
        if not args.repository: raise ValueError('Previous repository is required')
        identity = docker_json(['container', 'inspect', '--format', '{{json .Image}}', args.container])
        receipt = module.previous_release(inspected[0], identity, args.repository)
    else:
        if not module.IMAGE.fullmatch(args.image) or not args.revision or not module.REVISION.fullmatch(args.revision):
            raise ValueError('Immutable image digest and source revision are required')
        baked = copy_build_metadata(args.image)
        receipt = module.validate_candidate(args.image, args.revision, inspected[0], baked)
    print(json.dumps(receipt, sort_keys=True))


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print(f'Artifact verification failed: {exc}', file=sys.stderr)
        raise SystemExit(1)
