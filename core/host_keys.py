# -*- coding: utf-8 -*-
"""SSH host key verification (security hardening 5.1).

Единственный механизм против MITM-подмены сервера: до 5.1 панель
принимала любой host key молча (AutoAddPolicy без known_hosts), и при
каждом подключении (включая ядерный 15-минутный monitor-сбор) пароли
серверов уходили бы подменённому хосту.

Модель:
  * в servers.json у сервера хранится ``host_key`` — тип ключа, base64
    публичного ключа и fingerprint (SHA256, формат OpenSSH). Хранится
    именно ключ, а не голый отпечаток: коллизии/путаница алгоритмов
    исключены, ключ восстановим для сверки;
  * верификация — в единственной точке входа ``core.ssh.create_ssh_client``
    (все 70+ вызовов наследуют слой, CAS/QS verify-before-commit не
    тронуты);
  * записи нет → TOFU: первый коннект принимает ключ и записывает его
    на диск (через storage-хелпер под общим data_lock);
  * запись есть, ключ совпал → подключение;
  * запись есть, ключ НЕ совпал → отказ ДО аутентификации (пароль не
    отправляется) + CRITICAL-событие в журнал (с анти-спамом: одно
    сообщение на сервер до принятия решения).

Явное «сервер переустановлен, принять новый ключ» — отдельный поток
(Web API / CLI), см. ``core.ssh.accept_new_host_key``.
"""
from __future__ import annotations

import base64
import hashlib
from typing import Any, Optional

import paramiko

# Классы paramiko для восстановления PKey из сохранённого blob. Порядок
# не критичен: каждый класс отвергает чужой формат данных. DSS убран из
# paramiko 5.x — старые ssh-dss записи просто не восстановятся (а сами
# ключи ssh-dss современными серверами не принимаются).
_PKEY_CLASSES = (
    paramiko.Ed25519Key,
    paramiko.ECDSAKey,
    paramiko.RSAKey,
)


class HostKeyMismatchError(Exception):
    """Сервер предъявил host key, отличный от сохранённого.

    Поднимается ДО аутентификации: учётные данные не покидают панель.
    """

    def __init__(
        self,
        server_name: str,
        expected_fingerprint: str,
        presented_fingerprint: str,
    ):
        self.server_name = server_name
        self.expected_fingerprint = expected_fingerprint
        self.presented_fingerprint = presented_fingerprint
        super().__init__(
            f"Host key сервера «{server_name}» не совпадает с сохранённым "
            f"(ожидался {expected_fingerprint}, получен {presented_fingerprint}). "
            "Если сервер переустановлен — примите новый ключ "
            "в карточке сервера."
        )


def fingerprint_of(pkey: paramiko.PKey) -> str:
    """Fingerprint в формате OpenSSH (ssh-keygen -l): SHA256 без padding."""
    digest = hashlib.sha256(pkey.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).rstrip(b"=").decode("ascii")


def record_from_pkey(pkey: paramiko.PKey) -> dict:
    """Сохраняемая запись о host key сервера."""
    return {
        "type": pkey.get_name(),
        "key": base64.b64encode(pkey.asbytes()).decode("ascii"),
        "fingerprint": fingerprint_of(pkey),
    }


def pkey_from_record(record: Any) -> Optional[paramiko.PKey]:
    """Восстановить PKey из записи (для тестов и внешних сверок)."""
    if not isinstance(record, dict):
        return None
    b64 = record.get("key")
    if not isinstance(b64, str) or not b64:
        return None
    try:
        blob = base64.b64decode(b64, validate=True)
    except Exception:
        return None
    for cls in _PKEY_CLASSES:
        try:
            return cls(data=blob)
        except Exception:
            continue
    return None


def records_match(stored: Any, presented: dict) -> bool:
    """Совпадение записи и предъявленного ключа: тип + сам ключ."""
    return (
        isinstance(stored, dict)
        and stored.get("type") == presented.get("type")
        and stored.get("key") == presented.get("key")
    )


def stored_record(server: dict) -> Optional[dict]:
    """Валидная сохранённая запись host key сервера (или None)."""
    record = server.get("host_key") if isinstance(server, dict) else None
    if isinstance(record, dict) and record.get("key") and record.get("type"):
        return record
    return None


# ------------------------------------------------------------------
# События журнала
# ------------------------------------------------------------------

# Анти-спам: одно CRITICAL-уведомление о mismatch на сервер до принятия
# решения (иначе ядерный monitor-сбор каждые 15 минут зальёт журнал).
_mismatch_reported: set[str] = set()


def reset_mismatch_report(server_id) -> None:
    _mismatch_reported.discard(str(server_id))


def _emit_event(level_name: str, title: str, message: str, details: dict) -> None:
    """Синхронная запись события (потоки monitor/QS — не async-контекст)."""
    try:
        from core.event_service import create_event
        from core.event_types import EventLevel, EventType

        create_event(
            event_type=EventType.SSH,
            level=EventLevel(level_name),
            title=title,
            message=message,
            details=details,
            notify=True,
        )
    except Exception as exc:  # журнал не должен ломать SSH-подключение
        print(f"[HOSTKEY] событие не записано: {exc}", flush=True)


def _event_details(server: dict, extra: Optional[dict] = None) -> dict:
    """Общие поля деталей: привязка к серверу для журнала и фильтра
    «Недавние события сервера» (server_id/server_name)."""
    details = {
        "server_id": str(server.get("id") or ""),
        "server_name": server.get("name"),
    }
    if extra:
        details.update(extra)
    return details


def report_mismatch(server: dict, expected: dict, presented: dict) -> None:
    sid = str(server.get("id") or server.get("name") or "")
    if sid in _mismatch_reported:
        return
    _mismatch_reported.add(sid)
    _emit_event(
        "critical",
        "SSH host key сервера изменился",
        f"Сервер «{server.get('name', '?')}» предъявил неизвестный host key: "
        f"ожидался {expected.get('fingerprint')}, получен "
        f"{presented.get('fingerprint')}. Подключения к серверу заблокированы "
        "до явного решения. Если сервер переустановлен — примите новый ключ "
        "в карточке сервера.",
        _event_details(
            server,
            {
                "expected_fingerprint": expected.get("fingerprint"),
                "presented_fingerprint": presented.get("fingerprint"),
            },
        ),
    )


def report_first_pinned(server: dict, presented: dict) -> None:
    _emit_event(
        "info",
        "SSH host key сервера закреплён",
        f"Первое подключение к «{server.get('name', '?')}»: host key "
        f"{presented.get('fingerprint')} сохранён, дальнейшие подключения "
        "сверяются с ним.",
        _event_details(server, {"fingerprint": presented.get("fingerprint")}),
    )


def report_accepted_new(server: dict, old: Optional[dict], presented: dict) -> None:
    reset_mismatch_report(server.get("id"))
    _emit_event(
        "warning",
        "SSH host key сервера обновлён вручную",
        f"Принят новый host key сервера «{server.get('name', '?')}»: "
        f"{presented.get('fingerprint')}"
        + (
            f" (прежде был {old.get('fingerprint')})."
            if isinstance(old, dict) and old.get("fingerprint")
            else "."
        ),
        _event_details(
            server,
            {
                "old_fingerprint": old.get("fingerprint") if isinstance(old, dict) else None,
                "fingerprint": presented.get("fingerprint"),
            },
        ),
    )


# ------------------------------------------------------------------
# Политика верификации
# ------------------------------------------------------------------

class HostKeyGate(paramiko.MissingHostKeyPolicy):
    """Сверка host key ДО аутентификации.

    SSHClient вызывает missing_host_key для КАЖДОГО нашего подключения
    (known_hosts мы не грузим) сразу после handshake и до отправки
    учётных данных — см. SSHClient.connect: start_client → host key
    check → _auth. Решение принимается здесь:

      * сохранённой записи нет → принять и захватить (TOFU), запись на
        диск делает вызывающий (core.ssh.create_ssh_client);
      * ключ совпал → принять;
      * ключ не совпал → HostKeyMismatchError, подключение прерывается
        до аутентификации.
    """

    def __init__(self, server: dict):
        self.server = server
        self.expected = stored_record(server)
        # TOFU-захват: запись о предъявленном ключе, если сохранённого
        # не было (None = сверка по сохранённой записи).
        self.captured: Optional[dict] = None

    def missing_host_key(self, client, hostname, key) -> None:
        presented = record_from_pkey(key)
        if self.expected is None:
            self.captured = presented
            return
        if records_match(self.expected, presented):
            return
        report_mismatch(self.server, self.expected, presented)
        raise HostKeyMismatchError(
            str(self.server.get("name") or hostname or "?"),
            str(self.expected.get("fingerprint") or "?"),
            str(presented.get("fingerprint") or "?"),
        )


def persist_tofu(server: dict, record: dict) -> None:
    """Записать захваченный TOFU-ключ на диск (best-effort).

    Вызывается после успешного подключения. Не перезаписывает
    существующую запись (гонка параллельных подключений / решение
    accept-флоу). Сбой записи не роняет подключение: ключ будет
    захвачен повторно при следующем коннекте.
    """
    sid = server.get("id") if isinstance(server, dict) else None
    if sid is None or sid == "":
        return
    try:
        from core.storage import record_server_host_key

        created = record_server_host_key(str(sid), record, overwrite=False)
        if created:
            report_first_pinned(server, record)
    except Exception as exc:
        print(f"[HOSTKEY] TOFU-запись не удалась: {exc}", flush=True)
