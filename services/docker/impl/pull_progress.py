# -*- coding: utf-8 -*-
"""Живой прогресс загрузки образов Docker (compose.py §-pre-pull, images.py).

Два источника событий, оба сходятся в PullTracker:

  * Docker API через curl --unix-socket (основной путь, images._api_pull):
    POST /images/create отдаёт NDJSON-стрим со структурированными событиями
        {"status":"Downloading","progressDetail":{"current":..,"total":..},"id":..}
    Работает на любом Docker и не зависит от формата терминального вывода.
  * Текстовые строки `docker pull` (фолбэк без curl на сервере): старые CLI
    без TTY печатают по слою на строку:
        a2abf6c4d29d: Downloading [=================>   ]  14.24MB/62.51MB
    Новые версии (29+) в тексте прогресс не отдают — фолбэк тогда показывает
    факт загрузки без процентов.

Единственный наблюдатель потока — процесс задачи, которая качает образ.
Чтобы вкладка «Образы» (и любой другой потребитель) видела прогресс без
доступа к SSH-сессии задачи, PullTracker складывает агрегированный
процент во внутренний реестр {server_id: {image: снимок}}, а лёгкий
API-эндпоинт отдаёт его snapshot-ом. Реестр живёт в памяти процесса
панели — после перезапуска прогресс теряется, но теряется и сам
процесс-источник, так что это корректно.

Процент агрегируется по слоям: сумма скачанного / сумма известных размеров.
Слои, которые ещё не начали качаться, размера не знают — процент растёт по
мере появления их событий, как и в самом docker. Уже находящиеся локально
слои события без размера дают — они не участвуют в сумме (качать нечего).
"""
from __future__ import annotations

import re
import threading
from typing import Any, Dict, List, Optional, Tuple

# Реестр активных загрузок: server_id -> {image: snapshot-словарь}.
_active: Dict[str, Dict[str, Dict[str, Any]]] = {}
# Трекеры по ключу (server_id, image) — кнопке «✕» на вкладке «Образы» нужен
# сам объект (пометить отмену + убить процесс загрузки), а не снимок. Регистрируются
# только трекеры с kill_pattern (загрузка, которую вообще можно отменить).
_trackers: Dict[Tuple[str, str], "PullTracker"] = {}
_lock = threading.Lock()

# «a2abf6c4d29d: Downloading [===>   ]  14.24MB/62.51MB» — слой, байты.
_RE_DOWNLOADING = re.compile(
    r"^([0-9a-f]{12,64}): Downloading \[[=>\s]*\]\s*"
    r"([\d.]+)([kMG]?)B/([\d.]+)([kMG]?)B"
)
# «a2abf6c4d29d: Extracting [=>]  32.77MB/62.51MB» — скачивание слоя закончено,
# идёт распаковка: для суммы скачивания слой считается полностью полученным.
_RE_EXTRACTING = re.compile(
    r"^([0-9a-f]{12,64}): Extracting \[[=>\s]*\]"
)
# Завершение слоя: «Download complete» (получен) / «Pull complete» (готов).
_RE_LAYER_DONE = re.compile(
    r"^([0-9a-f]{12,64}): (?:Download complete|Pull complete)"
)

_SUFFIXES = {"": 1, "k": 10 ** 3, "M": 10 ** 6, "G": 10 ** 9}


def _bytes(value: str, suffix: str) -> int:
    """«14.24»+«M» → байты (docker использует десятичные суффиксы)."""
    try:
        return int(float(value) * _SUFFIXES.get(suffix, 1))
    except ValueError:
        return 0


def _format(n: int) -> str:
    """Человекочитаемые байты в стиле docker: 528B / 14.2MB / 1.1GB."""
    for div, suf in ((10 ** 9, "GB"), (10 ** 6, "MB"), (10 ** 3, "kB")):
        if n >= div:
            return f"{n / div:.1f}{suf}"
    return f"{n}B"


class PullTracker:
    """Парсер вывода одной `docker pull` + запись прогресса в реестр.

    Создаётся на каждую загрузку образа; feed() получает строки stdout,
    close() снимает запись из реестра (любой исход — успех или ошибка:
    подробности у задачи, вкладка «Образы» перезагрузится по исчезновению).
    """

    def __init__(self, server_id: str, image: str, ssh=None, server: Optional[dict] = None,
                 kill_pattern: str = ""):
        self.server_id = str(server_id)
        self.image = image
        # Отмена (кнопка ✕): сам трекер знает, как убить загрузку на сервере.
        self.ssh = ssh
        self.server = server or {}
        self.cancelled = False
        # слой -> (скачано, размер); размер 0 = ещё не объявился
        self._layers: Dict[str, Tuple[int, int]] = {}
        self._kill_pattern = ""
        with _lock:
            _active.setdefault(self.server_id, {})[self.image] = self._snapshot()
        # Сеттер: с маркером трекер становится находимым для cancel_pull.
        self.kill_pattern = kill_pattern

    @property
    def kill_pattern(self) -> str:
        """Маркер процесса загрузки для pkill -f (устанавливает images._api_pull).

        Property, а не поле: маркер известен только ВНУТРИ загрузки (какой путь
        выберет диспетчер — API или CLI), то есть уже после создания трекера.
        """
        return self._kill_pattern

    @kill_pattern.setter
    def kill_pattern(self, value: str) -> None:
        self._kill_pattern = value or ""
        with _lock:
            if self._kill_pattern:
                _trackers[(self.server_id, self.image)] = self

    # --- парсинг ---

    def feed(self, line: str) -> None:
        """Одна строка stdout docker pull → обновление состояния слоя.

        CLI без TTY на старых версиях печатает текстовые строки; новые версии
        (29+) прогресс в тексте не отдают вовсе — для них события приходят из
        Docker API через feed_event (см. images._api_pull).
        """
        line = (line or "").strip()
        if not line:
            return
        m = _RE_LAYER_DONE.match(line)
        if m:
            cur, total = self._layers.get(m.group(1), (0, 0))
            self._layers[m.group(1)] = (total or cur, total)
            self._publish()
            return
        m = _RE_EXTRACTING.match(line)
        if m:
            cur, total = self._layers.get(m.group(1), (0, 0))
            self._layers[m.group(1)] = (total or cur, total)
            self._publish()
            return
        m = _RE_DOWNLOADING.match(line)
        if m:
            layer = m.group(1)
            cur = _bytes(m.group(2), m.group(3))
            total = _bytes(m.group(4), m.group(5))
            self._layers[layer] = (cur, total or cur)
            self._publish()

    def feed_event(self, status: str, layer: str,
                   current: Optional[int] = None, total: Optional[int] = None) -> None:
        """Событие Docker API (/images/create, NDJSON) → состояние слоя.

        Нас интересуют «Downloading» (байты) и завершение слоя; Extracting
        для суммы скачивания тоже означает «слой получен целиком».
        """
        status = status or ""
        if not layer:
            return
        if status == "Downloading" and total:
            cur = current or 0
            self._layers[layer] = (min(cur, total), total)
            self._publish()
            return
        if status in ("Download complete", "Pull complete", "Extracting"):
            cur, known = self._layers.get(layer, (0, 0))
            self._layers[layer] = (known or cur, known)
            self._publish()

    # --- агрегат ---

    @property
    def progress(self) -> Tuple[int, str]:
        """(процент 0-100, «текущее / всего»). 0% при неизвестных слоях."""
        cur = sum(c for c, _ in self._layers.values())
        total = sum(t for _, t in self._layers.values())
        if total <= 0:
            return 0, ""
        percent = min(100, round(cur * 100 / total))
        return percent, f"{_format(cur)} / {_format(total)}"

    def mark_cancelled(self) -> None:
        """Пометить загрузку отменённой (вызывает cancel_pull из роутера).

        Снимок сразу показывает «отменяется», а не застывший процент;
        выполняющий задачу код увидит флаг после возврата exec и поднимет
        PullCancelled вместо StepError.
        """
        self.cancelled = True
        self._publish()

    def _snapshot(self) -> Dict[str, Any]:
        percent, detail = self.progress
        return {
            "image": self.image,
            "percent": percent,
            "detail": detail,
            "cancelled": self.cancelled,
        }

    def _publish(self) -> None:
        with _lock:
            per_server = _active.get(self.server_id)
            if per_server is not None and self.image in per_server:
                per_server[self.image] = self._snapshot()

    def close(self) -> None:
        """Убрать запись из реестра (вызов в finally — любой исход задачи)."""
        with _lock:
            _trackers.pop((self.server_id, self.image), None)
            per_server = _active.get(self.server_id)
            if per_server is not None:
                per_server.pop(self.image, None)
                if not per_server:
                    _active.pop(self.server_id, None)


def clear_server(server_id: str) -> None:
    """Снять все записи сервера (страховка на случай падения между шагами)."""
    with _lock:
        _active.pop(str(server_id), None)
        for key in [k for k in _trackers if k[0] == str(server_id)]:
            _trackers.pop(key, None)


def find_tracker(server_id: str, image: str) -> Optional["PullTracker"]:
    """Живой трекер загрузки (server_id, image) — для отмены, None если нет."""
    with _lock:
        return _trackers.get((str(server_id), image))


def snapshot(server_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Снимок активных загрузок: [{image, percent, detail}, ...].

    server_id=None — по всем серверам (для диагностики); эндпоинт вкладки
    «Образы» передаёт конкретный сервер. Читается под локом; наружу отдаются
    копии: _publish заменяет запись целиком, ссылки наружу не утекают.
    """
    with _lock:
        if server_id is None:
            return [dict(e) for per in _active.values() for e in per.values()]
        return [dict(e) for e in _active.get(str(server_id), {}).values()]
