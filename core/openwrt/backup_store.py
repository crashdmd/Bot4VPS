"""Gateway archive catalog; no router access and no changes to Linux backups."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile
import threading
import time

from core.install_paths import get_install_path
from core.json_store import atomic_write_json, locked

ROOT = get_install_path() / 'data/gateway-backups'
MAX_ARCHIVE_BYTES = 32 * 1024 * 1024
_lock = threading.RLock()
_ID = re.compile(r'[a-f0-9]{32}')


class ArchiveBusy(ValueError):
    pass


def archive_id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError('Некорректный идентификатор копии шлюза')
    return value


@contextmanager
def catalog_lock():
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    with locked(ROOT / '.catalog.lock', _lock):
        yield


def _regular(path):
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except FileNotFoundError:
        return False


def _load(value):
    value = archive_id(value)
    path = ROOT / 'catalog' / (value + '.json')
    if not _regular(path):
        raise FileNotFoundError('Копия шлюза не найдена')
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        raise ValueError('Запись копии шлюза повреждена') from None
    if not isinstance(record, dict) or record.get('id') != value:
        raise ValueError('Запись копии шлюза повреждена')
    if (not isinstance(record.get('created_at'), (int, float))
            or not isinstance(record.get('size'), int) or not 0 < record['size'] <= MAX_ARCHIVE_BYTES
            or not isinstance(record.get('source_name'), str)
            or not isinstance(record.get('filename'), str)
            or not re.fullmatch(r'[a-f0-9]{64}', str(record.get('sha256', '')))):
        raise ValueError('Запись копии шлюза повреждена')
    return record


def inventory():
    if not ROOT.exists():
        return []
    with catalog_lock():
        records = []
        for path in (ROOT / 'catalog').glob('*.json'):
            try:
                record = _load(path.stem)
            except (ValueError, FileNotFoundError):
                continue
            if _regular(ROOT / 'archives' / (record['id'] + '.tar.gz')):
                records.append(record)
        return sorted(records, key=lambda item: item['created_at'], reverse=True)


def save(source, *, source_name='', filename=None, model=None, version=None, target=None, origin='gateway'):
    """Publish a validated archive in a shared catalog; source is informational."""
    source = Path(source)
    if not _regular(source) or not 0 < source.stat().st_size <= MAX_ARCHIVE_BYTES:
        raise ValueError('Некорректный размер архива шлюза')
    if origin not in ('gateway', 'upload', 'protective'):
        raise ValueError('Некорректный источник копии шлюза')
    now = time.time()
    value = secrets.token_hex(16)
    label = str(model or source_name or 'openwrt')
    label = re.sub(r'[^\w.-]+', '-', label, flags=re.UNICODE).strip('-')[:80] or 'openwrt'
    if filename:
        filename = re.sub(r'[^\w .()-]+', '-', Path(filename).name, flags=re.UNICODE)[:140].strip('. ') or 'openwrt.tar.gz'
        if not filename.endswith(('.tar.gz', '.tgz')): filename += '.tar.gz'
    else:
        filename = label + '-' + datetime.fromtimestamp(now, timezone.utc).strftime('%Y%m%d-%H%M%S') + '.tar.gz'
    with catalog_lock():
        directory = ROOT / 'archives'
        directory.mkdir(exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(prefix='.incoming-', dir=directory)
        digest = hashlib.sha256()
        written = 0
        destination = directory / (value + '.tar.gz')
        try:
            with os.fdopen(fd, 'wb') as output, source.open('rb') as incoming:
                while chunk := incoming.read(65536):
                    written += len(chunk)
                    if written > MAX_ARCHIVE_BYTES:
                        raise ValueError('Архив шлюза превышает допустимый размер')
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            record = {'id': value, 'source_name': str(source_name),
                      'model': model, 'version': version, 'target': target, 'origin': origin,
                      'created_at': now, 'filename': filename, 'size': written, 'sha256': digest.hexdigest()}
            os.replace(temporary, destination)
            atomic_write_json(ROOT / 'catalog' / (value + '.json'), record)
            return record
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
        finally:
            Path(temporary).unlink(missing_ok=True)


def download(value, *, verify=False):
    with catalog_lock():
        record = _load(value)
        path = ROOT / 'archives' / (record['id'] + '.tar.gz')
        if not _regular(path):
            raise FileNotFoundError('Архив копии шлюза не найден')
        if path.stat().st_size != record['size']:
            raise ValueError('Размер архива копии шлюза изменился')
        if verify:
            with path.open('rb') as content:
                digest = hashlib.file_digest(content, 'sha256').hexdigest()
            if digest != record['sha256']:
                raise ValueError('Контрольная сумма копии шлюза не совпала')
        return path, record


def pin(value, token, expires):
    archive_id(token)
    with catalog_lock():
        download(value, verify=True)
        atomic_write_json(ROOT / 'pins' / (token + '.json'), {'archive_id': value, 'expires': expires})


def unpin(token):
    archive_id(token)
    with catalog_lock():
        (ROOT / 'pins' / (token + '.json')).unlink(missing_ok=True)


def delete(value):
    with catalog_lock():
        record = _load(value)
        for path in (ROOT / 'pins').glob('*.json'):
            try:
                pin_record = json.loads(path.read_text())
            except (OSError, ValueError):
                raise ArchiveBusy('Состояние выбранной для восстановления копии требует проверки') from None
            if pin_record.get('expires', 0) <= time.time():
                path.unlink(missing_ok=True)
            elif pin_record.get('archive_id') == value:
                raise ArchiveBusy('Копия выбрана для восстановления. Завершите или отмените план.')
        (ROOT / 'catalog' / (record['id'] + '.json')).unlink()
        (ROOT / 'archives' / (record['id'] + '.tar.gz')).unlink(missing_ok=True)
        return {'ok': True}
