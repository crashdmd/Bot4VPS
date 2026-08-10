# -*- coding: utf-8 -*-
"""WireGuard - интегрированный сервис Bot4VPS: сервер + профили клиентов."""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core.integrator import (
    Parameter,
    Service as BaseService,
    ServiceAction,
    StepError,
    read_cache,
    sync_progress,
    update_cache,
)
from core.ssh import create_ssh_client, exec_sudo
from core.storage import find_server
from core.task_manager import TaskResult

from . import lifecycle, migration, profiles, stats
from .validation import (
    ADDR_RE,
    coerce_bool,
    is_private_ip,
    validate_addr,
    validate_dns,
    validate_host,
    validate_port,
    validate_profile_name,
)

# Один shell-цикл: для каждого peers/*.conf + peers.disabled/*.conf выводит
# «name\tpubkey». Pubkey — из clients/<name>/publickey (managed), иначе из строки
# PublicKey= peer-файла (imported). Нет интерполяции пользовательского ввода.
_NAME_TO_PUBKEY_CMD = (
    'for d in /etc/wireguard/peers/*.conf /etc/wireguard/peers.disabled/*.conf; do '
    '[ -f "$d" ] || continue; '
    'name=$(basename "$d" .conf); '
    'if [ -f "/etc/wireguard/clients/$name/publickey" ]; then '
    'pub=$(tr -d \' \\r\\n\' < "/etc/wireguard/clients/$name/publickey"); '
    'else '
    "pub=$(awk '/^[[:space:]]*PublicKey/ {sub(/^[^=]*=/, \"\"); print; exit}' \"$d\" | tr -d ' \\r\\n'); "
    'fi; '
    '[ -n "$name" ] && [ -n "$pub" ] && printf \'%s\\t%s\\n\' "$name" "$pub"; '
    'done'
)


def _conf_value(text: str, key: str) -> Optional[str]:
    """Первое значение ``key`` из INI-подобного текста (wg0.conf): учитывает
    ``Key = val``, ``Key=val`` и регистр. None, если ключа нет."""
    key_l = key.lower()
    for line in (text or "").splitlines():
        s = line.strip()
        if "=" in s and s.lower().split("=", 1)[0].strip() == key_l:
            return s.split("=", 1)[1].strip() or None
    return None


def _set_conf_line(text: str, key: str, value: str) -> str:
    """Заменить значение ``Key = value`` в тексте; если строки нет — добавить перед
    первым [Peer]-разделом (или в конец). Остальные строки не трогает (ТЗ §13)."""
    key_l = key.lower()
    out: List[str] = []
    replaced = False
    for line in (text or "").splitlines():
        s = line.strip()
        if "=" in s and s.lower().split("=", 1)[0].strip() == key_l:
            if not replaced:
                out.append(f"{key} = {value}")
                replaced = True
            # старую строку ключа пропускаем (заменена)
            continue
        out.append(line)
    if not replaced:
        # вставляем перед первым [Peer] (если есть), иначе в конец
        insert_at = len(out)
        for i, line in enumerate(out):
            if line.strip().lower() == "[peer]":
                insert_at = i
                break
        out.insert(insert_at, f"{key} = {value}")
    return "\n".join(out) + ("\n" if text and text.endswith("\n") else "")


def _rollback_wg0(ssh, server, bak_path: Optional[str]) -> None:
    """Восстановить wg0.conf из бэкапа и перезапустить интерфейс при провале apply
    (ТЗ §16: атомарность, без ложного успеха). Путь бэкапа жёстко проверяется —
    это сформированный нами путь ``/etc/wireguard/wg0.conf.bak.<digits>``."""
    if not bak_path:
        return
    prefix = "/etc/wireguard/wg0.conf.bak."
    suffix = bak_path[len(prefix):]
    if not bak_path.startswith(prefix) or not suffix.isdigit():
        return  # не наш путь — не интерполируем
    try:
        exec_sudo(
            ssh, server,
            f"cp -a {bak_path} /etc/wireguard/wg0.conf && chmod 600 /etc/wireguard/wg0.conf && "
            "systemctl restart wg-quick@wg0 || true",
        )
    except Exception:
        pass


class Service(BaseService):
    """WireGuard: установка сервера и менеджмент профилей клиентов."""

    def params_schema(self) -> List[Parameter]:
        return [
            Parameter(
                name="WG_PORT", type="number", default=51820, min=1, max=65535,
                description="UDP-порт, на котором сервер слушает WireGuard",
            ),
            Parameter(
                name="WG_ADDR", type="text", default="10.66.66.1/24",
                pattern=ADDR_RE.pattern,
                description="Внутренний адрес сервера в туннеле (CIDR)",
            ),
            Parameter(
                name="WG_DNS", type="text", default="1.1.1.1", required=False,
                description="DNS, выдаваемый клиентам",
            ),
        ]

    async def do_install(
        self, server_id: str, params: Dict[str, Any], progress_cb: Callable[[str], Awaitable[None]]
    ) -> TaskResult:
        server = find_server(server_id)
        if not server:
            return TaskResult(success=False, error="Сервер не найден")
        async with sync_progress(progress_cb) as emit:
            runner = await asyncio.to_thread(lifecycle.install, server, params, emit)
            
            if "WG_ENDPOINT" in params:
                endpoint = str(params.get("WG_ENDPOINT") or "").strip()
            else:
                endpoint = str(server.get("host") or "").strip()
                
            if endpoint and is_private_ip(endpoint):
                emit("   [!] Указан приватный адрес. Клиенты вне локальной сети не смогут подключиться.")
                
            update_cache(
                self.manifest.id, server_id,
                endpoint=endpoint or None,
                dns=str(params.get("WG_DNS") or "1.1.1.1").strip(),
            )
        return TaskResult(
            success=True,
            output="WireGuard установлен; wg-quick@wg0 запущен. Шаги: " + ", ".join(runner.completed),
        )

    async def do_remove(
        self, server_id: str, params: Dict[str, Any], progress_cb: Callable[[str], Awaitable[None]]
    ) -> TaskResult:
        server = find_server(server_id)
        if not server:
            return TaskResult(success=False, error="Сервер не найден")
        async with sync_progress(progress_cb) as emit:
            runner = await asyncio.to_thread(lifecycle.remove, server, emit)
        return TaskResult(success=True, output="WireGuard удалён. Шаги: " + ", ".join(runner.completed))

    async def do_add_profile(
        self, server_id: str, params: Dict[str, Any], progress_cb: Callable[[str], Awaitable[None]]
    ) -> TaskResult:
        server = find_server(server_id)
        if not server:
            return TaskResult(success=False, error="Сервер не найден")
        name = validate_profile_name(params.get("name"))
        async with sync_progress(progress_cb) as emit:
            info = await asyncio.to_thread(
                profiles.add_profile, self.manifest.id, server, name, params, emit
            )
        return TaskResult(
            success=True,
            output=f"Профиль «{name}» создан. IP клиента: {info['client_ip']}. "
            f"Скачать: /etc/wireguard/clients/{name}.conf",
        )

    async def do_remove_profile(
        self, server_id: str, params: Dict[str, Any], progress_cb: Callable[[str], Awaitable[None]]
    ) -> TaskResult:
        server = find_server(server_id)
        if not server:
            return TaskResult(success=False, error="Сервер не найден")
        name = validate_profile_name(params.get("name"))
        async with sync_progress(progress_cb) as emit:
            await asyncio.to_thread(profiles.remove_profile, server, name, emit)
        return TaskResult(success=True, output=f"Профиль «{name}» удалён")

    async def do_toggle_profile(
        self, server_id: str, params: Dict[str, Any], progress_cb: Callable[[str], Awaitable[None]]
    ) -> TaskResult:
        server = find_server(server_id)
        if not server:
            return TaskResult(success=False, error="Сервер не найден")
        name = validate_profile_name(params.get("name"))
        enabled = coerce_bool(params.get("enabled"))
        async with sync_progress(progress_cb) as emit:
            await asyncio.to_thread(profiles.toggle_profile, server, name, enabled, emit)
        state = "включён" if enabled else "выключен"
        return TaskResult(success=True, output=f"Профиль «{name}» {state}")

    async def do_rename_profile(
        self, server_id: str, params: Dict[str, Any], progress_cb: Callable[[str], Awaitable[None]]
    ) -> TaskResult:
        server = find_server(server_id)
        if not server:
            return TaskResult(success=False, error="Сервер не найден")
        old_name = validate_profile_name(params.get("old_name"))
        new_name = validate_profile_name(params.get("new_name"))
        async with sync_progress(progress_cb) as emit:
            await asyncio.to_thread(profiles.rename_profile, server, old_name, new_name, emit)
        return TaskResult(success=True, output=f"Профиль «{old_name}» переименован в «{new_name}»")

    async def do_reissue_profile(
        self, server_id: str, params: Dict[str, Any], progress_cb: Callable[[str], Awaitable[None]]
    ) -> TaskResult:
        """Перевыпуск ключей для импортированного профиля."""
        server = find_server(server_id)
        if not server:
            return TaskResult(success=False, error="Сервер не найден")
        name = validate_profile_name(params.get("name"))
        async with sync_progress(progress_cb) as emit:
            await asyncio.to_thread(
                profiles.reissue_profile, self.manifest.id, server, name, params, emit
            )
        return TaskResult(
            success=True,
            output=f"Профиль «{name}» перевыпущен. Теперь доступно скачивание конфига."
        )

    async def do_migrate(
        self, server_id: str, params: Dict[str, Any], progress_cb: Callable[[str], Awaitable[None]]
    ) -> TaskResult:
        server = find_server(server_id)
        if not server:
            return TaskResult(success=False, error="Сервер не найден")
        reissue = bool(params.get("reissue"))
        async with sync_progress(progress_cb) as emit:
            count = await asyncio.to_thread(migration.migrate, server, emit)
            if reissue:
                # Перевыпуск без Endpoint бесполезен (свежие clients/*.conf некому
                # скачать). Проверяем заранее, чтобы успешная миграция не
                # маркировалась failed — перевыпуск просто пропускается.
                has_endpoint = bool(
                    (read_cache(self.manifest.id, server_id).get("endpoint") or "").strip()
                )
                if not has_endpoint:
                    emit("   [!] Endpoint не задан — перевыпуск пропущен.")
                    return TaskResult(
                        success=True,
                        output=(
                            f"Миграция выполнена. Перенесено профилей: {count}. "
                            f"Перевыпуск пропущен: не задан Endpoint. "
                            f"Укажите Endpoint, затем перевыпустите профили."
                        ),
                    )
                reissued = await asyncio.to_thread(
                    profiles.reissue_all, self.manifest.id, server, params, emit
                )
                return TaskResult(
                    success=True,
                    output=(
                        f"Миграция выполнена. Перенесено профилей: {count}; "
                        f"перевыпущено: {reissued}. Теперь доступны скачивание и QR."
                    ),
                )
        return TaskResult(
            success=True,
            output=(
                f"Миграция завершена. Перенесено профилей: {count}. "
                f"Резервная копия: /etc/wireguard/wg0.conf.bak.*. "
                f"Для скачивания/QR перевыпустите профили."
            ),
        )

    async def do_reissue_all(
        self, server_id: str, params: Dict[str, Any], progress_cb: Callable[[str], Awaitable[None]]
    ) -> TaskResult:
        """Перевыпустить все импортированные профили одной сервисной операцией
        (не N отдельных вызовов). UI — кнопка «Перевыпустить все»."""
        server = find_server(server_id)
        if not server:
            return TaskResult(success=False, error="Сервер не найден")
        async with sync_progress(progress_cb) as emit:
            count = await asyncio.to_thread(
                profiles.reissue_all, self.manifest.id, server, params, emit
            )
        return TaskResult(
            success=True,
            output=f"Перевыпущено профилей: {count}. Теперь доступны скачивание и QR.",
        )

    def detect_endpoint(self, server_id: str) -> Optional[str]:
        """Кандидат на публичный endpoint (host, без порта) для предзаполнения при
        миграции: из существующего clients/<name>.conf (если есть управляемые
        профили — это авторитетный адрес, что уже используют клиенты), иначе host
        сервера, если он публичный. None — не удалось определить. UI зовёт через
        integrator.call."""
        server = find_server(server_id)
        if not server:
            return None
        ssh = create_ssh_client(server)
        try:
            ep_line = exec_sudo(
                ssh, server,
                "grep -hm1 -E '^[[:space:]]*Endpoint[[:space:]]*=' /etc/wireguard/clients/*.conf 2>/dev/null || true",
            )[1].strip()
            if ep_line and "=" in ep_line:
                val = ep_line.split("=", 1)[1].strip()
                host = (val.rsplit(":", 1)[0] if ":" in val else val).strip()
                if host:
                    return host
            sh = (server.get("host") or "").strip()
            if sh and not is_private_ip(sh):
                return sh
            return None
        finally:
            ssh.close()

    def _read_live(self, server_id: str) -> Dict[str, Any]:
        """Единое read-only живое чтение состояния: существующие пробы + статистика
        (wg show wg0 dump), name→pubkey, server_public_key и поля конфига
        (address/port/dns) для префиля модалки. Ничего не пишет в кэш — это делает
        фреймворк ``sync()`` после ``do_sync``. Используется и ``do_sync`` (→ кэш),
        и ``get_state`` (→ живой ответ без кэша)."""
        server = find_server(server_id)
        if not server:
            return {"installed": False, "error": "Сервер не найден"}
        ssh = create_ssh_client(server)
        try:
            _, ver, _ = exec_sudo(
                ssh, server,
                "command -v wg >/dev/null 2>&1 && wg --version | head -1 || true",
            )
            # Используем wg show для более точной проверки инициализации WG
            _, active, _ = exec_sudo(
                ssh, server, "wg show wg0 >/dev/null 2>&1 && echo active || echo inactive"
            )
            _, active_lst, _ = exec_sudo(
                ssh, server,
                "find /etc/wireguard/peers -maxdepth 1 -name '*.conf' -printf '%f\\n' 2>/dev/null || true",
            )
            _, disabled_lst, _ = exec_sudo(
                ssh, server,
                "find /etc/wireguard/peers.disabled -maxdepth 1 -name '*.conf' -printf '%f\\n' 2>/dev/null || true",
            )
            # Получаем список управляемых профилей (у которых есть директория с ключами)
            _, client_dirs, _ = exec_sudo(
                ssh, server,
                "find /etc/wireguard/clients -maxdepth 1 -mindepth 1 -type d -printf '%f\\n' 2>/dev/null || true",
            )
            managed_set = set(n for n in client_dirs.splitlines() if n)

            active_names = [n for n in (f[:-5] for f in active_lst.splitlines() if f.endswith(".conf"))]
            disabled_names = [n for n in (f[:-5] for f in disabled_lst.splitlines() if f.endswith(".conf"))]

            # Формируем список с флагом managed (True если бот создавал профиль)
            profiles_list = (
                [{"name": n, "enabled": True, "managed": n in managed_set} for n in active_names]
                + [{"name": n, "enabled": False, "managed": n in managed_set} for n in disabled_names]
            )

            _, wg0, _ = exec_sudo(
                ssh, server,
                "test -f /etc/wireguard/wg0.conf && cat /etc/wireguard/wg0.conf || true",
            )
            peer_files = [f for f in active_lst.splitlines() if f.endswith(".conf")]
            has_inline = any(l.strip().lower() == "[peer]" for l in wg0.splitlines())
            needs_migration = False
            classic_peer_count = 0
            if ver.strip() and has_inline and not peer_files:
                needs_migration = True
                classic_peer_count = sum(1 for l in wg0.splitlines() if l.strip().lower() == "[peer]")
                profiles_list = []

            prev = read_cache(self.manifest.id, server_id)

            # --- Статистика + поля конфига (только для установленного не-классики) ---
            stats_block = {
                "online": 0, "total": len(profiles_list),
                "rx_bytes": 0, "tx_bytes": 0,
            }
            server_public_key = None
            address = None
            port = None
            dns = None

            if ver.strip() and not needs_migration:
                # now_ts — серверное время в той же SSH-сессии (нет расхождения часов)
                _, now_out, _ = exec_sudo(ssh, server, "date +%s")
                try:
                    now_ts = int(now_out.strip())
                except ValueError:
                    now_ts = 0

                _, spk, _ = exec_sudo(
                    ssh, server, "cat /etc/wireguard/server_public.key 2>/dev/null || true"
                )
                server_public_key = spk.strip() or None
                address = _conf_value(wg0, "Address")
                port_s = _conf_value(wg0, "ListenPort")
                port = int(port_s) if (port_s or "").isdigit() else None

                _, dns_out, _ = exec_sudo(
                    ssh, server,
                    "awk '/^[[:space:]]*DNS[[:space:]]*=/{sub(/^[^=]*=/, \"\"); print; exit}' "
                    "/etc/wireguard/clients/*.conf 2>/dev/null || true",
                )
                # DNS хранится в clients/*.conf; если профилей нет — берём
                # сохранённое предпочтение из кэша (как endpoint), иначе меню
                # конфигурации всегда показывает «—».
                dns = dns_out.strip() or prev.get("dns")

                # name → pubkey (один shell-цикл по peers + peers.disabled)
                _, namepub, _ = exec_sudo(ssh, server, _NAME_TO_PUBKEY_CMD)
                name_to_pubkey: Dict[str, str] = {}
                for ln in namepub.splitlines():
                    if "\t" in ln:
                        nm, pk = ln.split("\t", 1)
                        name_to_pubkey[nm.strip()] = pk.strip()

                # wg show dump → статистика (только при активном интерфейсе).
                # Если интерфейс неактивен — отдаём профили с нулевой статистикой.
                dump_map: Dict[str, Dict[str, Any]] = {}
                if active.strip() == "active":
                    _, dump_txt, _ = exec_sudo(ssh, server, "wg show wg0 dump 2>/dev/null || true")
                    dump_map = stats.parse_dump(dump_txt)
                profiles_list = stats.build_profile_stats(
                    profiles_list, name_to_pubkey, dump_map, now_ts
                )
                stats_block["online"] = sum(1 for p in profiles_list if p.get("connected"))
                stats_block["rx_bytes"] = sum(int(p.get("rx_bytes", 0)) for p in profiles_list)
                stats_block["tx_bytes"] = sum(int(p.get("tx_bytes", 0)) for p in profiles_list)

            return {
                "installed": bool(ver.strip()),
                "version": ver.strip() or None,
                "active": active.strip(),
                "profiles": profiles_list,
                "endpoint": prev.get("endpoint"),
                "needs_migration": needs_migration,
                "classic_peer_count": classic_peer_count,
                "stats": stats_block,
                "server_public_key": server_public_key,
                "address": address,
                "port": port,
                "dns": dns,
            }
        finally:
            ssh.close()

    async def do_sync(self, server_id: str) -> Dict[str, Any]:
        try:
            return await asyncio.to_thread(self._read_live, server_id)
        except Exception as e:
            return {"installed": False, "error": str(e)}

    def get_state(self, server_id: str) -> Dict[str, Any]:
        """Живое чтение состояния БЕЗ записи кэша (ТЗ §18/§21): актуальная
        статистика при открытии/рефреше экрана сервера. ``do_sync`` (→ кэш) и этот
        метод используют общий ``_read_live``; разница — только в персистентности.
        Синхронный: ``integrator.call`` заворачивает в ``asyncio.to_thread``."""
        return self._read_live(server_id)

    def get_status(self, server_id: str) -> Dict[str, Any]:
        return read_cache(self.manifest.id, server_id)

    def get_profiles(self, server_id: str) -> List[Dict[str, Any]]:
        return read_cache(self.manifest.id, server_id).get("profiles", [])

    def _apply_endpoint(self, server_id: str, endpoint: Optional[str]) -> Optional[int]:
        """Записать предпочтение Endpoint в кэш и переписать ``Endpoint =`` во всех
        ``clients/*.conf``. None/пусто = сброс предпочтения (конфиги не трогаем).
        Общая логика для ``set_endpoint`` и ``update_config``. Возвращает число
        обновлённых конфигов (None при сбросе)."""
        endpoint = (endpoint or "").strip() or None
        update_cache(self.manifest.id, server_id, endpoint=endpoint)
        if not endpoint:
            return None
        server = find_server(server_id)
        if not server:
            return 0
        return profiles.rewrite_client_endpoints(server, endpoint)

    def set_endpoint(self, server_id: str, endpoint: Optional[str]) -> Optional[int]:
        """Сменить Endpoint (обратная совместимость). Делегирует в ``_apply_endpoint``.
        UI/Telegram используют ``update_config``; этот метод остаётся для старого
        контракта (ТЗ §14: единый сервисный метод)."""
        return self._apply_endpoint(server_id, endpoint)

    def update_config(
        self, server_id: str,
        endpoint: Optional[str] = None,
        port: Optional[int] = None,
        address: Optional[str] = None,
        dns: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Частичное изменение конфигурации WireGuard (ТЗ §12-§17).

        ``None`` = пропустить (поле не трогается — частичный patch, §13); для
        ``endpoint`` пустая строка = явный сброс. Валидация — до любых SSH-записей.
        port/address → правка wg0.conf + ``wg-quick`` restart (с откатом при провале
        apply, §16); endpoint/dns → только clients/*.conf, без рестарта. Механизм
        применения — внутреннее дело сервиса (ТЗ §15: UI его не знает и systemctl
        не зовёт). Кэш обновляет вызывающий (роутер) через ``integrator.sync``.
        """
        # --- Валидация (всё сразу, до записи) ---
        v_port: Optional[str] = validate_port(port) if port is not None else None
        v_addr: Optional[str] = validate_addr(address) if address is not None else None
        v_dns: Optional[str] = validate_dns(dns) if dns is not None else None
        if endpoint is not None and endpoint.strip():
            validate_host(endpoint.strip())  # StepError при невалидном host

        iface_change = (v_port is not None) or (v_addr is not None)
        ep_change = endpoint is not None
        dns_change = v_dns is not None
        if not (iface_change or ep_change or dns_change):
            return {}  # ничего не менялось

        server = find_server(server_id)
        if not server:
            raise RuntimeError("Сервер не найден")

        ssh = create_ssh_client(server)
        bak_path: Optional[str] = None
        old_server_addr: Optional[str] = None
        try:
            # 1) wg0.conf: Address/ListenPort (до рестарта и до rewrite_endpoints,
            #    т.к. rewrite_endpoints читает ListenPort из wg0.conf).
            if iface_change:
                _, wg0, _ = exec_sudo(ssh, server, "cat /etc/wireguard/wg0.conf 2>/dev/null || true")
                if not wg0.strip():
                    raise StepError("update_config", -1, title="Изменение конфигурации",
                                    detail="/etc/wireguard/wg0.conf не найден или пуст")
                new_wg0 = wg0
                old_server_addr = _conf_value(wg0, "Address")  # для переноса подсети у пиров
                if v_addr is not None:
                    new_wg0 = _set_conf_line(new_wg0, "Address", v_addr)
                if v_port is not None:
                    new_wg0 = _set_conf_line(new_wg0, "ListenPort", v_port)
                # бэкап с серверным ts; echo пути — для точного отката при провале apply
                _, bak_out, _ = exec_sudo(
                    ssh, server,
                    "BAK=/etc/wireguard/wg0.conf.bak.$(date +%s); "
                    "cp -a /etc/wireguard/wg0.conf $BAK && echo $BAK",
                )
                bak_lines = [l.strip() for l in bak_out.splitlines() if l.strip()]
                bak_path = bak_lines[-1] if bak_lines else None
                sftp = ssh.open_sftp()
                try:
                    with sftp.file("/tmp/bot4vps_wg0.new", "w") as f:
                        f.write(new_wg0)
                finally:
                    sftp.close()
                code, _, e2 = exec_sudo(
                    ssh, server,
                    "mv /tmp/bot4vps_wg0.new /etc/wireguard/wg0.conf && chmod 600 /etc/wireguard/wg0.conf",
                )
                if code != 0:
                    raise StepError("update_config_write", code, title="Изменение конфигурации",
                                    detail=(e2 or "не удалось записать wg0.conf").strip()[:500])

            # 2) Endpoint в clients/*.conf (cache-pref + rewrite; читает новый ListenPort)
            if ep_change:
                self._apply_endpoint(server_id, endpoint)

            # 3) DNS в clients/*.conf (+ сохраняем предпочтение в кэш — как endpoint;
            #    иначе без профилей значение теряется, и меню показывает «—»).
            if dns_change:
                update_cache(self.manifest.id, server_id, dns=v_dns)
                profiles.rewrite_client_dns(server, v_dns)

            # 3b) ListenPort → Endpoint в clients/*.conf
            if v_port is not None:
                host = None
                try:
                    cached = read_cache(self.manifest.id, server_id) or {}
                    host = (cached.get("endpoint") or "").strip() or None
                    if host and ":" in host and not host.startswith("["):
                        host = host.rsplit(":", 1)[0].strip() or None
                except Exception:
                    host = None
                if not host:
                    _, ep_line, _ = exec_sudo(
                        ssh, server,
                        "awk '/^[[:space:]]*Endpoint[[:space:]]*=/{sub(/^[^=]*=/, ""); "
                        "gsub(/^[[:space:]]+|[[:space:]]+$/, ""); print; exit}' "
                        "/etc/wireguard/clients/*.conf 2>/dev/null || true",
                    )
                    ep_line = (ep_line or "").strip()
                    if ep_line:
                        host = ep_line.rsplit(":", 1)[0].strip() or None
                if host:
                    profiles.rewrite_client_endpoints(server, host)
                else:
                    profiles.rewrite_client_endpoint_ports(server, v_port)

            
            # 3c) Address (подсеть сервера) → Address клиентов + AllowedIPs peers
            if v_addr is not None and old_server_addr and old_server_addr != v_addr:
                try:
                    profiles.rewrite_client_subnet(server, old_server_addr, v_addr)
                except StepError:
                    raise
                except Exception as e:
                    raise StepError(
                        "rewrite_subnet", -1, title="Смена подсети",
                        detail=str(e)[:400],
                    )

# 4) Применение к работающему интерфейсу — только для port/address
            #    (endpoint/dns — клиентские, рестарта не требуют).
            if iface_change:
                code, _, e3 = exec_sudo(ssh, server, "systemctl restart wg-quick@wg0")
                if code != 0:
                    _rollback_wg0(ssh, server, bak_path)
                    raise StepError("update_config_apply", code, title="Применение конфигурации",
                                    detail=(e3 or "wg-quick restart завершился с ошибкой").strip()[:500])
                _, active_out, _ = exec_sudo(
                    ssh, server, "wg show wg0 >/dev/null 2>&1 && echo active || echo inactive"
                )
                if active_out.strip() != "active":
                    _rollback_wg0(ssh, server, bak_path)
                    raise StepError(
                        "update_config_apply", -1, title="Применение конфигурации",
                        detail="после перезапуска интерфейс wg0 не активен; конфиг откатан",
                    )
        finally:
            ssh.close()
        return {}

    def get_actions(self, server_id: str) -> List[ServiceAction]:
        status = self.get_status(server_id) or {}
        installed = bool(status.get("installed"))
        items: List[ServiceAction] = []
        if not installed:
            items.append(ServiceAction(
                "install", "🟢 Установить", style="primary", task_title="установка",
            ))
            items.append(ServiceAction(
                "sync", "🔵 Синхронизировать", task_title="синхронизация",
            ))
            return items
        if status.get("needs_migration"):
            items.append(ServiceAction(
                "confirm_migrate", "🔄 Выполнить миграцию",
                style="primary", task_title="миграция",
            ))
            items.append(ServiceAction(
                "sync", "🔵 Синхронизировать", task_title="синхронизация",
            ))
            return items
        items.append(ServiceAction(
            "sync", "🔵 Синхронизировать", task_title="синхронизация",
        ))
        items.append(ServiceAction(
            "set_endpoint", "✏️ Изменить Endpoint", task_title="смена Endpoint",
        ))
        items.append(ServiceAction(
            "add", "➕ Добавить профиль", group="profiles", task_title="добавление профиля",
        ))
        items.append(ServiceAction(
            "confirm_remove", "🗑 Удалить сервис", style="danger", task_title="удаление",
        ))
        return items

    def fetch_profile_config(self, server_id: str, name: str) -> bytes:
        name = validate_profile_name(name)
        if not (read_cache(self.manifest.id, server_id).get("endpoint") or "").strip():
            raise RuntimeError(
                "Endpoint не настроен. Укажите внешний IP или домен в настройках "
                "сервиса — без него конфиг клиентам бесполезен."
            )
        server = find_server(server_id)
        if not server:
            raise RuntimeError("Сервер не найден")
        ssh = create_ssh_client(server)
        try:
            sftp = ssh.open_sftp()
            try:
                with sftp.file(f"/etc/wireguard/clients/{name}.conf", "r") as f:
                    return f.read()
            finally:
                sftp.close()
        finally:
            ssh.close()