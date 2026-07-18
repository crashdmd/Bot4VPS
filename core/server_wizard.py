import os
import secrets
from typing import Optional, Tuple

from core.storage import load_servers, save_servers, is_group_ssl_enabled
from core.ssh import test_connection
from core.storage import find_server, load_servers, save_servers


def validate_port(port_str: str) -> Tuple[bool, Optional[int], str]:
    """Валидация порта. Возвращает (ok, port, error_message)."""
    try:
        port = int(port_str)
    except ValueError:
        return False, None, "❌ Порт должен быть числом."
    
    if port < 1 or port > 65535:
        return False, None, "❌ Порт должен быть от 1 до 65535."
    
    return True, port, ""


def create_key_file(key_data: str, server_name: str) -> str:
    """Создаёт файл ключа и возвращает путь."""
    key_name = f"key_{server_name}"
    key_path = f"/opt/bot4vps/keys/{key_name}"
    counter = 1

    while os.path.exists(key_path):
        key_path = f"/opt/bot4vps/keys/{key_name}_{counter}"
        counter += 1

    with open(key_path, "w") as f:
        f.write(key_data)

    os.chmod(key_path, 0o600)
    return key_path


def build_server_dict(
    state: dict,
    auth_type: str,
    password: Optional[str] = None,
    key_path: Optional[str] = None
) -> dict:
    """Создаёт словарь сервера из состояния мастера."""
    server = {
        "id": secrets.token_hex(4),
        "name": state["name"],
        "group": state["group"],
        "host": state["host"],
        "port": state["port"],
        "user": state["user"],
        "auth_type": auth_type
    }

    if password:
        server["password"] = password

    if key_path:
        server["key_path"] = key_path

    if "certificate_check" in state:
        server["certificate_check"] = state["certificate_check"]

    if "ssl_host" in state:
        server["ssl_host"] = state["ssl_host"]

    return server


def save_new_server(
    state: dict,
    auth_type: str,
    password: Optional[str] = None,
    key_path: Optional[str] = None
) -> str:
    """Сохраняет новый сервер и возвращает его id."""
    server = build_server_dict(state, auth_type, password, key_path)

    servers = load_servers()
    servers.append(server)
    save_servers(servers)

    return server["id"]


def test_server_connection(
    host: str,
    port: int,
    user: str,
    auth_type: str,
    password: Optional[str] = None,
    key_path: Optional[str] = None
) -> Tuple[bool, str]:
    """Тестирует SSH-подключение."""
    test_server = {
        "host": host,
        "port": port,
        "user": user,
        "auth_type": auth_type
    }

    if password:
        test_server["password"] = password
    if key_path:
        test_server["key_path"] = key_path

    return test_connection(test_server)

def update_server_field(server_id: str, field: str, value: any) -> Tuple[bool, str]:
    """Обновляет одно поле сервера."""
    servers = load_servers()

    for server in servers:
        if server["id"] == server_id:
            if field == "port":
                ok, port, error = validate_port(str(value))
                if not ok:
                    return False, error
                server["port"] = port
            else:
                server[field] = value

            save_servers(servers)
            return True, "Параметр успешно обновлён."

    return False, "Сервер не найден."


def update_ssl_host(server_id: str, ssl_host: str) -> bool:
    """Обновляет домен для SSL и сразу проверяет сертификат."""
    server = find_server(server_id)
    if not server:
        return False

    server["ssl_host"] = ssl_host.strip()
    server["certificate_check"] = True

    servers = load_servers()
    for i, item in enumerate(servers):
        if item["id"] == server_id:
            servers[i] = server
            break

    save_servers(servers)

    from core.monitor import update_server_certificate
    update_server_certificate(server)

    return True