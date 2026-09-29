"""Метрики серверов: сбор, свёртка и чтение рядов (§7 и §10.1 ТЗ).

Разделение обязанностей: ``core/servers.py`` **достаёт** числа (одной
SSH-командой, в составе уже существующей пробы), этот модуль их
**сохраняет**, сворачивает и **отдаёт API**. Никаких собственных
подключений здесь нет и быть не должно: метрика бесплатна ровно потому,
что едет на пробе доступности, которая и так делается каждые 15 минут
(``system_sync``). Второй сбор «для метрик» — это удвоенные SSH-хендшейки
и расхождение двух рядов.

Почему чтение для API живёт здесь, а не в роутере: смысл данных («что
такое разрыв», «что значит ram_pct», «когда шаг часовой») принадлежит
владельцу таблиц. Разложи его по роутерам — UI и SSE начнут толковать
одни и те же точки по-разному и разойдутся молча.

Что модуль обязан соблюдать (§7.4 и §3 ТЗ):

- **неудача пробы — пропуск, а не ноль**: недоступный сервер не должен
  выглядеть простаивающим на графике (ноль нагрузки — это тоже данные);
- **отсутствие данных ≠ 0 и ≠ «не собирается на этом шаге»**: у серии есть
  явный список ``available`` (что шаг умеет отдавать) и явные ``gaps``
  (где данных нет). Пустой массив без них — загадка для UI;
- **время — epoch UTC секундами**, никаких локальных строк;
- **сборщик не падает**: ошибка хранилища логируется внутри ``state_db``
  и возвращает ``False`` — мониторинг доступности от метрик не зависит.

Свёртка (``fold_hours``) — отдельная забота: сырые точки живут 90 дней,
часовые агрегаты 24 месяца (§9). Свёртка идемпотентна (``INSERT OR
REPLACE`` по ``(server_id, hour_ts)``), поэтому её можно звать сколько
угодно раз и в любом порядке — в том числе после простоя.
"""
from __future__ import annotations

import time
from typing import Optional

from core import state_db

# Час в секундах — и единица свёртки, и шаг её водяного знака.
HOUR = 3600

# Источник пробы уезжает в БД строкой: она переживёт переименование
# джобы, а по ``source`` потом видно, откуда взялись точки (этап 2 пишет
# только из system_sync; другие источники — это уже другой ряд).
SOURCE_SYSTEM_SYNC = "system_sync"

# Верхняя граница на один проход свёртки. Нужна не для скорости, а для
# памяти: после долгого простоя (панель не работала 100 дней) свёртка
# может накрыть всю историю сразу, а «худший диск часа» отбирается в
# словаре в памяти. Неделя держит словарь маленьким независимо от
# длительности простоя; INSERT OR REPLACE делает разбиение безопасным.
FOLD_WINDOW = 7 * 24 * HOUR


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _round(value, digits: int):
    return None if value is None else round(float(value), digits)


def record_sample(server: dict, info: dict, *, now: Optional[int] = None) -> bool:
    """Записать одну пробу сервера в ``metric_samples`` (+монтирования).

    ``info`` — возврат ``core.servers.get_server_info``: тот же словарь,
    из которого карточка берёт строки. Числа лежат в ``info["metrics"]``,
    точный uptime — в ``info["uptime_seconds"]`` (его разбор общий с
    карточкой, второй раз секцию 9 не парсим).

    Пропуск (``False``) — это нормальный исход, а не ошибка: сервер не
    ответил, команда сбора не уложилась в таймаут, у сервера нет id.
    Ровно поэтому дыру в ряду потом видно как дыру.
    """
    if not info.get("metrics_ok"):
        return False
    server_id = server.get("id")
    if not server_id:
        print(
            f"[METRICS] проба без server_id пропущена: {server.get('name')}",
            flush=True,
        )
        return False

    metrics = info.get("metrics") or {}
    ts = int(now if now is not None else time.time())
    sample = {
        "server_id": server_id,
        "ts": ts,
        "source": SOURCE_SYSTEM_SYNC,
        "load1": metrics.get("load1"),
        "load5": metrics.get("load5"),
        "load15": metrics.get("load15"),
        "cpu_count": metrics.get("cpu_count"),
        "ram_used_kb": metrics.get("ram_used_kb"),
        "ram_total_kb": metrics.get("ram_total_kb"),
        "swap_used_kb": metrics.get("swap_used_kb"),
        "swap_total_kb": metrics.get("swap_total_kb"),
        "uptime_sec": _int_or_none(info.get("uptime_seconds")),
    }
    # Та же проверка, что ставит metrics_ok при разборе, — но здесь, у самой
    # записи: точка из одних NULL засорила бы ряд, а положиться на флаг
    # вызывающего значит держать инвариант «неудача = пропуск» в другом
    # модуле, где его легко потерять при рефакторинге.
    if sample["load1"] is None or not sample["ram_total_kb"]:
        return False
    # Монтирования приходят уже под колонки metric_disks — дописываем
    # только ключ пробы. Пустой список — тоже данные: если `df` не успел
    # (мёртвый NFS), точки по дискам за этот ts просто не будет, а load и
    # память останутся. Нулей на их месте не появится.
    disks = [
        {**mount, "server_id": server_id, "ts": ts}
        for mount in metrics.get("mounts") or ()
    ]
    return state_db.insert_sample(sample, disks=disks)


# Агрегаты часа. AVG/MAX по load1 и процент памяти считает sqlite, «худший
# монтирование часа» — двумя шагами: MAX по (час, монтирование) здесь,
# выбор максимума между монтированиями в Python. Так имя монтирования
# остаётся привязанным к своему значению — иначе пришлось бы брать
# mount от одной строки, а процент от другой.
#
# CASE WHEN ram_total_kb > 0 — не придирка: деление на NULL даёт NULL, но
# деление на ноль в sqlite даёт NULL только для 0/0, а 100*x/0 → NULL
# тоже, однако явное условие читается как «нет объёма — нет процента».
_SAMPLES_SQL = """
    SELECT (ts / 3600) * 3600 AS hour_ts,
           server_id,
           COUNT(*) AS samples,
           AVG(load1) AS load1_avg,
           MAX(load1) AS load1_max,
           AVG(CASE WHEN ram_total_kb > 0
                    THEN 100.0 * ram_used_kb / ram_total_kb END) AS ram_pct_avg,
           MAX(CASE WHEN ram_total_kb > 0
                    THEN 100.0 * ram_used_kb / ram_total_kb END) AS ram_pct_max
    FROM metric_samples
    WHERE ts >= ? AND ts < ?
    GROUP BY server_id, hour_ts
"""

_DISKS_SQL = """
    SELECT (ts / 3600) * 3600 AS hour_ts,
           server_id,
           mount,
           MAX(used_pct) AS max_pct
    FROM metric_disks
    WHERE ts >= ? AND ts < ? AND used_pct IS NOT NULL
    GROUP BY server_id, hour_ts, mount
"""


def _watermark() -> Optional[int]:
    """С какого часа сворачивать: последний свёрнутый час или начало ряда.

    Последний свёрнутый час берётся **включительно** — он пересвёртывается.
    Это не лишняя работа, а страховка: свёрнутый в середине часа агрегат
    иначе навсегда остался бы неполным, а так следующий проход его
    перезапишет уже полным.
    """
    rows = state_db.query("SELECT MAX(hour_ts) AS last FROM metric_hourly")
    last = rows[0]["last"] if rows else None
    if last is not None:
        return int(last)

    rows = state_db.query("SELECT MIN(ts) AS first FROM metric_samples")
    first = rows[0]["first"] if rows else None
    if first is None:
        return None
    return int(first) // HOUR * HOUR


def _fold_window(since: int, until: int) -> int:
    """Свернуть часы из ``[since, until)``. Возвращает число записей."""
    worst_disks: dict[tuple, tuple] = {}
    for row in state_db.query(_DISKS_SQL, (since, until)):
        key = (row["server_id"], row["hour_ts"])
        worst = worst_disks.get(key)
        if worst is None or row["max_pct"] > worst[0]:
            worst_disks[key] = (row["max_pct"], row["mount"])

    rows = []
    for row in state_db.query(_SAMPLES_SQL, (since, until)):
        worst = worst_disks.get((row["server_id"], row["hour_ts"]))
        rows.append({
            "server_id": row["server_id"],
            "hour_ts": row["hour_ts"],
            "load1_avg": _round(row["load1_avg"], 3),
            "load1_max": _round(row["load1_max"], 3),
            "ram_pct_avg": _round(row["ram_pct_avg"], 2),
            "ram_pct_max": _round(row["ram_pct_max"], 2),
            "disk_max_pct": _round(worst[0], 2) if worst else None,
            "disk_max_mount": worst[1] if worst else None,
            # Сколько сырых точек легло в час. Нужен, чтобы час с одной
            # точкой не выглядел как час плотных измерений: на длинном
            # диапазоне график по среднему без этого врёт.
            "samples": row["samples"],
        })
    return state_db.insert_hourly(rows)


def fold_hours(now: Optional[int] = None) -> int:
    """Свернуть завершённые часы в ``metric_hourly``. Возвращает число записей.

    Текущий (незавершённый) час не сворачивается: он ещё набирает точки,
    а записанный агрегат пришлось бы потом переписывать. Свёртка при этом
    идемпотентна, поэтому повторный вызов в том же часу ничего не портит —
    он лишь перезапишет последний свёрнутый час теми же значениями (или
    более полными, если тот был свёрнут в середине).

    Разбиение на окна — только ради памяти, см. ``FOLD_WINDOW``.

    Граница честности: пересвёртывается только последний свёрнутый час.
    Поздняя запись в более старый уже свёрнутый час попадёт лишь в сырой
    ряд (и исчезнет вместе с ним по ретенции) — при штатной работе такого
    не бывает, потому что ``record_sample`` всегда ставит текущее время,
    а свёртка отстаёт от него меньше чем на час.
    """
    current_hour = int(now if now is not None else time.time()) // HOUR * HOUR
    since = _watermark()
    if since is None or since >= current_hour:
        return 0

    written = 0
    start = since
    while start < current_hour:
        end = min(start + FOLD_WINDOW, current_hour)
        written += _fold_window(start, end)
        start = end
    return written


# --------------------------------------------------------------------------
# Чтение рядов для API (§10.1)
#
# Здесь только sqlite и ничего больше: ни одного подключения к серверам.
# Открытие исторического раздела не должно создавать нагрузку (§10.4) —
# это проверяется тестом, а не обещанием.
# --------------------------------------------------------------------------

# Окна страницы «Мониторинг серверов». Ключи — ровно то, что приходит
# в ?range=; неизвестный диапазон отвергается, а не подменяется молча
# на 24ч: «показали не то, что просили» хуже ошибки.
RANGES: dict[str, int] = {
    "24h": 24 * HOUR,
    "7d": 7 * 24 * HOUR,
    "30d": 30 * 24 * HOUR,
    "90d": 90 * 24 * HOUR,
}
DEFAULT_RANGE = "24h"
DEFAULT_SPARKLINE_POINTS = 48
# Потолок на число точек спарклайна: ?sparkline_points=100000 — это не
# желание разглядеть детали, а способ положить панель.
MAX_SPARKLINE_POINTS = 720

# Шаг auto: до этой длины окна точка графика — сырая проба, дальше час.
# 7 суток = 672 точки на сервер; сырее уже не читается глазом, а JSON
# выходит вчетверо толще.
AUTO_RAW_LIMIT = 7 * 24 * HOUR

# Разрыв — просвет больше полутора номинальных интервалов. Полтора, а не
# «больше одного»: расписание сбора дышит на секунды, и рвать линию на
# каждом вздохе нельзя. Один пропущенный такт (30 минут вместо 15) при
# этом уже виден.
GAP_FACTOR = 1.5

# Причина разрыва. В БД её нет и быть не может: таблица хранит только то,
# что удалось собрать, а «почему не собралось» знает момент сбора (§10.1
# в примере пишет "no_ssh", §10.3 — то же самое). Поэтому причина одна и
# честная: данных нет. Разложить её на «нет SSH / офлайн / backoff» может
# только тот, кто видел попытку, — журнал и события доступности, и это
# работа таймлайна (§10.3), а не ряда.
GAP_REASON = "no_data"

# stale — точки старше двух интервалов сбора: одна пропущенная проба
# (backoff, перезапуск панели) ещё не повод красить сервер тревожно.
STALE_FACTOR = 2


def _ram_pct(used_kb, total_kb):
    """Процент занятой памяти или None. Нет объёма — нет процента (§7.4)."""
    if not total_kb or used_kb is None:
        return None
    return round(100.0 * used_kb / total_kb, 1)


def _append(series: list, ts, value) -> None:
    """Дописать точку, если значение существует.

    NULL в ряду — не точка: пропущенное значение не должно становиться
    нулём на графике. Проверка стоит на каждой серии отдельно, поэтому
    пустая память одной пробы не выбивает из её же load1 точку.
    """
    if value is not None:
        series.append([int(ts), value])


def sample_interval() -> int:
    """Номинальный интервал сырых точек — он же расписание сбора.

    Берётся из ``core.monitor``, а не дублируется числом: и разрыв, и
    статус «свежих данных нет» определены через этот интервал, и при его
    изменении определение должно поехать следом, а не разойтись молча.
    Импорт внутри функции — чтобы не тянуть SSH-стек в модуль на импорте.
    """
    from core.monitor import SYSTEM_SYNC_INTERVAL_MIN

    return int(SYSTEM_SYNC_INTERVAL_MIN) * 60


def bucket_seconds(window: int, points: int) -> int:
    """Ширина корзины спарклайна: окно, поделённое на число точек."""
    points = _int_or_none(points) or DEFAULT_SPARKLINE_POINTS
    points = max(1, min(points, MAX_SPARKLINE_POINTS))
    return max(1, int(window) // points)


def _gaps(stamps, nominal: int, since=None, until=None, now=None) -> list:
    """Разрывы ряда по отметкам времени точек.

    Разрыв — любой просвет без точек внутри окна: и между точками, и на
    **краях**. Пропущенный край — такой же факт, как пропущенная середина:
    если в суточном окне единственная точка стоит в самом конце, значит
    сбор начался только что, и график обязан показать это пропуском, а не
    пустотой — пустой участок без разрыва не отличить от «данных нет, но
    всё хорошо». Границей разрыва служит граница окна, а конец обрезается
    по текущему моменту (``now``): окно, запрошенное в будущее, не должно
    превращаться в разрыв там, где ещё ничего не должно было случиться.

    Края считаются разрывом только при известном окне (``since``/``until``)
    — без него ряд говорит лишь о том, что видит.
    """
    hole = nominal * GAP_FACTOR
    edge_to = until
    if until is not None and now is not None:
        edge_to = min(int(until), int(now))
    gaps = []
    if not stamps:
        if since is not None and edge_to is not None and int(since) < edge_to:
            gaps.append({"from": int(since), "to": edge_to, "reason": GAP_REASON})
        return gaps
    if since is not None and int(stamps[0]) - int(since) > hole:
        gaps.append({"from": int(since), "to": int(stamps[0]), "reason": GAP_REASON})
    for prev, cur in zip(stamps, stamps[1:]):
        if cur - prev > hole:
            gaps.append({"from": int(prev), "to": int(cur), "reason": GAP_REASON})
    if edge_to is not None and edge_to - int(stamps[-1]) > hole:
        gaps.append({"from": int(stamps[-1]), "to": edge_to, "reason": GAP_REASON})
    return gaps


def _triples(gaps: list) -> list:
    """Разрывы списком троек — форма, которую задаёт §10.1 для overview."""
    return [[gap["from"], gap["to"], gap["reason"]] for gap in gaps]


def _worst_disk(disks) -> tuple:
    """Худшее монтирование списка: (процент, имя) — имя при своём числе."""
    worst = None
    for disk in disks:
        pct = _round(disk.get("used_pct"), 1)
        if pct is None:
            continue
        if worst is None or pct > worst[0]:
            worst = (pct, disk.get("mount"))
    return worst if worst else (None, None)


def _system_disk(disks) -> Optional[dict]:
    """Запись системного раздела `/` из одной пробы, если она есть."""
    return next((disk for disk in disks if disk.get("mount") == "/"), None)


def _status(last_ts, online, now: int, interval: int) -> str:
    """ok | stale | unreachable.

    ``unreachable`` — по данным пробы доступности, а не по метрикам: факт
    «не отвечает» знает она, и он свежее возраста последней точки.
    Сервер без единой точки — ``stale``, а не ``unreachable``: «не
    отвечает» без попытки утверждать нельзя, а «свежих данных нет» —
    правда.
    """
    if online is False:
        return "unreachable"
    if last_ts is None or int(now) - int(last_ts) > interval * STALE_FACTOR:
        return "stale"
    return "ok"


def last_sample(server_id: str) -> Optional[dict]:
    """Последняя проба сервера из БД, вместе с монтированиями.

    Историческая опора для карточки (§10.1): живые числа даёт
    существующий ``/api/servers/{id}/metrics``, а этот — что успело
    лечь в базу. SSH здесь не нужен и не делается.
    """
    rows = state_db.query(
        f"SELECT {', '.join(state_db.SAMPLE_COLUMNS)} FROM metric_samples "
        "WHERE server_id = ? ORDER BY ts DESC LIMIT 1",
        (server_id,),
    )
    if not rows:
        return None
    sample = dict(rows[0])
    sample["ram_pct"] = _ram_pct(sample.get("ram_used_kb"), sample.get("ram_total_kb"))
    disks = state_db.iter_disks(server_id, since=sample["ts"], until=sample["ts"])
    for disk in disks:
        disk["used_pct"] = _round(disk.get("used_pct"), 1)
    sample["disks"] = disks
    return sample


def latest(server_id: str, *, now=None) -> dict:
    """Последняя проба для карточки (§10.1), без SSH."""
    sample = last_sample(server_id)
    if sample is None:
        # Пустой ответ, а не ответ с нулями: «точек ещё нет» и «нагрузка
        # ноль» — разные утверждения, и показать второе вместо первого
        # значит соврать про сервер, который ещё ни разу не ответил.
        return {"server_id": server_id, "ts": None, "age_sec": None,
                "sample": None, "disks": []}
    now = int(now if now is not None else time.time())
    return {
        "server_id": server_id,
        "ts": sample["ts"],
        "age_sec": max(0, now - int(sample["ts"])),
        "sample": {
            "source": sample.get("source"),
            "load1": _round(sample.get("load1"), 3),
            "load5": _round(sample.get("load5"), 3),
            "load15": _round(sample.get("load15"), 3),
            "cpu_count": sample.get("cpu_count"),
            "ram_used_kb": sample.get("ram_used_kb"),
            "ram_total_kb": sample.get("ram_total_kb"),
            "ram_pct": sample.get("ram_pct"),
            "swap_used_kb": sample.get("swap_used_kb"),
            "swap_total_kb": sample.get("swap_total_kb"),
            "uptime_sec": sample.get("uptime_sec"),
        },
        # ts и server_id здесь не повторяются — они в родителе.
        "disks": [
            {
                "mount": disk.get("mount"),
                "fs": disk.get("fs"),
                "used_kb": disk.get("used_kb"),
                "total_kb": disk.get("total_kb"),
                "used_pct": disk.get("used_pct"),
            }
            for disk in sample["disks"]
        ],
    }


# Спарклайн списка: корзина одна на весь ответ, поэтому одна пара запросов
# на все серверы, а не по запросу на сервер. Числитель и знаменатель
# взвешенного среднего берутся из samples: у часов с разным числом проб
# равный вес соседей дал бы среднее «по часам», а не «по времени».
_SPARK_RAW_SQL = """
    SELECT server_id,
           (ts / ?) * ? AS bucket_ts,
           COUNT(*) AS samples,
           AVG(load1) AS load1,
           AVG(CASE WHEN ram_total_kb > 0
                    THEN 100.0 * ram_used_kb / ram_total_kb END) AS ram_pct
    FROM metric_samples
    WHERE ts >= ? AND ts <= ?
    GROUP BY server_id, bucket_ts
    ORDER BY bucket_ts
"""

_SPARK_RAW_DISK_SQL = """
    SELECT server_id,
           (ts / ?) * ? AS bucket_ts,
           MAX(used_pct) AS disk_max_pct
    FROM metric_disks
    WHERE ts >= ? AND ts <= ? AND used_pct IS NOT NULL
    GROUP BY server_id, bucket_ts
    ORDER BY bucket_ts
"""

_SPARK_HOUR_SQL = """
    SELECT server_id,
           (hour_ts / ?) * ? AS bucket_ts,
           SUM(samples) AS samples,
           SUM(load1_avg * samples) / SUM(samples) AS load1,
           SUM(ram_pct_avg * samples) / SUM(samples) AS ram_pct,
           MAX(disk_max_pct) AS disk_max_pct
    FROM metric_hourly
    WHERE hour_ts >= ? AND hour_ts <= ?
    GROUP BY server_id, bucket_ts
    ORDER BY bucket_ts
"""


def _sparklines(since: int, until: int, bucket: int, step: str) -> dict:
    """Спарклайны всех серверов окна: ``{server_id: {...}}``.

    ``buckets`` — отметки корзин, в которых были пробы. По ним считается
    разрыв: если корзина не набралась, точки в ней нет, и линия рвётся
    ровно там, где данных не было. Монтирования в этот список не
    добавляются: они пишутся одной транзакцией с пробой, поэтому дыр
    сверх уже учтённых у них не бывает.
    """
    data: dict[str, dict] = {}

    def slot(server_id: str) -> dict:
        return data.setdefault(server_id, {
            "load1": [], "ram_pct": [], "disk_max_pct": [], "buckets": [],
        })

    if step == "raw":
        for row in state_db.query(_SPARK_RAW_SQL, (bucket, bucket, since, until)):
            item = slot(row["server_id"])
            item["buckets"].append(int(row["bucket_ts"]))
            _append(item["load1"], row["bucket_ts"], _round(row["load1"], 3))
            _append(item["ram_pct"], row["bucket_ts"], _round(row["ram_pct"], 1))
        for row in state_db.query(_SPARK_RAW_DISK_SQL, (bucket, bucket, since, until)):
            item = slot(row["server_id"])
            _append(item["disk_max_pct"], row["bucket_ts"], _round(row["disk_max_pct"], 1))
    else:
        for row in state_db.query(_SPARK_HOUR_SQL, (bucket, bucket, since, until)):
            item = slot(row["server_id"])
            item["buckets"].append(int(row["bucket_ts"]))
            _append(item["load1"], row["bucket_ts"], _round(row["load1"], 3))
            _append(item["ram_pct"], row["bucket_ts"], _round(row["ram_pct"], 1))
            _append(item["disk_max_pct"], row["bucket_ts"], _round(row["disk_max_pct"], 1))
    return data


def overview(servers, availability=None, *, range_key: str = DEFAULT_RANGE,
             points: Optional[int] = None, now=None) -> dict:
    """Данные списка «Мониторинг серверов» (§10.1) — одним ответом.

    ``servers`` и ``availability`` передаются снаружи: серверы приходят из
    конфигурации, доступность — из monitor.json, и читать файлы этот
    модуль не должен (он владеет таблицами, а не файлами панели).
    ``points=None`` — умолчание ``DEFAULT_SPARKLINE_POINTS``.

    В список попадают **все** настроенные серверы, включая те, по которым
    точек нет: строка «данных пока нет» и строка «данных нет уже час» —
    разные состояния, и оба нужны на экране. Сервер без данных с нулевым
    load1 вместо пустоты выглядел бы работающим.
    """
    window = RANGES.get(str(range_key))
    if window is None:
        raise ValueError(f"range: {range_key}")
    availability = availability or {}
    until = int(now if now is not None else time.time())
    since = until - window
    # Шаг выбирается по длине окна, а не по наличию точек: дольше ретенции
    # сырых проб в БД их нет, и «дырка» в начале такого окна была бы не
    # пропуском сбора, а отсутствием самого ряда — разными вещами.
    step = "raw" if window <= AUTO_RAW_LIMIT else "hour"
    bucket = bucket_seconds(window, points)
    interval = sample_interval()
    sparks = _sparklines(since, until, bucket, step)

    items = []
    for server in servers:
        server_id = server.get("id")
        if not server_id:
            continue
        spark = sparks.get(server_id) or {
            "load1": [], "ram_pct": [], "disk_max_pct": [], "buckets": [],
        }
        sample = last_sample(server_id)
        last = None
        if sample is not None:
            disk = _system_disk(sample["disks"])
            last = {
                "load1": _round(sample.get("load1"), 3),
                "cpu_count": _int_or_none(sample.get("cpu_count")),
                "ram_used_kb": sample.get("ram_used_kb"),
                "ram_total_kb": sample.get("ram_total_kb"),
                "ram_pct": sample.get("ram_pct"),
                "disk_pct": _round(disk.get("used_pct"), 1) if disk else None,
                "disk_used_kb": disk.get("used_kb") if disk else None,
                "disk_total_kb": disk.get("total_kb") if disk else None,
                "disk_mount": disk.get("mount") if disk else None,
                "uptime_sec": sample.get("uptime_sec"),
            }
        online = (availability.get(server_id) or {}).get("online")
        items.append({
            "server_id": server_id,
            "server_name": server.get("name"),
            "last_ts": sample["ts"] if sample else None,
            "last": last,
            "sparkline": {
                "load1": spark["load1"],
                "ram_pct": spark["ram_pct"],
                "disk_max_pct": spark["disk_max_pct"],
            },
            "status": _status(sample["ts"] if sample else None, online, until, interval),
            "gaps": _triples(_gaps(spark["buckets"], bucket, since=since,
                                   until=until, now=until)),
        })
    return {
        "range": str(range_key),
        # step и границы — добавка к §10.1: ответ описывает сам себя, и UI
        # не гадает, усреднены ли точки по часу и какое окно посчитано.
        "step": step,
        "from": since,
        "to": until,
        "sparkline_seconds": bucket,
        "servers": items,
    }


_HOUR_SERIES_SQL = """
    SELECT hour_ts, load1_avg, ram_pct_avg, disk_max_pct, disk_max_mount, samples
    FROM metric_hourly
    WHERE server_id = ? AND hour_ts >= ? AND hour_ts <= ?
    ORDER BY hour_ts
"""


def _disk_series(rows) -> tuple:
    """Ряд по монтированиям и «худшее в пробе» из строк ``metric_disks``.

    Возвращает ``(disks, worst)``: ``disks`` — список монтирований,
    ``worst`` — ``{ts: (процент, имя)}`` по каждой пробе.

    Имя монтирования держится при своём числе: максимум по пробам берётся
    вместе с тем монтированием, которое его дало, иначе «78%» потеряло бы
    ответ «где».
    """
    by_mount: dict = {}
    worst: dict = {}
    for row in rows:
        ts = int(row["ts"])
        mount = row.get("mount")
        entry = by_mount.get(mount)
        if entry is None:
            entry = by_mount[mount] = {"mount": mount, "fs": row.get("fs"), "points": []}
        elif not entry.get("fs"):
            entry["fs"] = row.get("fs")
        pct = _round(row.get("used_pct"), 1)
        if pct is None:
            continue
        entry["points"].append([ts, pct])
        current = worst.get(ts)
        if current is None or pct > current[0]:
            worst[ts] = (pct, mount)
    return list(by_mount.values()), worst


def _raw_values(rows: list[dict], disk_rows: list[dict]) -> dict:
    """Сопоставить сырые абсолютные значения по timestamp без интерполяции."""
    values: dict[str, dict] = {}
    for row in rows:
        ts = int(row["ts"])
        values[str(ts)] = {
            "sample_ts": ts,
            "source": row.get("source") or "system_sync",
            "load1": _round(row.get("load1"), 3),
            "cpu_count": _int_or_none(row.get("cpu_count")),
            "ram_used_kb": row.get("ram_used_kb"),
            "ram_total_kb": row.get("ram_total_kb"),
            "ram_pct": _ram_pct(row.get("ram_used_kb"), row.get("ram_total_kb")),
            "uptime_sec": _int_or_none(row.get("uptime_sec")),
            "disks": {},
        }
    for disk in disk_rows:
        ts = int(disk["ts"])
        value = values.get(str(ts))
        if value is None:
            continue
        mount = disk.get("mount")
        if not mount:
            continue
        value["disks"][str(mount)] = {
            "mount": mount,
            "used_kb": disk.get("used_kb"),
            "total_kb": disk.get("total_kb"),
            "used_pct": _round(disk.get("used_pct"), 1),
        }
    return values


def _regular_reading(row: dict) -> dict:
    return {
        "row": {**row, "source": "system_sync"},
        "source": "system_sync",
        "operation_id": None,
    }


def _peak_reading(peak: dict) -> dict:
    return {
        "row": {
            **peak,
            "ts": int(peak["captured_ts"]),
            "source": "operation_peak",
        },
        "source": "operation_peak",
        "operation_id": str(peak["operation_id"]),
    }


def _select_raw_context(regular: Optional[dict], peak: Optional[dict], *, left: bool) -> Optional[dict]:
    candidates = [candidate for candidate in (regular, peak) if candidate is not None]
    if not candidates:
        return None
    if left:
        timestamp = max(int(candidate["ts"] if "ts" in candidate else candidate["captured_ts"])
                        for candidate in candidates)
    else:
        timestamp = min(int(candidate["ts"] if "ts" in candidate else candidate["captured_ts"])
                        for candidate in candidates)
    at_timestamp = [candidate for candidate in candidates
                    if int(candidate["ts"] if "ts" in candidate else candidate["captured_ts"])
                    == timestamp]
    peak_candidate = next((candidate for candidate in at_timestamp if "operation_id" in candidate), None)
    return _peak_reading(peak_candidate) if peak_candidate is not None else _regular_reading(at_timestamp[0])


def _raw_context_reading(
    server_id: str,
    *,
    lower: int,
    boundary: int,
    upper: int,
    left: bool,
) -> tuple[Optional[dict], list[dict]]:
    if left:
        regular = state_db.sample_predecessor(server_id, lower=lower, before=boundary)
        peak = state_db.operation_metric_peak_predecessor(
            server_id, lower=lower, before=boundary,
        )
    else:
        regular = state_db.sample_successor(server_id, after=boundary, upper=upper)
        peak = state_db.operation_metric_peak_successor(server_id, after=boundary, upper=upper)
    reading = _select_raw_context(regular, peak, left=left)
    if reading is None:
        return None, []
    ts = int(reading["row"]["ts"])
    if reading["source"] == "system_sync":
        return reading, state_db.iter_disks(server_id, since=ts, until=ts)
    disks = state_db.operation_metric_peak_disks(str(reading["operation_id"]))
    return reading, [{**disk, "ts": ts} for disk in disks]


def _raw_readings(server_id: str, *, since: int, until: int) -> tuple[list[dict], list[dict]]:
    """Объединить целые regular/peak snapshots для точного raw-вида.

    Коллизия времени выбирает peak, а между несколькими peak — меньший producer
    operation ID. Выбор всегда относится к одному фактическому snapshot и не
    меняет исходные регулярные записи в хранилище.
    """
    regular_rows = state_db.iter_samples(server_id, since=since, until=until)
    regular_disks = state_db.iter_disks(server_id, since=since, until=until)
    selected: dict[int, dict] = {}
    disks_by_ts: dict[int, list[dict]] = {}
    for row in regular_rows:
        ts = int(row["ts"])
        selected[ts] = _regular_reading(row)
    for disk in regular_disks:
        disks_by_ts.setdefault(int(disk["ts"]), []).append(disk)

    for peak in state_db.iter_operation_metric_peaks(server_id, since=since, until=until):
        ts = int(peak["captured_ts"])
        candidate = _peak_reading(peak)
        previous = selected.get(ts)
        if (
            previous is not None
            and previous["source"] == "operation_peak"
            and str(previous["operation_id"]) <= str(candidate["operation_id"])
        ):
            continue
        selected[ts] = candidate

    rows: list[dict] = []
    disk_rows: list[dict] = []
    for ts, reading in sorted(selected.items()):
        rows.append(reading["row"])
        if reading["source"] == "system_sync":
            disk_rows.extend(disks_by_ts.get(ts, ()))
            continue
        for disk in reading["row"].get("disks") or ():
            disk_rows.append({**disk, "ts": ts})
    return rows, disk_rows


def _raw_context(
    server_id: str,
    *,
    retention_from: int,
    effective_from: int,
    until: int,
    now: int,
) -> tuple[list[dict], list[dict]]:
    left, left_disks = _raw_context_reading(
        server_id,
        lower=retention_from,
        boundary=effective_from,
        upper=until,
        left=True,
    )
    right, right_disks = _raw_context_reading(
        server_id,
        lower=retention_from,
        boundary=until,
        upper=now,
        left=False,
    )
    readings = [reading for reading in (left, right) if reading is not None]
    readings.sort(key=lambda reading: int(reading["row"]["ts"]))
    return [reading["row"] for reading in readings], left_disks + right_disks


def series(server_id: str, *, since=None, until=None, step: str = "auto",
           now=None, line_context: bool = False) -> dict:
    """Ряд одного сервера для графика (§10.1). Только чтение БД, без SSH.

    Шаги: ``raw`` — сырые пробы (до 90 дней ретенции), ``hour`` — часовая
    свёртка (24 месяца), ``auto`` — сырые до недели, дальше час.

    Границы в ответе — **фактические**, а не запрошенные: сырых проб
    старше ретенции в БД нет, и отдать вместо них пустоту значило бы
    показать отсутствие данных там, где их не хранят вовсе. Клиент видит
    фактическое окно в ``from``/``to`` и отличает одно от другого.
    """
    if step not in ("auto", "raw", "hour"):
        raise ValueError(f"step: {step}")
    moment = int(now if now is not None else time.time())
    until = int(until if until is not None else moment)
    since = int(since if since is not None else until - RANGES[DEFAULT_RANGE])
    if since > until:
        raise ValueError("from: больше to")
    if step == "auto":
        step = "raw" if until - since <= AUTO_RAW_LIMIT else "hour"

    interval = sample_interval()
    if step == "raw":
        limit = state_db.RAW_METRICS_DAYS * 86400
        retention_from = until - limit
        effective_from = max(since, retention_from)
        rows, disk_rows = _raw_readings(
            server_id,
            since=effective_from,
            until=until,
        )
        if line_context:
            context_rows, context_disks = _raw_context(
                server_id,
                retention_from=retention_from,
                effective_from=effective_from,
                until=until,
                now=moment,
            )
            rows = sorted(context_rows + rows, key=lambda row: int(row["ts"]))
            disk_rows = sorted(context_disks + disk_rows,
                               key=lambda row: (int(row["ts"]), str(row.get("mount") or "")))
        stamps = [int(row["ts"]) for row in rows]
        load1: list = []
        ram_pct: list = []
        uptime: list = []
        for row in rows:
            ts = int(row["ts"])
            _append(load1, ts, _round(row.get("load1"), 3))
            _append(ram_pct, ts, _ram_pct(row.get("ram_used_kb"), row.get("ram_total_kb")))
            _append(uptime, ts, _int_or_none(row.get("uptime_sec")))
        disks, worst = _disk_series(disk_rows)
        raw_values = _raw_values(rows, disk_rows)
        disk_stamps = sorted(worst)
        disk_max_pct = [[ts, worst[ts][0]] for ts in disk_stamps]
        disk_labels = [[ts, worst[ts][1]] for ts in disk_stamps]
        available = {"load1": True, "ram_pct": True, "uptime_sec": True,
                     "disks": True, "disk_max_pct": True}
    else:
        limit = state_db.HOURLY_METRICS_MONTHS * 30 * 86400
        effective_from = max(since, until - limit)
        rows = state_db.query(_HOUR_SERIES_SQL, (server_id, effective_from, until))
        if line_context:
            predecessor = state_db.hourly_predecessor(
                server_id,
                lower=until - limit,
                before=effective_from,
            )
            successor = state_db.hourly_successor(
                server_id,
                after=until,
                upper=moment,
            )
            rows = sorted(
                [row for row in (predecessor, *rows, successor) if row is not None],
                key=lambda row: int(row["hour_ts"]),
            )
        stamps = [int(row["hour_ts"]) for row in rows]
        load1 = []
        ram_pct = []
        # Часовой свёртки нет у uptime (агрегировать «сколько работал» по
        # среднему — бессмыслица), и монтирований в ней тоже нет: в часе
        # живёт только худшее. Шаг, который чего-то не умеет, говорит об
        # этом в available, а не отдаёт пустой массив без объяснений.
        uptime = []
        disks = []
        disk_max_pct = []
        disk_labels = []
        for row in rows:
            ts = int(row["hour_ts"])
            _append(load1, ts, _round(row.get("load1_avg"), 3))
            _append(ram_pct, ts, _round(row.get("ram_pct_avg"), 1))
            pct = _round(row.get("disk_max_pct"), 1)
            if pct is not None:
                disk_max_pct.append([ts, pct])
                disk_labels.append([ts, row.get("disk_max_mount")])
        disk_stamps = [ts for ts, _ in disk_max_pct]
        raw_values = {}
        available = {"load1": True, "ram_pct": True, "uptime_sec": False,
                     "disks": False, "disk_max_pct": True}

    return {
        "server_id": server_id,
        "step": step,
        "from": effective_from,
        "to": until,
        "series": {
            "load1": load1,
            "ram_pct": ram_pct,
            "uptime_sec": uptime,
            # Добавка к §10.1, но ровно та форма, что у таймлайна (§10.3):
            # «худшее монтирование» на длинном окне нужно графику, а в
            # часовой свёртке оно и хранится.
            "disk_max_pct": disk_max_pct,
        },
        "disks": disks,
        "gaps": _gaps(stamps, HOUR if step == "hour" else interval,
                      since=effective_from, until=until, now=moment),
        # Дыры дискового ряда отдельным списком: монтирования приходят
        # одним `df`, поэтому дыра у них общая — когда `df` не успел,
        # точки по дискам нет, а проба (load, память) на месте. Без этого
        # списка линия диска соединила бы края такой дыры насквозь.
        "disk_gaps": _gaps(disk_stamps, HOUR if step == "hour" else interval,
                           since=effective_from, until=until, now=moment),
        # Имя монтирования к каждому числу в series.disk_max_pct: на
        # часовом шаге монтирование между точками может меняться, и без
        # подписи «78%» осталось бы без ответа «чего».
        "labels": {"disk_max_pct": disk_labels},
        "available": available,
        # Absolute values are meaningful only at raw sample timestamps. The
        # hourly table stores percentages and mount labels, not capacities.
        "raw_values": raw_values,
        "raw_values_available": step == "raw",
    }


# Хвост новых проб для SSE (§11). Записи компактные — по строке виджета
# на сервер: параметров, выводов задач и прочего, что не влезет в поток
# раз в 3 секунды, здесь нет.
_TAIL_SQL = """
    SELECT s.server_id, s.ts, s.load1, s.cpu_count, s.ram_used_kb, s.ram_total_kb,
           d.used_pct AS disk_pct, d.used_kb AS disk_used_kb,
           d.total_kb AS disk_total_kb, d.mount AS disk_mount
    FROM metric_samples s
    LEFT JOIN metric_disks d
      ON d.server_id = s.server_id AND d.ts = s.ts AND d.mount = '/'
    WHERE s.ts > ?
    ORDER BY s.ts, s.server_id
    LIMIT ?
"""


def tail_since(ts: int, limit: int = 200) -> list:
    """Пробы новее ``ts`` — для ``event: metrics`` в SSE (§11).

    Не шина в памяти, а водяной знак по таблице: пробы пишет любой из
    трёх процессов панели (web, Telegram, CLI), и внутрипроцессная шина
    половину из них не увидела бы. Чтение идёт по индексу (server_id, ts),
    раз в такт и независимо от числа клиентов.

    ``limit`` — не только про память: если за время простоя накопился
    большой хвост, отдаём первые двести записей, а не весь. Водяной знак
    вызывающего двинется по последней отданной, и следующий такт заберёт
    остальное — потерять их так нельзя, пока на одну секунду не приходится
    больше двухсот проб (в panel'е серверов на порядок меньше).
    """
    rows = state_db.query(_TAIL_SQL, (int(ts), int(limit)))
    out = []
    for row in rows:
        out.append({
            "server_id": row["server_id"],
            "ts": int(row["ts"]),
            "load1": _round(row.get("load1"), 3),
            "cpu_count": _int_or_none(row.get("cpu_count")),
            "ram_used_kb": row.get("ram_used_kb"),
            "ram_total_kb": row.get("ram_total_kb"),
            "ram_pct": _ram_pct(row.get("ram_used_kb"), row.get("ram_total_kb")),
            "disk_pct": _round(row.get("disk_pct"), 1),
            "disk_used_kb": row.get("disk_used_kb"),
            "disk_total_kb": row.get("disk_total_kb"),
            "disk_mount": row.get("disk_mount"),
        })
    return out


def last_ts() -> Optional[int]:
    """Время самой свежей пробы в БД; None — данных нет.

    Точка отсчёта для SSE при подключении клиента: поток отдаёт только
    новое, и без этого знака первый же такт высыпал бы в браузер всю
    историю.
    """
    rows = state_db.query("SELECT MAX(ts) AS last FROM metric_samples")
    last = rows[0]["last"] if rows else None
    return None if last is None else int(last)
