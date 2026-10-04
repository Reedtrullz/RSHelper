"""Image-owned build revision and independently verified deployment receipts."""
import json
import os
from pathlib import Path
import re
import stat

BUILD_METADATA_PATH = Path(__file__).with_name('_build.json')
DIGEST = re.compile(r'^sha256:[0-9a-f]{64}$')
REVISION = re.compile(r'^[0-9a-f]{40}$')
IMAGE = re.compile(r'^ghcr\.io/[a-z0-9._-]+/[a-z0-9._-]+@sha256:[0-9a-f]{64}$')


class ReleaseMetadataError(ValueError):
    pass


def _build(data):
    if (not isinstance(data, dict) or set(data) != {'schema_version', 'source_revision',
            'base_image_digest', 'platform'} or type(data['schema_version']) is not int
            or data['schema_version'] != 1 or data['platform'] != 'linux/amd64'
            or not isinstance(data['source_revision'], str) or not REVISION.fullmatch(data['source_revision'])
            or not isinstance(data['base_image_digest'], str) or not DIGEST.fullmatch(data['base_image_digest'])):
        raise ReleaseMetadataError('Invalid baked build metadata')
    return data


def build_metadata():
    try:
        fd = os.open(BUILD_METADATA_PATH, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ReleaseMetadataError('Cannot read baked build metadata') from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode): raise ReleaseMetadataError('Build metadata is not regular')
        with os.fdopen(fd, 'rb') as stream:
            fd = None
            raw = stream.read(4097)
        if len(raw) > 4096: raise ReleaseMetadataError('Build metadata exceeds limit')
        return _build(json.loads(raw))
    except (ValueError, UnicodeDecodeError, OSError) as exc:
        raise ReleaseMetadataError('Invalid baked build metadata') from exc
    finally:
        if fd is not None: os.close(fd)


def health_metadata():
    from rshelper import __version__
    baked = build_metadata()
    digest = os.environ.get('RSHELPER_IMAGE_DIGEST', '')
    return {'status': 'healthy', 'version': baked['source_revision'] if baked else __version__,
            'build_revision': baked['source_revision'] if baked else None,
            # This digest is a declaration checked against Docker by deployment;
            # the build revision comes only from the root-owned image file.
            'image_digest': digest if baked and DIGEST.fullmatch(digest) else None,
            'platform': baked['platform'] if baked else None,
            'base_image_digest': baked['base_image_digest'] if baked else None}


def _inspect(data):
    if (not isinstance(data, dict) or not isinstance(data.get('Id'), str)
            or not DIGEST.fullmatch(data['Id']) or data.get('Architecture') != 'amd64'
            or data.get('Os') != 'linux' or not isinstance(data.get('RepoDigests'), list)):
        raise ReleaseMetadataError('Image is unavailable or has the wrong platform/identity')
    config = data.get('Config')
    labels = config.get('Labels') if isinstance(config, dict) else None
    if not isinstance(labels, dict): raise ReleaseMetadataError('Missing OCI revision label')
    revision = labels.get('org.opencontainers.image.revision')
    if not isinstance(revision, str) or not REVISION.fullmatch(revision):
        raise ReleaseMetadataError('Invalid OCI revision label')
    return revision


def validate_candidate(image, revision, inspected, baked):
    if (not isinstance(image, str) or not IMAGE.fullmatch(image)
            or not isinstance(revision, str) or not REVISION.fullmatch(revision)):
        raise ReleaseMetadataError('An immutable GHCR digest and full revision are required')
    actual_revision = _inspect(inspected)
    baked = _build(baked)
    if image not in inspected['RepoDigests']:
        raise ReleaseMetadataError('Pulled digest does not match the requested image')
    if actual_revision != revision or baked['source_revision'] != revision:
        raise ReleaseMetadataError('Requested, OCI and baked revisions do not agree')
    return {'image': image, 'digest': image.partition('@')[2], 'revision': revision,
            'image_id': inspected['Id'], 'platform': 'linux/amd64'}


def previous_release(inspected, container_image_id, repository):
    revision = _inspect(inspected)
    if inspected['Id'] != container_image_id:
        raise ReleaseMetadataError('Previous container and image identities differ')
    matches = sorted({ref for ref in inspected['RepoDigests'] if isinstance(ref, str)
                      and IMAGE.fullmatch(ref) and ref.partition('@')[0] == repository})
    if not matches: raise ReleaseMetadataError('Previous image has no retained repository digest')
    return {'image': matches[0], 'digest': matches[0].partition('@')[2],
            'revision': revision, 'image_id': inspected['Id'], 'platform': 'linux/amd64'}
