"""Panel-owned release metadata cache and GitHub rate-limit backoff."""
import asyncio
import json
import time
from pathlib import Path

import httpx
from core.json_store import atomic_write_json

_locks = {}
_state = {}


def read(path, repository):
    try:
        value = json.loads(path.read_text())
        if isinstance(value, dict) and value.get('repository') == repository and isinstance(value.get('releases'), list): return value
    except (OSError, ValueError, TypeError): pass
    return {'repository': repository, 'releases': [], 'fetched_at': 0, 'retry_at': 0}


def status(profile): return _state.get(profile, {})


async def get(root, profile, repository):
    async with _locks.setdefault(profile, asyncio.Lock()):
        path = Path(root) / 'release-index' / (profile + '.json')
        value = await asyncio.to_thread(read, path, repository)
        now = time.time()
        fresh = value.get('fetched_at', 0) > now - 600
        backoff = value.get('retry_at', 0) > now
        if fresh or backoff:
            _state[profile] = {'cached': True, 'offline': not fresh}
            if value['releases']: return value['releases']
            if backoff: raise ValueError('Лимит запросов GitHub исчерпан. Используются сохранённые на панели комплекты; онлайн-проверка повторится позже.')
        async with httpx.AsyncClient(trust_env=False, follow_redirects=True, timeout=20, headers={'User-Agent': 'Bot4VPS-OpenWrt'}) as http:
            response = await http.get('https://api.github.com/repos/' + repository + '/releases?per_page=100')
            if response.status_code in (403, 429):
                try: retry_at = float(response.headers.get('x-ratelimit-reset', now + 600))
                except ValueError: retry_at = now + 600
                value['retry_at'] = min(max(now + 60, retry_at), now + 3600)
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    await asyncio.to_thread(atomic_write_json, path, value)
                except OSError: pass
                _state[profile] = {'cached': bool(value['releases']), 'offline': True}
                if value['releases']: return value['releases']
            response.raise_for_status()
            rows = response.json()
            if not isinstance(rows, list): raise ValueError('Некорректный список релизов GitHub')
            # Keep release metadata; service binaries remain in verified bundles.
            rows = [{'tag_name': row.get('tag_name'), 'prerelease': row.get('prerelease', False), 'draft': row.get('draft', False), 'assets': [
                {key: asset.get(key) for key in ('name', 'browser_download_url', 'size', 'digest')} for asset in row.get('assets', [])]} for row in rows]
        value = {'repository': repository, 'releases': rows, 'fetched_at': now, 'retry_at': 0}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(atomic_write_json, path, value)
        except OSError: pass
        _state[profile] = {'cached': False, 'offline': False}
        return rows
