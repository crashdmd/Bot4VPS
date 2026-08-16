# -*- coding: utf-8 -*-
"""Чистый парсинг и нормализация данных о контейнерах Docker (без SSH, без состояния).

Живой сбор (SSH, `docker ps` / `docker stats`) живёт в сервисе
(`service._read_live`); здесь — только детерминированная трансформация текста в
нормализованные dict'ы (как services/wireguard/impl/stats.py). Так парсер
тестируется изолированно, а оба UI (Web и будущий TG) получают один источник.

Формат ввода — по одному JSON-объекту на строку:
    docker ps -a  --format '{{json .}}'   → Names/Image/State/Status/Ports/Labels/ID
    docker stats --no-stream --format '{{json .}}' → Name/CPUPerc/MemUsage/NetIO

Контракт нормализованного контейнера (service обогащает им кэш и live-ответ):

    {
      "name": str, "image": str, "state": str, "status": str,
      "id": str, "managed": bool, "compose_project": str,
      "compose_workdir": str, "ports": [str, ...],
      "cpu": str, "mem": str, "net_in": str, "net_out": str,
    }
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

# Лейбл, которым помечаются созданные ботом контейнеры (managed-флаг из on-disk
# маркера, не из БД — как clients/<name> у WG).
MANAGED_LABEL = "bot4vps.managed"

# Лейблы Compose: по ним контейнер связывается с развёртыванием (project +
# working_dir = игнор-ключ) и скрывается, если проект в игноре
# (docs/compose-model.md §11). working_dir обязателен: у двух одноимённых
# проектов в разных каталогах игнор одного не должен прятать другой (§10).
COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
COMPOSE_WORKDIR_LABEL = "com.docker.compose.project.working_dir"


def _iter_json_lines(text: str):
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except (ValueError, TypeError):
            continue


def _labels_have_managed(labels_raw: str) -> bool:
    """`docker ps` отдаёт Labels строкой «k=v,k2=v2». Ищем bot4vps.managed=true."""
    for pair in (labels_raw or "").split(","):
        pair = pair.strip()
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        if k.strip() == MANAGED_LABEL and v.strip().lower() == "true":
            return True
    return False


def _label_value(labels_raw: str, key: str) -> str:
    """Значение лейбла из строки «k=v,k2=v2» (пусто, если нет)."""
    for pair in (labels_raw or "").split(","):
        pair = pair.strip()
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        if k.strip() == key:
            return v.strip()
    return ""


def _split_ports(ports_raw: str) -> List[str]:
    """Строка Ports из docker ps → список уникальных маппингов (сохраняя порядок)."""
    seen: List[str] = []
    for p in (ports_raw or "").split(","):
        p = p.strip()
        if p and p not in seen:
            seen.append(p)
    return seen


def _extract_published_ports(ports_raw: str) -> List[str]:
    """Все уникальные опубликованные host-порты, сохраняя порядок Docker.

    IPv4/IPv6-публикации одного порта схлопываются. Диапазон публикации
    ``80-81->80-81/tcp`` разворачивается в реальные host-порты 80 и 81.
    """
    import re
    out: List[str] = []
    for mapping in (ports_raw or "").split(","):
        mapping = mapping.strip()
        if "->" not in mapping:
            continue
        host_side = mapping.split("->", 1)[0].strip()
        # Формы Docker: 0.0.0.0:8080, [::]:8080 и :::8080.
        m = re.search(r":(\d+)(?:-(\d+))?$", host_side)
        if not m:
            continue
        start = int(m.group(1))
        end = int(m.group(2) or start)
        if end < start or end - start > 65535:
            continue
        for port in range(start, end + 1):
            value = str(port)
            if value not in out:
                out.append(value)
    return out


def _extract_published_port(ports_raw: str) -> str:
    """Первый опубликованный host-порт (обратная совместимость)."""
    ports = _extract_published_ports(ports_raw)
    return ports[0] if ports else ""


def parse_ps(text: str) -> List[Dict[str, Any]]:
    """Разобрать `docker ps -a --format '{{json .}}'` → список нормализованных
    контейнеров без статистики (cpu/mem/net — нули, дополняются из parse_stats)."""
    out: List[Dict[str, Any]] = []
    for obj in _iter_json_lines(text):
        # Names может быть строкой «a» или «a,b» (docker обычно даёт одно имя).
        name = str(obj.get("Names") or obj.get("Name") or "").split(",")[0].strip()
        if not name:
            continue
        ports_raw = str(obj.get("Ports") or "")
        labels_raw = str(obj.get("Labels") or "")
        out.append({
            "name": name,
            "image": str(obj.get("Image") or "").strip(),
            "state": str(obj.get("State") or "").strip().lower(),
            "status": str(obj.get("Status") or "").strip(),
            "id": str(obj.get("ID") or obj.get("Id") or "").strip()[:12],
            "managed": _labels_have_managed(labels_raw),
            "compose_project": _label_value(labels_raw, COMPOSE_PROJECT_LABEL),
            "compose_workdir": _label_value(labels_raw, COMPOSE_WORKDIR_LABEL),
            "ports": _split_ports(ports_raw),
            "published_ports": _extract_published_ports(ports_raw),
            "published_port": _extract_published_port(ports_raw),
            "cpu": "",
            "mem": "",
            "net_in": "",
            "net_out": "",
        })
    return out


def parse_stats(text: str) -> Dict[str, Dict[str, str]]:
    """Разобрать `docker stats --no-stream --format '{{json .}}'` →
    {name: {cpu, mem, net_in, net_out}}. NetIO вида «1.2kB / 3.4kB» разбивается
    на вход/выход."""
    out: Dict[str, Dict[str, str]] = {}
    for obj in _iter_json_lines(text):
        name = str(obj.get("Name") or obj.get("Names") or "").split(",")[0].strip()
        if not name:
            continue
        net_in = net_out = ""
        netio = str(obj.get("NetIO") or "").strip()
        if "/" in netio:
            a, b = netio.split("/", 1)
            net_in, net_out = a.strip(), b.strip()
        out[name] = {
            "cpu": str(obj.get("CPUPerc") or "").strip(),
            "mem": str(obj.get("MemUsage") or "").strip(),
            "net_in": net_in,
            "net_out": net_out,
        }
    return out


def parse_inspect(text: str) -> Dict[str, Dict[str, Any]]:
    """Разобрать `docker inspect` (JSON-массив) → {id: {started_at}}.

    §3: StartedAt нужен для uptime. docker inspect возвращает массив или ничего;
    если контейнеров нет — пустой dict. Ключ — короткий ID (первые 12 символов).
    """
    out: Dict[str, Dict[str, Any]] = {}
    try:
        arr = json.loads(text or "[]")
        if not isinstance(arr, list):
            return out
        for obj in arr:
            if not isinstance(obj, dict):
                continue
            cid = str(obj.get("Id") or "")[:12]
            state = obj.get("State") or {}
            started = state.get("StartedAt") if isinstance(state, dict) else None
            if cid and started:
                out[cid] = {"started_at": str(started)}
    except (json.JSONDecodeError, ValueError):
        pass
    return out


def build_container_stats(
    ps_list: List[Dict[str, Any]],
    stats_map: Dict[str, Dict[str, str]],
    inspect_map: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Соединить список контейнеров (parse_ps) со статистикой (parse_stats) и
    inspect (parse_inspect) по имени/id. Остановленные контейнеры отсутствуют в
    stats/inspect — получают пустые метрики (не роняем весь read)."""
    for c in ps_list:
        s = stats_map.get(c["name"])
        if s:
            c["cpu"] = s.get("cpu", "")
            c["mem"] = s.get("mem", "")
            c["net_in"] = s.get("net_in", "")
            c["net_out"] = s.get("net_out", "")
        # §3: uptime вычисляем из StartedAt (если контейнер running).
        c["uptime_seconds"] = None
        info = inspect_map.get(c["id"])
        if info and c.get("state") == "running":
            started = info.get("started_at")
            if started:
                try:
                    from datetime import datetime, timezone
                    # StartedAt вида "2026-08-11T13:45:30.123456789Z" или с +00:00
                    st = started.rstrip("Z").split(".")[0]
                    dt = datetime.fromisoformat(st).replace(tzinfo=timezone.utc)
                    now = datetime.now(timezone.utc)
                    c["uptime_seconds"] = int((now - dt).total_seconds())
                except Exception:
                    pass
    return ps_list
