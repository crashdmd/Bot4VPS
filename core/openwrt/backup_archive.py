"""Validate configuration archives without extracting them on the panel."""
from __future__ import annotations

import gzip
from pathlib import PurePosixPath
import posixpath
import tarfile
import zlib

from core.openwrt.backup_store import MAX_ARCHIVE_BYTES

MAX_UNPACKED = 128 * 1024 * 1024
MAX_MEMBERS = 2000
FORBIDDEN = {'proc', 'sys', 'dev', 'run', 'tmp', 'overlay'}


def safe_path(value):
    if not isinstance(value, str) or len(value) > 512 or value.startswith('/') or '\\' in value:
        raise ValueError('Архив содержит недопустимый путь')
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError('Архив содержит недопустимый путь')
    try: value.encode('utf-8')
    except UnicodeEncodeError: raise ValueError('Имя файла в архиве не является корректным UTF-8') from None
    parts = PurePosixPath(value).parts
    if not parts or '..' in parts or parts[0] in FORBIDDEN:
        raise ValueError('Архив содержит путь за пределами настроек шлюза')
    return '/'.join(parts)


def inspect(path):
    if not 0 < path.stat().st_size <= MAX_ARCHIVE_BYTES:
        raise ValueError('Архив настроек должен быть не больше 32 МБ')
    total = 0
    try:
        # Read to EOF so a truncated gzip stream cannot pass on a complete tar prefix.
        with gzip.open(path, 'rb') as stream:
            while chunk := stream.read(65536):
                total += len(chunk)
                if total > MAX_UNPACKED:
                    raise ValueError('Распакованный архив настроек превышает 128 МБ')
        entries = []
        paths = set()
        links = set()
        regular = set()
        with tarfile.open(path, mode='r:gz') as archive:
            for member in archive:
                if member.isdir() and member.name in ('.', './'):
                    continue
                name = safe_path(member.name)
                if name in paths or len(entries) >= MAX_MEMBERS:
                    raise ValueError('Архив содержит повторяющиеся пути или слишком много файлов')
                if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                    raise ValueError('Архив содержит неподдерживаемый тип файла')
                entry = {'path': name, 'type': 'file' if member.isfile() else 'dir' if member.isdir() else 'link'}
                if member.issym() or member.islnk():
                    target = member.linkname
                    if member.issym():
                        if target.startswith('/'):
                            target = safe_path(target[1:])
                        else:
                            if '\\' in target or any(ord(c) < 32 for c in target):
                                raise ValueError('Архив содержит недопустимую ссылку')
                            target = safe_path(posixpath.normpath(posixpath.join(posixpath.dirname(name), target)))
                    else:
                        target = safe_path(target)
                    entry['target'] = target
                    entry['hardlink'] = member.islnk()
                    links.add(name)
                elif member.isfile():
                    regular.add(name)
                    if member.size < 0 or member.size > MAX_UNPACKED:
                        raise ValueError('Недопустимый размер файла в архиве')
                    source = archive.extractfile(member)
                    read = 0
                    while chunk := source.read(65536):
                        read += len(chunk)
                    if read != member.size:
                        raise ValueError('Файл в архиве повреждён')
                paths.add(name)
                entries.append(entry)
        for entry in entries:
            parents = PurePosixPath(entry['path']).parents
            if any(str(parent) in links for parent in parents):
                raise ValueError('Файл в архиве находится внутри ссылки')
            if entry.get('hardlink') and entry['target'] not in regular:
                raise ValueError('Жёсткая ссылка не указывает на файл внутри архива')
        if not regular or not any(name.startswith('etc/') for name in paths):
            raise ValueError('В архиве не найдены настройки OpenWrt в каталоге etc')
        return {'entries': entries, 'files': len(regular), 'unpacked_size': total,
                'network': any(name in paths for name in ('etc/config/network', 'etc/config/wireless', 'etc/config/firewall', 'etc/config/dhcp')),
                'access': any(name in paths for name in ('etc/config/rpcd', 'etc/config/uhttpd', 'etc/shadow', 'etc/passwd'))}
    except (tarfile.TarError, EOFError, OSError, zlib.error):
        raise ValueError('Архив настроек повреждён или имеет неподдерживаемый формат tar.gz') from None
