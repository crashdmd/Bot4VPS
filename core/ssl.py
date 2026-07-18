import ipaddress

from core.storage import load_servers, save_servers, find_server
from core.monitor import update_server_certificate


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