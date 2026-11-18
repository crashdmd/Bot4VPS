import ipaddress
import asyncio
from dataclasses import dataclass, fields

from core.storage import data_lock, load_servers, save_servers, find_server
from core.monitor import clear_server_ssl, update_server_certificate


@dataclass(frozen=True)
class CertificatePostIssueOptions:
    """Shared options for services that issue and assign certificates."""
    monitor_ssl: bool = True

    @classmethod
    def from_dict(cls, values=None):
        if values is None:
            return cls()
        if not isinstance(values, dict):
            raise ValueError("Параметры после выпуска сертификата: нужен объект post_issue")
        unknown = set(values) - {field.name for field in fields(cls)}
        if unknown:
            raise ValueError("Неизвестные параметры post_issue: " + ", ".join(sorted(map(str, unknown))))
        if 'monitor_ssl' in values and not isinstance(values['monitor_ssl'], bool):
            raise ValueError("post_issue.monitor_ssl: требуется true или false")
        return cls(**values)


async def apply_certificate_post_issue(server_id, ssl_host, *, assigned,
                                       options=None, progress_cb=None):
    """Call after a successful issue and assignment in any service.

    Issuing files without assigning them leaves existing monitoring intact.
    Additional post-issue options and actions belong here, rather than in
    each service implementation. Failures are warnings: issue already succeeded.
    """
    options = options or CertificatePostIssueOptions()
    result = {"ssl_monitoring": "skipped", "warnings": []}
    if not assigned or not options.monitor_ssl:
        return result
    ssl_host = str(ssl_host or '').strip()
    async def emit(message):
        if progress_cb:
            try:
                await progress_cb(message)
            except Exception:
                pass
    await emit(f"SSL-мониторинг: включение проверки {ssl_host}…")
    try:
        if not ssl_host:
            raise ValueError("не указан домен или IP выпущенного сертификата")
        enabled = await asyncio.to_thread(enable_ssl_check, server_id, ssl_host)
        if not enabled:
            raise ValueError("сервер не найден в настройках мониторинга")
        result["ssl_monitoring"] = "enabled"
        message = f"SSL-мониторинг включён для {ssl_host}"
    except Exception as exc:
        result["ssl_monitoring"] = "incomplete"
        message = f"Сертификат выпущен, но настройка SSL-мониторинга не завершена: {exc}"
        result["warnings"].append(message)
    await emit(message)
    return result


def is_ip_address(host: str) -> bool:
    """Проверяет, является ли host IP-адресом."""
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def enable_ssl_check(server_id: str, ssl_host: str = None):
    """Включает проверку SSL для сервера."""
    with data_lock():
        servers = load_servers()
        server = next((item for item in servers if item.get("id") == server_id), None)
        if server is None:
            return False
        server["ssl_host"] = ssl_host.strip() if ssl_host else server.get("host")
        server["certificate_check"] = True
        save_servers(servers)
    update_server_certificate(server)
    return True


def disable_ssl_check(server_id: str):
    """Отключает проверку SSL."""
    with data_lock():
        servers = load_servers()
        server = next((item for item in servers if item.get("id") == server_id), None)
        if server is None:
            return False
        server["certificate_check"] = False
        save_servers(servers)
    return True


def clear_ssl_check(server_id: str, domain: str) -> bool:
    """Убрать SSL-мониторинг конкретного домена: ssl_host, certificate_check
    и сертификатная часть monitor.json. Действует только когда отслеживаемый
    домен совпадает с удалённым сертификатом; чужой домен не трогаем."""
    domain = (domain or "").strip()
    if not domain:
        return False
    cleared = False
    with data_lock():
        servers = load_servers()
        for i, item in enumerate(servers):
            if item.get("id") != server_id:
                continue
            if (item.get("ssl_host") or "") != domain:
                break
            item.pop("ssl_host", None)
            item["certificate_check"] = False
            servers[i] = item
            cleared = True
            break
        if cleared:
            save_servers(servers)
    if cleared:
        clear_server_ssl(server_id)
    return cleared
