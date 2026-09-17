# -*- coding: utf-8 -*-
"""GitHub-каталог релизов 3x-ui (MHSanaei/3x-ui).

Только чтение: последняя версия, список версий, URL артефактов. Скачивание —
в release_cache.py; установка — в installer.py (этап 2).

HTTP — stdlib urllib.request (как core/update/updater.py: без новых
зависимостей). Latest определяется redirect-приёмом (HEAD на
releases/latest → конечный URL содержит тег) — не подвержен 60 req/h
unauthenticated-API лимиту, как и в официальном install.sh 3x-ui.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.request
from typing import List, Optional

REPO = "MHSanaei/3x-ui"
RELEASES_LATEST_URL = f"https://github.com/{REPO}/releases/latest"
RELEASES_API_URL = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
DOWNLOAD_URL = f"https://github.com/{REPO}/releases/download"

USER_AGENT = "Bot4VPS-3x-ui"
_HTTP_TIMEOUT = 20
_LIST_TIMEOUT = 30

# «v2.3.5» / «2.3.5»; dev-latest и прочие не-semver теги не каталожные
_TAG_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")

# Arch-имена артефактов в релизах 3x-ui (x-ui-linux-<arch>.tar.gz)
SUPPORTED_ARCHS = ("amd64", "arm64")


class ReleaseError(Exception):
    """Сетевая/форматная ошибка каталога релизов. Не несёт step-id —
    это не шаг установки, а источник данных (UI покажет текст)."""


def parse_tag(tag: str) -> Optional[tuple]:
    """«v2.6.4» → (2, 6, 4). Не-semver (dev-latest) → None."""
    m = _TAG_RE.match(str(tag or "").strip())
    if not m:
        return None
    return tuple(int(g) for g in m.groups())


def is_version_newer(candidate: str, reference: str) -> bool:
    """candidate строго новее reference (обе — semver-теги; некорректная
    reference считается «старой нулевой» — кандидат новее)."""
    ref = parse_tag(reference) or (0, 0, 0)
    cand = parse_tag(candidate)
    if cand is None:
        return False
    return cand > ref


def tarball_url(tag: str, arch: str) -> str:
    """URL тарболла релиза. tag — с 'v' или без (нормализуем к 'v')."""
    if arch not in SUPPORTED_ARCHS:
        raise ReleaseError(f"Неподдерживаемая архитектура: {arch}")
    norm = tag if tag.startswith("v") else f"v{tag}"
    return f"{DOWNLOAD_URL}/{norm}/x-ui-linux-{arch}.tar.gz"


def sha256_url(tag: str, arch: str) -> str:
    """URL sidecar-чексуммы (<артефакт>.sha256 публикуют с релизом)."""
    return tarball_url(tag, arch) + ".sha256"


def _urlopen(url: str, timeout: int):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_latest_tag() -> str:
    """Последний стабильный тег через releases/latest redirect.

    Redirect-приём: GitHub отдаёт 302 на /tag/<tag>; итоговый URL читаем
    без скачивания тела. Ошибка сети → ReleaseError (строка для UI).
    """
    try:
        with _urlopen(RELEASES_LATEST_URL, timeout=_HTTP_TIMEOUT) as resp:
            final_url = resp.geturl()
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ReleaseError(f"GitHub недоступен: {e}") from e
    # .../releases/tag/v2.6.4 → v2.6.4
    marker = "/releases/tag/"
    if marker not in final_url:
        raise ReleaseError(f"Неожидаемый ответ releases/latest: {final_url}")
    tag = final_url.split(marker, 1)[1].split("?", 1)[0].strip("/")
    if not tag or tag == "latest":
        raise ReleaseError(f"Не удалось определить тег из {final_url}")
    return tag


def fetch_tag_list() -> List[str]:
    """Список semver-тегов релизов (свежие первыми) через публичный API.

    Для разовых операций (выбор версии в UI); периодический job использует
    fetch_latest_tag (redirect, без лимитов API). Ошибка сети → ReleaseError.
    """
    try:
        with _urlopen(RELEASES_API_URL, timeout=_LIST_TIMEOUT) as resp:
            import json
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ReleaseError(f"GitHub API недоступен: {e}") from e
    if not isinstance(data, list):
        raise ReleaseError("GitHub API вернул не список релизов")
    tags = []
    for item in data:
        tag = str(item.get("tag_name") or "")
        if parse_tag(tag):
            tags.append(tag.lstrip("v"))
    return tags
