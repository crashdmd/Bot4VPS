# -*- coding: utf-8 -*-
"""Модели состояния Quick Setup (Базовые настройки сервера)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


class QuickSetupServerNotFoundError(LookupError):
    """Запрошенный сервер Quick Setup отсутствует в локальном хранилище."""


def _to_dict(obj: Any) -> Any:
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _to_dict(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list):
        return [_to_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_dict(v) for k, v in obj.items()}
    return obj


@dataclass
class SystemStatus:
    """Раздел «Система»."""
    last_check: Optional[str] = None  # ISO или human
    updates_available: Optional[bool] = None  # True / False / None=unknown
    updates_summary: str = ""  # краткий текст: «доступны» / «система актуальна» / ошибка
    error: Optional[str] = None


@dataclass
class DiagnosticsStatus:
    """Раздел «Диагностика» — снимок с VPS."""
    os: str = "—"
    os_version: str = "—"
    kernel: str = "—"
    arch: str = "—"
    hostname: str = "—"
    cpu_model: str = "—"
    cpu_cores: Optional[int] = None
    ram: str = "—"
    disk: str = "—"
    uptime: str = "—"
    uptime_seconds: Optional[float] = None
    ssh_ok: bool = False
    ssh_port: int = 22
    ssh_error: Optional[str] = None
    firewall: str = "—"  # UFW / firewalld / nftables / Не обнаружен
    fail2ban: str = "—"  # ● Работает / ● Остановлен / Не установлен
    error: Optional[str] = None


@dataclass
class FirewallStatus:
    """Заглушка до реализации firewall/."""
    backend: Optional[str] = None  # ufw | firewalld | nftables | None
    active: Optional[bool] = None
    label: str = "Не обнаружен"
    error: Optional[str] = None
    # bounded inventory поддерживаемых логических firewall backend-ов
    backends: list = field(default_factory=list)


@dataclass
class Fail2banStatus:
    """Фактическое состояние пакета и сервиса Fail2ban."""
    installed: bool = False
    running: Optional[bool] = None
    autostart: Optional[bool] = None
    state: str = "absent"  # absent | stopped | running
    ssh_jail_enabled: Optional[bool] = None
    ban_time: Optional[str] = None
    find_time: Optional[str] = None
    max_retry: Optional[int] = None
    banned_count: Optional[int] = None
    jail_count: int = 0
    config_present: Optional[bool] = None
    label: str = "Не установлен"
    error: Optional[str] = None


@dataclass
class SshAccessStatus:
    """Заглушка / частичное чтение до полной реализации ssh_access."""
    user: str = "—"
    port: int = 22
    root_login: Optional[str] = None  # Запрещён / Разрешён / —
    password_auth: Optional[str] = None
    key_configured: Optional[bool] = None  # прописан ли key_path текущего пользователя в servers.json
    key_present: Optional[bool] = None  # True/False — ключ проверен на сервере; None — не проверялся
    auth_type: str = "password"
    sudo_capable: Optional[bool] = None  # sudo у текущего пользователя (root — True)
    key_shared_with: Optional[str] = None  # другой пользователь сервера, использующий записанный ключ
    # SSH host key (5.1): сохранённая запись + факт несоответствия.
    # Локальные поля — читаются и при недоступном SSH.
    host_key_type: Optional[str] = None
    host_key_fingerprint: Optional[str] = None  # SHA256:... сохранённого ключа
    host_key_mismatch: bool = False  # сервер предъявил другой ключ — подключения заблокированы
    error: Optional[str] = None


@dataclass
class PackageItem:
    name: str
    installed: bool
    # Категория каталога («utils»/«net»/«diag»/«services») — UI группирует
    # по ней; для произвольных запросов category = ""
    category: str = ""


@dataclass
class PackagesStatus:
    """Статус пакетов каталога Quick Setup."""
    items: list[PackageItem] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class LocalSettingsStatus:
    """Локальные поля servers.json (без SSH): имя, группа и SSL-проверка."""
    name: str = ""
    group: str = ""
    groups: list = field(default_factory=list)  # доступные группы для выбора
    ssl_enabled: bool = False  # certificate_check сервера
    ssl_host: str = ""  # домен проверки (пусто — берётся host сервера)


@dataclass
class QuickSetupOverview:
    """Полный снимок для страницы «Базовые настройки»."""
    server_id: str
    server_name: str
    host: str
    local_settings: LocalSettingsStatus = field(default_factory=LocalSettingsStatus)
    system: SystemStatus = field(default_factory=SystemStatus)
    firewall: FirewallStatus = field(default_factory=FirewallStatus)
    fail2ban: Fail2banStatus = field(default_factory=Fail2banStatus)
    ssh_access: SshAccessStatus = field(default_factory=SshAccessStatus)
    packages: PackagesStatus = field(default_factory=PackagesStatus)
    diagnostics: DiagnosticsStatus = field(default_factory=DiagnosticsStatus)

    def to_dict(self) -> dict:
        return _to_dict(self)


@dataclass
class OpResult:
    """Ограниченный результат синхронной операции Quick Setup."""
    ok: bool
    message: str = ""
    output: str = ""
    error: Optional[str] = None
    data: Optional[dict] = None
    details: Optional[dict] = None
    _data_text_limit: int = field(default=4000, repr=False, compare=False)

    def to_dict(self) -> dict:
        try:
            data_text_limit = int(self._data_text_limit)
        except (TypeError, ValueError):
            data_text_limit = 4000
        data_text_limit = max(1, min(data_text_limit, 512 * 1024))
        d = {
            "ok": bool(self.ok),
            "message": str(self.message or "")[:1000],
            "output": str(self.output or "")[:4000],
            "error": str(self.error)[:2000] if self.error is not None else None,
        }
        if self.data is not None:
            d["data"] = _bounded(self.data, text_limit=data_text_limit)
        if self.details is not None:
            d["details"] = _bounded(self.details)
        return d


def _bounded(value: Any, *, depth: int = 0, text_limit: int = 4000) -> Any:
    """Ограничить технические данные перед выдачей в Web API."""
    if depth > 5:
        return "…"
    if isinstance(value, str):
        return value[:text_limit]
    if isinstance(value, dict):
        return {
            str(key)[:120]: _bounded(
                item,
                depth=depth + 1,
                text_limit=text_limit,
            )
            for key, item in list(value.items())[:100]
        }
    if isinstance(value, (list, tuple)):
        return [
            _bounded(item, depth=depth + 1, text_limit=text_limit)
            for item in list(value)[:200]
        ]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:1000]
