"""HTTPS trust for explicit pre-7.0 rollbacks; never a fallback for updates."""
from __future__ import annotations

import json
import re
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    from .release_verify import REPOSITORY, normalized_version
except ImportError:
    from release_verify import REPOSITORY, normalized_version

LIMIT = 512 * 1024 * 1024
HOSTS = {'api.github.com', 'github.com', 'codeload.github.com'}


def target_version(action, target):
    version = normalized_version(target)
    if action != 'rollback' or not (3, 0, 0) <= tuple(map(int, version.split('.'))) < (7, 0, 0):
        raise ValueError('Без подписи разрешён только откат на версии от 3.0 до 7.0')
    return version


def check_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in HOSTS or parsed.port not in (None, 443)
            or parsed.username is not None or parsed.password is not None):
        raise ValueError('Недопустимый адрес старого релиза')
    prefix = f'/repos/{REPOSITORY}/' if parsed.hostname == 'api.github.com' else f'/{REPOSITORY}/'
    if not parsed.path.startswith(prefix):
        raise ValueError('Старый релиз должен принадлежать репозиторию Bot4VPS')


class Redirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, limit=4 * 1024 * 1024, destination=None):
    check_url(url)
    request = Request(url, headers={'User-Agent': 'Bot4VPS legacy rollback', 'Accept': 'application/json' if destination is None else 'application/octet-stream'})
    data = bytearray()
    total = 0
    with build_opener(Redirects()).open(request, timeout=120) as response:
        check_url(response.geturl())
        while chunk := response.read(256 * 1024):
            total += len(chunk)
            if total > limit:
                raise ValueError('Старый релиз превышает допустимый размер')
            if destination is None:
                data.extend(chunk)
            else:
                destination.write(chunk)
    return bytes(data)


def resolve(action, target):
    version = target_version(action, target)
    releases = json.loads(fetch(f'https://api.github.com/repos/{REPOSITORY}/releases?per_page=100'))
    if not isinstance(releases, list):
        raise ValueError('Не удалось прочитать старые релизы')
    tag = None
    for release in releases:
        if not isinstance(release, dict) or release.get('draft') or release.get('prerelease'):
            continue
        candidate = release.get('tag_name')
        try:
            if normalized_version(candidate) == version:
                tag = candidate
                break
        except ValueError:
            continue
    if tag is None:
        raise ValueError('Старая версия не опубликована в GitHub Releases')
    reference = json.loads(fetch(f'https://api.github.com/repos/{REPOSITORY}/git/ref/tags/{quote(tag, safe="")}')).get('object', {})
    for _ in range(5):
        sha = reference.get('sha')
        if not isinstance(sha, str) or not re.fullmatch('[0-9a-f]{40}', sha):
            raise ValueError('Старый релиз не закреплён за коммитом')
        if reference.get('type') == 'commit':
            return {'legacy': True, 'version': version, 'tag': tag, 'commit': sha,
                    'archive_url': f'https://github.com/{REPOSITORY}/archive/{sha}.tar.gz'}
        if reference.get('type') != 'tag':
            break
        reference = json.loads(fetch(f'https://api.github.com/repos/{REPOSITORY}/git/tags/{sha}')).get('object', {})
    raise ValueError('Не удалось разрешить тег старого релиза')
