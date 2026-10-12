import csv
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import zipfile

from rshelper import backup, persistence
_CSV_LOCK = threading.Lock()


def _read_csv(raw):
    with _CSV_LOCK:
        limit = csv.field_size_limit(backup.MAX_BUNDLE_BYTES)
        try:
            reader = csv.reader(io.StringIO(raw.decode('utf-8'), newline=''), strict=True)
            if next(reader, None) != ['file', 'content']:
                raise ValueError('invalid private CSV header')
            files = {}
            for row in reader:
                if len(row) != 2 or row[0] in files or len(files) >= 513:
                    raise ValueError('invalid or duplicate CSV file')
                files[row[0]] = row[1]
            manifest = persistence.decode_json(files.pop('manifest.json').encode())
            return manifest, files
        except (csv.Error, KeyError) as exc:
            raise ValueError('invalid private CSV import') from exc
        finally:
            csv.field_size_limit(limit)


def export_profile(profile, destination, format='json'):
    if format not in ('json', 'csv'):
        raise ValueError('unsupported private export format')
    with tempfile.TemporaryDirectory(prefix='rshelper-transfer-') as folder:
        archive = Path(folder)/'profile.zip'
        backup.export_profile(profile, archive)
        manifest, content = backup._inspect(archive)
    content = {name: raw.decode('utf-8') for name, raw in content.items()}
    if format == 'json':
        payload = json.dumps({'manifest': manifest, 'files': content}, sort_keys=True).encode()
    else:
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(['file', 'content'])
        writer.writerow(['manifest.json', json.dumps(manifest, sort_keys=True)])
        writer.writerows(sorted(content.items()))
        payload = output.getvalue().encode()
    if len(payload) > backup.MAX_BUNDLE_BYTES:
        raise ValueError('private export exceeds byte budget')
    destination = Path(destination).absolute()
    if destination.resolve().is_relative_to(backup._profile_root(profile)):
        raise ValueError('export destination must be outside profile state')
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=destination.parent, prefix='.rshelper-export-')
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(payload); stream.flush(); os.fsync(stream.fileno())
        os.link(temporary, destination)
        directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {'schema_version': 1, 'sensitivity': 'private', 'format': format,
            'profile_uuid': manifest['profile_uuid'], 'source_revision': manifest['source_revision'],
            'files': sorted(content)}


def import_profile(profile, source, format='json', *, expected_profile_uuid,
                   expected_source_revision=None, apply=False, operation_id=None, backup_path=None):
    if apply and (operation_id is None or backup_path is None):
        raise ValueError('apply requires an operation UUID and a new pre-apply backup path')
    if format not in ('json', 'csv', 'zip'):
        raise ValueError('unsupported private import format')
    with tempfile.TemporaryDirectory(prefix='rshelper-import-') as folder:
        archive = Path(folder)/'staged.zip'
        if format == 'zip':
            archive.write_bytes(backup._read_file(Path(source), backup.MAX_BUNDLE_BYTES))
        else:
            raw = backup._read_file(Path(source), backup.MAX_BUNDLE_BYTES)
            if format == 'json':
                data = persistence.decode_json(raw)
                if not isinstance(data, dict) or set(data) != {'manifest', 'files'}:
                    raise ValueError('invalid profile export envelope')
                manifest, files = data['manifest'], data['files']
            else:
                manifest, files = _read_csv(raw)
            if (not isinstance(files, dict) or len(files) > 512 or 'manifest.json' in files
                    or any(type(name) is not str or type(value) is not str for name, value in files.items())):
                raise ValueError('invalid private import inventory')
            if not isinstance(manifest, dict):
                raise ValueError('invalid private import manifest')
            manifest = dict(manifest)
            manifest.pop('profile_uuid', None)
            with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
                bundle.writestr('manifest.json', json.dumps(manifest, sort_keys=True))
                for name, value in files.items():
                    bundle.writestr(name, value)
        return backup.restore_profile(profile, archive, expected_profile_uuid=expected_profile_uuid,
            operation_id=operation_id, expected_source_revision=expected_source_revision,
            dry_run=not apply, pre_restore_backup=backup_path if apply else None)
