import ipaddress

from core.storage import data_lock, load_servers, save_servers, find_server
from core.monitor import clear_server_ssl, update_server_certificate


def is_ip_address(host: str) -> bool:
    """Проверяет, является ли host IP-адресом."""
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def enable_ssl_check(server_id: str, ssl_host: str = None):
    """Включает проверку SSL для сервера."""
    server = find_server(server_id)
    if not server:
        return False

    if ssl_host:
        server["ssl_host"] = ssl_host.strip()
    else:
        server["ssl_host"] = server.get("host")

    server["certificate_check"] = True

    servers = load_servers()
    for i, item in enumerate(servers):
        if item["id"] == server_id:
            servers[i] = server
            break

    save_servers(servers)
    update_server_certificate(server)
    return True


def disable_ssl_check(server_id: str):
    """Отключает проверку SSL."""
    server = find_server(server_id)
    if not server:
        return False

    server["certificate_check"] = False

    servers = load_servers()
    for i, item in enumerate(servers):
        if item["id"] == server_id:
            servers[i] = server
            break

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