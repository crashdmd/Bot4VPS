"""Identify existing SSClash binaries using official release fingerprints."""
import asyncio
import hashlib
import json
import re
import time
from urllib.parse import quote

import httpx
from core.openwrt import bundles
from core.json_store import atomic_write_json

_checksums = {}


def ssclash_architecture(platform):
    architecture = platform.get('architecture', '')
    return 'amd64' if architecture == 'x86_64' else 'arm64' if architecture == 'aarch64' or architecture.startswith('aarch64_') else None


def checksum_entries(text):
    result = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) == 2 and re.fullmatch(r'[a-fA-F0-9]{64}', fields[0]):
            result[fields[1].lstrip('*').removeprefix('./')] = fields[0].lower()
    return result


def checksum_releases(versions):
    return [{'tag_name': tag, 'assets': [
        {'name': 'ssclash-linux-amd64'}, {'name': 'ssclash-linux-arm64'},
        {'name': 'sha256sums.txt', 'browser_download_url': 'https://github.com/' + bundles.REPOS['ssclash'] + '/releases/download/' + quote(tag, safe='') + '/sha256sums.txt'}]}
        for tag in set(versions) if bundles._version(tag)]


async def release_checksums(http, release):
    asset = next((row for row in release.get('assets', []) if row.get('name') == 'sha256sums.txt'), None)
    if not asset: return {}
    url = asset.get('browser_download_url', '')
    expected = 'https://github.com/' + bundles.REPOS['ssclash'] + '/releases/download/' + quote(release['tag_name'], safe='') + '/sha256sums.txt'
    if url != expected: raise ValueError('Источник контрольных сумм SSClash не совпадает с официальным релизом')
    saved = bundles.ROOT / 'release-fingerprints' / (hashlib.sha256(url.encode()).hexdigest() + '.json')
    try:
        record = json.loads(saved.read_text())
        if isinstance(record, dict) and record.get('source') == url:
            entries = record.get('checksums', {})
            if isinstance(entries, dict) and all(isinstance(name, str) and isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value) for name, value in entries.items()): return entries
    except (OSError, ValueError, TypeError): pass
    cached = _checksums.get(url)
    if cached and cached[0] > time.monotonic(): return cached[1]
    async with http.stream('GET', url) as response:
        response.raise_for_status()
        bundles._allowed_url(str(response.url))
        chunks = []; size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > 65536: raise ValueError('Файл контрольных сумм SSClash слишком большой')
            chunks.append(chunk)
    entries = checksum_entries(b''.join(chunks).decode('utf-8'))
    if len(_checksums) >= 128: _checksums.clear()
    _checksums[url] = (time.monotonic() + 900, entries)
    if entries:
        try:
            saved.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(saved, {'source': url, 'checksums': entries})
        except OSError: pass  # Identification still works with a read-only metadata cache.
    return entries


async def identify_ssclash(fingerprint, releases, platform):
    if not re.fullmatch(r'[a-fA-F0-9]{64}', fingerprint or ''): return None
    arch = ssclash_architecture(platform)
    if not arch: return None
    name = 'ssclash-linux-' + arch
    fingerprint = fingerprint.lower()
    by_tag = {}
    for row in releases:
        if row.get('tag_name') not in by_tag: by_tag[row.get('tag_name')] = row
    candidates = sorted((row for row in by_tag.values() if bundles._version(row.get('tag_name', '')) and not row.get('draft') and not row.get('prerelease')),
                        key=lambda row: bundles._version(row['tag_name']), reverse=True)
    # GitHub supplies SHA-256 for newer assets; it also covers installations
    # made outside Bot4VPS without downloading a binary or running it.
    for row in candidates:
        asset = next((asset for asset in row.get('assets', []) if asset.get('name') == name), {})
        if asset.get('digest') == 'sha256:' + fingerprint: return row['tag_name']
    if not any(asset.get('name') == name for row in candidates for asset in row.get('assets', [])): return None
    async with asyncio.timeout(20):
        async with httpx.AsyncClient(trust_env=False, follow_redirects=True, timeout=10,
                                     headers={'User-Agent': 'Bot4VPS-OpenWrt'}) as http:
            for row in candidates:
                asset = next((asset for asset in row.get('assets', []) if asset.get('name') == name), None)
                if not asset or re.fullmatch(r'sha256:[a-fA-F0-9]{64}', asset.get('digest') or ''): continue
                entries = await release_checksums(http, row)
                if entries.get(name) == fingerprint: return row['tag_name']
    return None
