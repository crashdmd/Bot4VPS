"""Explicit OpenWrt onboarding with encrypted, retained SSH access."""
from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import shlex
import ssl
import time
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

from core.task_manager import TaskResult, register_executor, task_manager
from core.install_paths import get_install_path
from core.json_store import atomic_write_json, locked

ASSETS = Path(__file__).parent / "assets"
REQUIRED = ("rpcd", "rpcd-mod-file", "rpcd-mod-iwinfo", "rpcd-mod-ucode", "ucode-mod-uci", "ucode-mod-fs", "ucode-mod-ubus", "uhttpd", "uhttpd-mod-ubus", "luci-base", "usign")
_drafts = {}
_setup_locks = {}
DRAFTS_ROOT = get_install_path() / 'data/openwrt-bootstrap-drafts'
_draft_lock = threading.RLock()
DRAFT_TTL = 300


@dataclass
class Draft:
    token: str
    owner: str
    credentials: dict
    board: dict
    packages: dict
    expires: float
    started: bool = False


def draft_path(token):
    if not isinstance(token, str) or len(token) != 43 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in token):
        return None
    return DRAFTS_ROOT / (token + '.json')


def save_draft(draft):
    path = draft_path(draft.token)
    if not path: raise ValueError('Некорректный черновик подключения')
    atomic_write_json(path, asdict(draft))


def load_draft(token):
    path = draft_path(token)
    if path and path.exists():
        try: return Draft(**json.loads(path.read_text()))
        except (OSError, ValueError, TypeError): return None
    return _drafts.get(token)


def discard_draft(token, draft=None):
    if draft: draft.credentials.clear()
    cached = _drafts.pop(token, None)
    if cached: cached.credentials.clear()
    path = draft_path(token)
    if path: path.unlink(missing_ok=True)


def prune_drafts():
    if not DRAFTS_ROOT.exists(): return
    with locked(DRAFTS_ROOT / '.lock', _draft_lock):
        for path in DRAFTS_ROOT.glob('*.json'):
            draft = load_draft(path.stem)
            if not draft: discard_draft(path.stem)
            elif draft.expires < time.time():
                if draft.started: path.unlink(missing_ok=True)  # The running task retains its encrypted credentials until cleanup.
                else: discard_draft(path.stem, draft)


def draft_credentials(draft):
    from core.secretbox import decrypt
    credentials = dict(draft.credentials)
    if credentials.get('password'): credentials['password'] = decrypt(credentials['password'])
    return credentials


def _read(ssh, command):
    from core.openwrt.bootstrap_transaction import drain
    _, stdout, stderr = ssh.exec_command(command, timeout=240)
    result, error, status = drain(stdout, stderr)
    if status: raise ValueError("Команда роутера завершилась с ошибкой")
    return result.decode("utf-8", "replace")


def inspect_target(credentials):
    from core.ssh import create_ssh_client
    from core.host_keys import record_from_pkey
    ssh = create_ssh_client(credentials)
    try:
        _, stdout, _ = ssh.exec_command("ubus call system board 2>/dev/null", timeout=8)
        output = stdout.read(65536).decode("utf-8", "replace")
        code = stdout.channel.recv_exit_status()
        if code:
            os_release = _read(ssh, "cat /etc/os-release 2>/dev/null || true")
            if 'ID="openwrt"' in os_release or 'ID=openwrt' in os_release:
                raise ValueError("Обнаружен OpenWrt, но ubus недоступен. Используйте ручную настройку API.")
            return None
        try:
            board = json.loads(output)
        except ValueError:
            return None
        if board.get("release", {}).get("distribution", "").lower() != "openwrt":
            return None
        from core.openwrt.feature import enabled, register_ssh
        if enabled(): register_ssh(ssh)
        credentials["host_key"] = record_from_pkey(ssh.get_transport().get_remote_server_key())
        packages_text = _read(ssh, "if command -v apk >/dev/null 2>&1; then apk list -I --manifest; else opkg list-installed; fi")
        manager = "opkg" if " - " in packages_text else "apk"
        if manager == "opkg":
            packages = dict(line.split(" - ", 1) for line in packages_text.splitlines() if " - " in line)
        else:
            # apk 3 --manifest emits exact name/version fields, preserving
            # dashed names and versions with git prefixes or ABI hashes.
            packages = {}
            for line in packages_text.splitlines():
                fields = line.split()
                if len(fields) == 2:
                    packages[fields[0]] = fields[1]
        board["package_manager"] = manager
        board["lan_ip"] = _read(ssh, "uci -q get network.lan.ipaddr || true").strip()
        board["https_listen"] = _read(ssh, "uci -q get uhttpd.main.listen_https || true").strip()
        if credentials.get('user') == 'root':
            from core.openwrt.password import password_configured
            board['root_password_configured'] = password_configured(ssh)
            if credentials.get('auth_type') == 'none' and board['root_password_configured'] is not False:
                raise ValueError('Вход без пароля доступен только на OpenWrt с незаданным паролем root')
        return board, packages
    finally:
        ssh.close()


def gateway_name(name, board, host):
    for value in (name, board.get('model'), board.get('hostname'), host):
        if isinstance(value, str) and value.strip():
            return value.strip()[:100]
    return 'OpenWrt'


async def prepare(credentials, owner):
    from core.openwrt.feature import require_enabled
    require_enabled()
    await asyncio.to_thread(prune_drafts)
    credentials = dict(credentials)
    credentials["id"] = secrets.token_hex(8)
    credentials['_gateway_node_id'] = credentials['id']
    if credentials.get('auth_type') == 'password' and not credentials.get('password'):
        if credentials.get('user') != 'root': raise ValueError('Введите SSH-пароль')
        credentials.update(auth_type='none', password=None)
    inspected = await asyncio.to_thread(inspect_target, credentials)
    if inspected is None:
        return None
    board, packages = inspected
    credentials['name'] = gateway_name(credentials.get('name'), board, credentials['host'])
    token = secrets.token_urlsafe(32)
    if credentials.get('password'):
        from core.secretbox import encrypt
        credentials['password'] = await asyncio.to_thread(encrypt, credentials['password'])
    draft = Draft(token, owner, credentials, board, packages, time.time() + DRAFT_TTL)
    def store():
        with locked(DRAFTS_ROOT / '.lock', _draft_lock):
            if len(list(DRAFTS_ROOT.glob('*.json'))) >= 32: raise ValueError('Слишком много незавершённых подключений')
            save_draft(draft)
            _drafts[token] = draft
    await asyncio.to_thread(store)
    return public_draft(draft)


def get_draft(token, owner):
    draft = load_draft(token)
    if not draft or draft.owner != owner or draft.expires < time.time():
        raise ValueError("Проверка подключения истекла. Повторите её.")
    return draft


def public_draft(draft):
    return {"draft_token": draft.token, "node_type": "openwrt", "name": draft.credentials['name'], "board": draft.board,
        "missing_packages": [name for name in REQUIRED if name not in draft.packages],
        "https_configuration_required": not bool(draft.board.get("https_listen")),
        "component": "Раздел LuCI «Службы → Bot4VPS» и ограниченный RPC-профиль",
        "changes": ["Создать отдельную учётную запись для мониторинга, управления службами и отзыва собственного доступа", "Разрешить установку Podkop/SSClash только по подписанному панелью плану", "Установить компонент управления доступом в LuCI", "Сохранить SSH-доступ для консоли; пароль шифруется мастер-ключом панели", "Проверить HTTPS и права API"],
        "manual": manual_instructions(draft)}


def manual_instructions(draft):
    missing = [name for name in REQUIRED if name not in draft.packages]
    manager = draft.board["package_manager"]
    return {"packages": missing, "commands": ([manager + " update", manager + (" add " if manager == "apk" else " install ") + " ".join(missing)] if missing else []),
        "steps": ["Настройте HTTPS endpoint ubus в uhttpd.",
            "Создайте отдельную учётную запись rpcd с правами мониторинга.",
            "Укажите адрес API, логин, секрет и отпечаток сертификата в панели."],
        "acl": json.loads((ASSETS / "acl/bot4vps.json").read_text())["bot4vps-reader"],
        "note": "Секрет подключения rpcd — пароль отдельной учётной записи; API выдаёт временные сессии."}


def _write(ssh, path, content, mode="600"):
    destination = shlex.quote(path)
    temp = shlex.quote(path + ".bot4vps-new")
    parent = shlex.quote(str(Path(path).parent))
    stdin, stdout, stderr = ssh.exec_command(f"umask 077; mkdir -p {parent} && cat > {temp} && chmod {mode} {temp} && mv {temp} {destination}", timeout=20)
    stdin.write(content)
    stdin.flush()
    stdin.channel.shutdown_write()
    from core.openwrt.bootstrap_transaction import drain
    _, _, status = drain(stdout, stderr)
    if status:
        raise ValueError("Не удалось сохранить компонент подключения")


def configure(draft, emit):
    identity = (draft.credentials.get("host_key") or {}).get("fingerprint") or draft.credentials["host"]
    with _setup_locks.setdefault(identity, threading.RLock()):
        return _configure(draft, emit)


def _configure(draft, emit):
    from core.ssh import create_ssh_client
    from core.host_keys import record_from_pkey
    credentials = draft_credentials(draft)
    ssh = create_ssh_client({**credentials, '_gateway_node_id': credentials.get('id') or 'bootstrap'})
    node_id = credentials["id"]
    account = "bot4vps_" + node_id
    secret = secrets.token_hex(32)
    from core.openwrt.signing import create
    signing_config, public_signing_key = create()
    touched = []
    from core.openwrt.bootstrap_transaction import Transaction
    transaction = Transaction(ssh, node_id, emit)
    draft.transaction = transaction
    original_rpcd = None
    try:
        emit("Подключаюсь к OpenWrt; проверяю сохранённый SSH-ключ…")
        transaction.package_manager = draft.board['package_manager']
        transaction.packages_before = transaction.inventory()
        for path in ('/etc/config/rpcd', '/etc/config/uhttpd', '/etc/uhttpd.crt', '/etc/uhttpd.key'):
            transaction.snapshot(path)
        transaction.save()
        for package in REQUIRED:
            if package not in transaction.inventory():
                # Refreshing package indexes is not upgrading installed packages.
                manager = draft.board["package_manager"]
                if not touched:
                    emit("Обновляю список доступных пакетов (без обновления установленных)…")
                    _read(ssh, manager + " update")
                emit("Устанавливаю пакет " + package + "…")
                flag = " add " if manager == "apk" else " install "
                simulation = _read(ssh, manager + (' add --simulate ' if manager == 'apk' else ' --noaction install ') + shlex.quote(package))
                import re
                if re.search(r'(Upgrading|Downgrading|Reinstalling|Removing|Purging|Replacing)', simulation, re.I):
                    raise ValueError('Подключение требует изменения существующих пакетов. Автоматическая замена отключена; установите совместимые зависимости самостоятельно.')
                try:
                    _read(ssh, manager + flag + shlex.quote(package))
                finally:
                    transaction.packages_after = transaction.inventory(); transaction.save()
                    for path in tuple(transaction.files):
                        if path != '/etc/config/rpcd': transaction.record(path)
                emit("Пакет " + package + " установлен.")
                touched.append(package)
        emit("Сохраняю исходные настройки API…")
        original_rpcd = _read(ssh, "cat /etc/config/rpcd")
        _read(ssh, f"umask 077; mkdir -p /root/bot4vps-backup/{node_id}; cp /etc/config/rpcd /root/bot4vps-backup/{node_id}/rpcd; cp /etc/config/uhttpd /root/bot4vps-backup/{node_id}/uhttpd")
        emit("Устанавливаю раздел LuCI: Службы → Bot4VPS…")
        from core.openwrt.components import FILES
        files = {target: ASSETS / source for target, source in FILES.items()}
        for target, source in files.items():
            transaction.write(target, source.read_text(), "644")
        transaction.write("/etc/bot4vps/keys/" + account + ".pub", public_signing_key, "644")
        revoke_role = "bot4vps-key-" + node_id
        transaction.write("/usr/share/rpcd/acl.d/" + revoke_role + ".json", json.dumps({revoke_role: {
            "description": "Отзыв собственной учётной записи Bot4VPS", "write": {
                "ubus": {revoke_role: ["disconnect", "capabilities", "plan", "upload", "apply", "job", "confirm", "cleanup"]}}}}, ensure_ascii=False), "644")
        emit("Создаю отдельный секрет подключения и права мониторинга…")
        # Password is sent through stdin, never through task logs or a local argv.
        stdin, stdout, stderr = ssh.exec_command("ucode -", timeout=15)
        script = "import { cursor } from 'uci'; import { popen } from 'fs';\n"
        script += "let c = cursor(); let secret = " + json.dumps(secret) + ";\n"
        script += "let f = popen('/usr/sbin/uhttpd -m ' + secret); let hash = trim(f.read('all')); f.close();\n"
        script += "if (!hash) exit(1); c.set('rpcd', " + json.dumps(account) + ", 'login');\n"
        for key, value in {"username": account, "password": None, "bot4vps_id": node_id,
            "bot4vps_label": credentials.get("name", "Bot4VPS"), "read": ["bot4vps-reader"], "write": [revoke_role]}.items():
            script += "c.set('rpcd', " + json.dumps(account) + ", " + json.dumps(key) + ", " + ("hash" if value is None else json.dumps(value)) + ");\n"
        script += "if (!c.commit('rpcd')) exit(1);\n"
        stdin.write(script); stdin.flush(); stdin.channel.shutdown_write()
        from core.openwrt.bootstrap_transaction import drain
        _, _, status = drain(stdout, stderr)
        if status:
            raise ValueError("Не удалось создать отдельную учётную запись API")
        if not draft.board.get("https_listen"):
            emit("Включаю HTTPS uhttpd на адресе LAN; сетевые интерфейсы не меняю…")
            lan = draft.board.get("lan_ip")
            import ipaddress
            address = str(ipaddress.IPv4Address(lan))
            # Stage the UCI change; journal its exact bytes before publication.
            stage = '/tmp/bot4vps-bootstrap-' + node_id
            _read(ssh, 'umask 077; mkdir -p ' + stage + '/uci ' + stage + '/delta; cp /etc/config/uhttpd ' + stage + '/uci/uhttpd')
            code = "import { cursor } from 'uci'; let c = cursor(" + json.dumps(stage + '/uci') + ", " + json.dumps(stage + '/delta') + "); let listeners = c.get('uhttpd','main','listen_https') || []; if (type(listeners) != 'array') listeners = [listeners]; push(listeners," + json.dumps(address + ':443') + "); c.set('uhttpd','main','listen_https',listeners); if (!c.commit('uhttpd')) exit(1);"
            _write(ssh, stage + '/prepare.uc', code)
            _read(ssh, 'ucode ' + stage + '/prepare.uc')
            changed = _read(ssh, 'cat ' + stage + '/uci/uhttpd')
            transaction.write('/etc/config/uhttpd', changed, '600')
            _read(ssh, '/etc/init.d/uhttpd restart')
            _read(ssh, 'rm -rf ' + stage)
        transaction.record("/etc/config/uhttpd")
        _read(ssh, "/etc/init.d/rpcd reload; rm -f /tmp/luci-indexcache /tmp/luci-modulecache/*; true")
        cert_path = _read(ssh, "uci -q get uhttpd.main.cert || true").strip() or "/etc/uhttpd.crt"
        _, stdout, _ = ssh.exec_command("cat " + shlex.quote(cert_path), timeout=10)
        certificate = stdout.read(65536)
        if stdout.channel.recv_exit_status() or not certificate:
            raise ValueError("HTTPS-сертификат не создан. Проверьте настройки uhttpd в LuCI.")
        pem = certificate.decode("ascii") if b"BEGIN CERTIFICATE" in certificate else ssl.DER_cert_to_PEM_cert(certificate)
        der = ssl.PEM_cert_to_DER_cert(pem)
        host = credentials["host"]
        authority = "[" + host + "]" if ":" in host else host
        import re
        ports = re.findall(r":([0-9]+)(?:\s|$)", draft.board.get("https_listen", ""))
        https_port = 443 if "443" in ports or not ports else int(ports[0])
        url = "https://" + authority + (":" + str(https_port) if https_port != 443 else "") + "/ubus"
        return {"id": node_id, "name": credentials["name"], "host": host,
            "group": credentials.get("group", ""), "node_type": "openwrt",
            "root_password_configured": draft.board.get('root_password_configured'),
            "openwrt": {"url": url, "username": account, "password": secret,
                "tls_certificate": pem, "tls_sha256": hashlib.sha256(der).hexdigest(),
                "board": draft.board, "managed": True, **signing_config,
                "installed_components": {target: transaction.files[target]['after'] for target in files},
                "ssh": {key: credentials[key] for key in ('port', 'user', 'auth_type', 'password', 'key_path', 'host_key') if key in credentials and credentials[key] is not None},
                "luci_path": "/cgi-bin/luci/admin/services/bot4vps"}}
    except Exception:
        try: transaction.rollback()
        except Exception: emit('Откат подключения не завершён. Журнал: ' + transaction.path + '. Проверьте доступ и компоненты в LuCI.')
        raise
    finally:
        ssh.close()


async def execute(payload, task, progress):
    token = payload.get("draft_token")
    draft = _drafts.get(token) or load_draft(token)
    if not draft or not draft.started:
        return TaskResult(False, error="Данные подключения истекли. Повторите проверку; автоматический повтор настройки отключён.")
    loop = asyncio.get_running_loop()
    def emit(line):
        asyncio.run_coroutine_threadsafe(progress(line), loop).result(timeout=15)
    node = None
    stored = False
    try:
        node = await asyncio.to_thread(configure, draft, emit)
        await progress("Проверяю HTTPS API и права мониторинга…")
        from core.openwrt.rpc import RpcClient
        client = RpcClient(node["openwrt"])
        try:
            await client.call("system", "board")
            await client.call("bot4vps", "status")
            from core.openwrt.contract import check
            from core.openwrt.operations import namespace
            await check(client, namespace(node))
        finally:
            await client.close()
        from core.storage import add_server, load_servers, data_lock
        def store():
            with data_lock():
                if any(item.get('host') == node['host'] and item.get('node_type') == 'openwrt' for item in load_servers()):
                    raise ValueError('Этот шлюз уже подключён. Дополнительный API-доступ будет удалён.')
                add_server(node)
        node['bootstrap_state'] = 'commit_pending'
        await asyncio.to_thread(store)
        stored = True
        warnings = False
        try:
            await asyncio.to_thread(commit_transaction, draft)
            await asyncio.to_thread(set_bootstrap_state, node['id'], 'ready')
        except Exception:
            warnings = True
            await progress('Шлюз подключён и сохранён. Фиксация транзакции не подтверждена: повторите её во вкладке «Доступ». Повторное подключение не требуется.')
        await progress("Подключение готово. API: " + node["openwrt"]["url"])
        await progress("Отключение и перевыпуск: LuCI → Службы → Bot4VPS")
        await progress("Пароли и секреты в журнал не записываются.")
        from core.openwrt.monitor import refresh
        try:
            await refresh(node, force=True)
        except Exception:
            warnings = True
            await progress('Шлюз подключён. Первоначальные метрики пока недоступны; мониторинг повторит проверку.')
        try:
            from core.openwrt.bundle_jobs import enqueue_reserve
            await enqueue_reserve(node, automatic=True)
        except Exception:
            warnings = True
            await progress('Не удалось поставить резервирование в очередь; используйте ручную загрузку во вкладке «Файлы → Сервисы».')
        return TaskResult(True, warnings=warnings, output=json.dumps({"gateway_id": node["id"], "api_url": node["openwrt"]["url"], "luci_path": node["openwrt"]["luci_path"]}, ensure_ascii=False))
    except Exception as exc:
        if not stored and (node or getattr(draft, 'transaction', None) and not draft.transaction.finished):
            await progress('Подключение не завершено. Удаляю созданный API-доступ; SSH и другие подключения сохраняю…')
            try:
                await asyncio.to_thread(rollback_transaction, draft, node)
                await progress('Созданный доступ и его сеансы отозваны.')
            except Exception:
                await progress('Очистку доступа проверить не удалось. Отключите созданную учётную запись в LuCI → Службы → Bot4VPS.')
        return TaskResult(False, error=str(exc))
    finally:
        await asyncio.to_thread(discard_draft, token, draft)


def set_bootstrap_state(node_id, state):
    from core.storage import find_server, commit_server, data_lock
    with data_lock():
        node = find_server(node_id)
        if node and node.get('node_type') == 'openwrt':
            node['bootstrap_state'] = state
            commit_server(node)


def finalize_connection(node):
    """Retry only the transaction checkpoint of an already saved connection."""
    from core.openwrt.console import target
    from core.ssh import create_ssh_client
    ssh = create_ssh_client(target(node))
    try:
        path = '/root/bot4vps-backup/' + node['id'] + '/transaction.json'
        transaction = json.loads(_read(ssh, 'cat ' + shlex.quote(path)))
        if transaction.get('account') != node['openwrt']['username'] or transaction.get('phase') not in ('running', 'committed'):
            raise ValueError('Транзакция не соответствует сохранённому подключению')
        transaction['phase'] = 'committed'
        _write(ssh, path, json.dumps(transaction, separators=(',', ':')))
        set_bootstrap_state(node['id'], 'ready')
    finally: ssh.close()


async def execute_finalize(payload, task, progress):
    from core.storage import find_server
    node = await asyncio.to_thread(find_server, task.server_id)
    if not node or node.get('bootstrap_state') != 'commit_pending':
        return TaskResult(False, error='Нет незавершённой фиксации подключения')
    try:
        await asyncio.to_thread(finalize_connection, node)
        await progress('Фиксация сохранённого подключения завершена.')
        return TaskResult(True)
    except Exception as exc:
        return TaskResult(False, error=str(exc))


register_executor('openwrt-bootstrap-finalize', execute_finalize)


def commit_transaction(draft):
    from core.ssh import create_ssh_client
    transaction = getattr(draft, 'transaction', None)
    if not transaction: return
    ssh = create_ssh_client({**draft_credentials(draft), '_gateway_node_id': draft.credentials.get('id') or 'bootstrap'})
    try: transaction.ssh = ssh; transaction.commit()
    finally: ssh.close()


def rollback_transaction(draft, node):
    from core.ssh import create_ssh_client
    transaction = getattr(draft, 'transaction', None)
    if not transaction: return cleanup_created_access(draft, node)
    ssh = create_ssh_client({**draft_credentials(draft), '_gateway_node_id': draft.credentials.get('id') or 'bootstrap'})
    try: transaction.ssh = ssh; transaction.rollback()
    finally: ssh.close()


def cleanup_created_access(draft, node):
    from core.ssh import create_ssh_client
    account = node['openwrt']['username']
    import re
    if not re.fullmatch(r'bot4vps_[a-f0-9]+', account): raise ValueError('Неизвестная учётная запись')
    ssh = create_ssh_client({**draft_credentials(draft), '_gateway_node_id': draft.credentials.get('id') or 'bootstrap'})
    try:
        _read(ssh, 'uci -q delete rpcd.' + account + ' || true; uci commit rpcd; /usr/bin/ucode /usr/libexec/bot4vps-revoke.uc ' + account)
        _read(ssh, 'rm -f ' + shlex.quote('/etc/bot4vps/keys/' + account + '.pub') + ' ' + shlex.quote('/usr/share/rpcd/acl.d/bot4vps-key-' + account[8:] + '.json') + '; /etc/init.d/rpcd reload')
    finally:
        ssh.close()


async def start(token, owner):
    def claim():
        with locked(DRAFTS_ROOT / '.lock', _draft_lock):
            draft = get_draft(token, owner)
            if draft.started: raise ValueError('Настройка уже запущена')
            draft.started = True
            save_draft(draft)
            _drafts[token] = draft
            return draft
    draft = await asyncio.to_thread(claim)
    try:
        return await task_manager.enqueue(name="Подключение шлюза OpenWrt", server_id=draft.credentials["id"],
            server_name=draft.credentials["name"], kind="openwrt-bootstrap", payload={"draft_token": token}, live_reported=True)
    except Exception:
        draft.started = False
        await asyncio.to_thread(save_draft, draft)
        raise


register_executor("openwrt-bootstrap", execute)
