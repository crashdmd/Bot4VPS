# -*- coding: utf-8 -*-
"""3x-ui - интегрированный сервис Bot4VPS: панель управления Xray.

Этап 1: контракт Service + кэш релизов. Этап 2: установка/удаление/
обновление (lifecycle/installer), sync реального состояния с сервера
(версия, статус юнита, panel_url, креды из install-result.env → enc1:).

Кэш (data/services/3x-ui/<server>.json):
    {installed, version, active, enabled, panel_url, username(enc1:),
     api_token(enc1:), installed_at, service_id, synced_at}
Кэш артефактов релизов — data/services/3x-ui/version/<tag>/<arch>/
(release_cache.py; здесь не пересекается).

Видение: бот — инструмент, а не контроллер. Инбаунды/клиенты/подписки —
территория панели 3x-ui; бот ставит и сопровождает сервис-уровень.
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core.integrator import (
    Parameter,
    Service as BaseService,
    ServiceAction,
    StepError,
    StepRunner,
    read_cache,
    sync_progress,
    update_cache,
)
from core.ssh import create_ssh_client, exec_sudo
from core.ssl import clear_ssl_check, enable_ssl_check
from core.storage import find_server
from core.task_manager import TaskResult

from . import certs, dbops, fakesite, installer, lifecycle, manage, release_cache, releases, templates, validation
from .releases import ReleaseError


class Service(BaseService):
    """3x-ui: установка из кэша/GitHub + сервис-уровень."""

    def params_schema(self) -> list:
        # Параметры собираются модалкой установки (этап 3): креды, порт,
        # web base path, SSL-режим. Схема мастера не используется.
        return []

    def persistent_cache_fields(self) -> tuple[str, ...]:
        """Расширения 3x-ui, живущие поверх live-пробы панели."""
        return ("fakesite",)

    def card_action_requires_sync(self, action: str) -> bool:
        # Информация SelfSNI — только уже сохранённый JSON; SSH/live sync
        # здесь означал бы медленную и ненужную проверку nginx/сертификата.
        return action != "fakesite_info"

    def get_actions(self, server_id: str) -> List[ServiceAction]:
        items = super().get_actions(server_id)
        if not server_id:
            items.extend((
                ServiceAction("fakesite_install", "Установить SelfSNI",
                              task_title="установка SelfSNI"),
                ServiceAction("fakesite_remove", "Удалить SelfSNI",
                              style="danger", task_title="удаление SelfSNI"),
            ))
        return items


    def prepare_install_params(
        self, server_id: str, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        return validation.validate_install_params(params)

    async def do_install(
        self, server_id: str, params: Dict[str, Any],
        progress_cb: Callable[[str], Awaitable[None]],
    ) -> TaskResult:
        server = find_server(server_id)
        if not server:
            return TaskResult(success=False, error="Сервер не найден")
        try:
            params = validation.validate_install_params(params)
        except validation.ValidationError as e:
            return TaskResult(success=False, error=str(e))
        # IP сервера — для LE IP-сертификата и URL при skip
        if params.get("ssl_mode") == "ip" and not params.get("server_ip"):
            params["server_ip"] = str(server.get("host") or "")
        # Резолв источника ДО прогона: 1) превью шага 3 и установка видят
        # один и тот же выбор; 2) фоновая докачка в кэш стартует сразу и
        # независимо от исхода установки (медленный канал — норма, результат
        # не ждём; сбой установки не должен оставлять кэш пустым).
        try:
            arch = str(params.get("arch") or release_cache.default_arch())
            params = lifecycle.resolve_source(params, arch)
        except lifecycle.ReleaseError as e:
            return TaskResult(success=False, error=str(e))
        self._schedule_arch_pull(params)
        async with sync_progress(progress_cb) as emit:
            try:
                runner = await asyncio.to_thread(
                    lifecycle.install, server, params, emit,
                    resolved=True,
                )
            except Exception as e:
                return TaskResult(success=False, error=str(e))
        self._sync_install_result(server_id, runner)
        res = getattr(runner, "result", {})
        source = res.get("source", "github")
        out = f"3x-ui установлен (источник: {source}). Шаги: " + ", ".join(runner.completed)
        fw = res.get("firewall") or {}
        if fw.get("opened"):
            ports_note = ", ".join(f"{p}/tcp" for p in fw["opened"])
            out += (f". ВНИМАНИЕ: в firewall открыт порт {ports_note} — "
                    "панель доступна из интернета")
        elif fw.get("skipped"):
            ports_note = ", ".join(f"{p}/tcp" for p in fw["skipped"])
            out += f". Порт {ports_note} НЕ открыт в firewall — добавьте правило вручную"
        return TaskResult(success=True, output=out)

    def _schedule_arch_pull(self, params: Dict[str, Any]) -> None:
        """Фоновая докачка релиза в кэш (медленный канал — до 30 минут).

        Стартует сразу при старте установки и НЕ зависит от её исхода:
        следующий сервер получит артефакт из кэша. Качаем, когда ставим с
        GitHub (в кэше нет нужной версии/arch) — при source=push она уже
        там.
        """
        arch = str(params.get("arch") or "")
        tag = str(params.get("tag") or "")
        if not arch or not tag:
            return
        if params.get("source") == "push":
            return
        if release_cache.has_version(tag, arch):
            return

        def _pull() -> None:
            try:
                release_cache.download(tag, arch, lambda _line: None)
                print(f"[3x-ui] {tag}/{arch} докачана в кэш "
                      "(параллельно установке с GitHub)", flush=True)
            except Exception as e:
                print(f"[3x-ui] фоновая докачка {tag}/{arch} не удалась: {e}",
                      flush=True)

        try:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, _pull)
        except RuntimeError:
            _pull()

    async def do_remove(
        self, server_id: str, params: Dict[str, Any],
        progress_cb: Callable[[str], Awaitable[None]],
    ) -> TaskResult:
        server = find_server(server_id)
        if not server:
            return TaskResult(success=False, error="Сервер не найден")
        async with sync_progress(progress_cb) as emit:
            runner = await asyncio.to_thread(lifecycle.remove, server, params, emit)
        note = "" if params.get("remove_data") else " /etc/x-ui сохранён"
        return TaskResult(
            success=True,
            output=f"3x-ui удалён.{note} Шаги: " + ", ".join(runner.completed),
        )

    async def do_update(
        self, server_id: str, params: Dict[str, Any],
        progress_cb: Callable[[str], Awaitable[None]],
    ) -> TaskResult:
        server = find_server(server_id)
        if not server:
            return TaskResult(success=False, error="Сервер не найден")
        async with sync_progress(progress_cb) as emit:
            try:
                runner = await asyncio.to_thread(lifecycle.update, server, params, emit)
            except Exception as e:
                return TaskResult(success=False, error=str(e))
        self._sync_install_result(server_id, runner)
        source = getattr(runner, "result", {}).get("source", "github")
        return TaskResult(
            success=True,
            output=f"3x-ui обновлён (источник: {source}). Шаги: "
            + ", ".join(runner.completed),
        )

    # ------------------------------------------------------------
    # Синхронизация состояния (read-only)
    # ------------------------------------------------------------

    def _panel_display_host(self, server: Dict[str, Any], fakesite_state: Any,
                            cert_file: str, key_file: str) -> str:
        host = manage.panel_display_host(server)
        if not isinstance(fakesite_state, dict) or not fakesite_state.get("present"):
            return host
        domain = fakesite_state.get("domain")
        certificate = fakesite_state.get("certificate")
        certificate_key = fakesite_state.get("certificate_key")
        if not all(isinstance(value, str)
                   for value in (domain, certificate, certificate_key)):
            return host
        if not cert_file or not key_file:
            return host
        if certificate != cert_file or certificate_key != key_file:
            return host
        try:
            return validation.validate_domain(domain)
        except validation.ValidationError:
            return host

    def _read_live(self, server_id: str, ssh=None) -> Dict[str, Any]:
        """Живое чтение: установленность, версия, юнит, panel_url, креды.

        ``ssh``: готовое соединение (общий фоновый job проверяет все сервисы
        сервера за один коннект) — тогда не создаём и не закрываем своё."""
        server = find_server(server_id)
        if not server:
            return {}
        own = ssh is None
        if own:
            ssh = create_ssh_client(server)
        try:
            # arch целевого сервера — нужна модалке ДО установки (арх-политика)
            arch_raw = ssh_probe(ssh, server, "uname -m 2>/dev/null").strip()
            arch_map = {"x86_64": "amd64", "amd64": "amd64",
                        "aarch64": "arm64", "arm64": "arm64"}
            arch = arch_map.get(arch_raw)

            installed = ssh_probe(ssh, server,
                f"test -x {templates.XUI_FOLDER}/x-ui && echo yes || echo no") == "yes"
            if not installed:
                return {"installed": False, "service_id": "3x-ui", "arch": arch}

            active = ssh_probe(ssh, server,
                "systemctl is-active x-ui 2>/dev/null") == "active"
            enabled = ssh_probe(ssh, server,
                "systemctl is-enabled x-ui 2>/dev/null") == "enabled"
            # версия: у Go-бинаря нет подкоманды version (печатает
            # «Invalid subcommands») — только флаг -v
            version = ssh_probe(ssh, server,
                f"{templates.XUI_FOLDER}/x-ui -v 2>/dev/null").strip() or None
            settings_show = ssh_probe(ssh, server,
                f"{templates.XUI_FOLDER}/x-ui setting -show true 2>/dev/null")
            port = _grep_setting(settings_show, "port")
            web_base_path = _grep_setting(settings_show, "webBasePath")

            # panel_url: схема https если сертификат настроен, иначе http
            cert = ssh_probe(ssh, server,
                f"{templates.XUI_FOLDER}/x-ui setting -getCert true 2>/dev/null")
            cert_file = _grep_setting(cert, "cert")
            key_file = _grep_setting(cert, "key")
            scheme = "https" if cert_file else "http"
            panel_url = None
            if port:
                fakesite_state = (read_cache("3x-ui", server_id) or {}).get("fakesite")
                host = self._panel_display_host(server, fakesite_state, cert_file, key_file)
                path = (web_base_path or "").strip("/")
                panel_url = f"{scheme}://{host}:{port}/{path}"

            # креды из install-result.env (наш парсинг — не source!)
            creds = {}
            raw = ssh_probe(ssh, server,
                f"if [ -r {templates.XUI_INSTALL_RESULT} ]; then cat {templates.XUI_INSTALL_RESULT}; fi")
            for line in raw.splitlines():
                line = line.strip()
                if not line or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                creds[key.strip()] = value.strip().strip("'").strip('"')
            # BBR и geo-файлы — для карточки (этап 4); при неустановленном
            # сервисе сюда не доходим (installed=False выше)
            bbr = manage.read_bbr_state(ssh, server)
            geo = manage.read_geo_state(ssh, server)
            # сертификаты (зеркало их CLI SSL-меню): домены /root/cert,
            # сроки; cert_file уже прочитан — не пробиваем повторно
            cert_state = certs.read_state(ssh, server, cert_file or None)
            return {
                "installed": True,
                "version": version,
                "active": active,
                "enabled": enabled,
                "panel_url": panel_url,
                "port": port,
                "web_base_path": web_base_path,
                "scheme": scheme,
                "username": creds.get("XUI_USERNAME"),
                "password": creds.get("XUI_PASSWORD"),
                "api_token": creds.get("XUI_API_TOKEN"),
                "arch": arch,
                "bbr": bbr,
                "geo": geo,
                "cert": cert_state,
                "service_id": "3x-ui",
            }
        finally:
            if own:
                ssh.close()

    async def do_sync(self, server_id: str, ssh=None) -> Dict[str, Any]:
        live = await asyncio.to_thread(self._read_live, server_id, ssh)
        # секреты live — plaintext; в кэш (через integrator.sync → write_cache)
        # должны попадать уже enc1:
        if live.get("installed"):
            live = _encrypt_secrets(live)
        return live

    def get_state(self, server_id: str) -> Dict[str, Any]:
        """Live-чтение для карточки. Креды НЕ отдаём (как в их CLI: старые
        не показываем и не спрашиваем — смена = задать новый). Единственное
        место показа кредов — финальное окно установки (install-result)."""
        data = self._read_live(server_id)
        for key in ("username", "password", "api_token"):
            data.pop(key, None)
        return data

    def get_status(self, server_id: str) -> Dict[str, Any]:
        """Кэш-статус для списков UI. Секреты НЕ включаем (спискам не нужны,
        расшифровка — по запросу карточки через get_install_result).

        Только кэш, БЕЗ сети: раньше здесь был release_inventory() с живым
        запросом latest-тега к GitHub на каждый сервер — страницу списка это
        тормозило (при душёном GitHub — до таймаута × серверы), а потребляли
        этот ключ никто (визард берёт источник через resolve-source)."""
        cache = read_cache("3x-ui", server_id) or {}
        return {
            "installed": bool(cache.get("installed")),
            "version": cache.get("version"),
            "active": cache.get("active"),
            "enabled": cache.get("enabled"),
            "panel_url": cache.get("panel_url"),
            "port": cache.get("port"),
            "web_base_path": cache.get("web_base_path"),
            "creds_present": bool(cache.get("username") and cache.get("password")),
            "service_id": "3x-ui",
        }

    def get_install_result(self, server_id: str) -> Dict[str, Any]:
        """Креды панели из кэша (расшифрованные) — для финального окна и
        карточки. Отдельный от get_status метод: секреты отдаются только
        по явному запросу, не в массовых списках."""
        cache = _decrypt_secrets(read_cache("3x-ui", server_id) or {})
        return {
            "username": cache.get("username"),
            "password": cache.get("password"),
            "api_token": cache.get("api_token"),
            "panel_url": cache.get("panel_url"),
            "creds_present": bool(cache.get("username") and cache.get("password")),
            "creds_stale": bool(cache.get("creds_stale")),
        }

    def _sync_install_result(self, server_id: str, runner: StepRunner) -> None:
        """После install/update: перечитать живое состояние и пополнить кэш.

        Секреты (password, api_token) пишутся enc1: — единая точка ниже;
        _read_live вернул plaintext, шифруем перед write_cache.
        """
        try:
            live = self._read_live(server_id)
        except Exception:
            live = {}
        res = getattr(runner, "result", None) or {}
        merged = dict(live)
        merged["installed"] = True
        merged["installed_at"] = res.get("tag")
        # при недоступности live (панель только что перезапущена и т.п.) —
        # креды из результата установки, чтобы финальное окно не было пустым
        if not merged.get("username") and res.get("install_result"):
            ir = res["install_result"]
            merged.setdefault("username", ir.get("XUI_USERNAME"))
            merged.setdefault("password", ir.get("XUI_PASSWORD"))
            merged.setdefault("api_token", ir.get("XUI_API_TOKEN"))
            merged.setdefault("panel_url", ir.get("XUI_ACCESS_URL"))
        # служебные ключи интегратора не проходят как **fields (service_id —
        # позиционный аргумент update_cache; synced_at она ставит сама)
        for k in ("service_id", "synced_at"):
            merged.pop(k, None)
        update_cache("3x-ui", server_id, **_encrypt_secrets(merged))

    # ------------------------------------------------------------
    # Карточка сервиса (этап 4): быстрые действия card_*
    #
    # Префикс card_ — контракт «лёгкого» действия: роутер дергает их
    # напрямую (без очереди задач), в отличие от do_* (enqueue/install и
    # т.п.). Кэш после мутации обновляет вызывающий (роутер) через sync —
    # creds перечитаются из install-result.env и зашифруются enc1:.
    # ------------------------------------------------------------

    def _card_ssh(self, server_id: str):
        """SSH-коннект + сервер для card_*; StepError при отсутствии."""
        from core.integrator import StepError
        server = find_server(server_id)
        if not server:
            raise StepError("server", -1, title="Карточка 3x-ui",
                            detail="Сервер не найден")
        return create_ssh_client(server), server

    def _card_check_installed(self, ssh, server) -> None:
        from core.integrator import StepError
        installed = ssh_probe(ssh, server,
            f"test -x {templates.XUI_FOLDER}/x-ui && echo yes || echo no") == "yes"
        if not installed:
            raise StepError("not_installed", -1, title="Карточка 3x-ui",
                            detail="3x-ui на сервере не установлен")

    def card_unit_action(self, server_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """start/stop/restart/restart_xray юнита x-ui."""
        action = str((params or {}).get("action") or "")
        ssh, server = self._card_ssh(server_id)
        try:
            self._card_check_installed(ssh, server)
            active = manage.unit_action(ssh, server, action)
            return {"success": True, "active": active,
                    "output": f"x-ui: {manage.UNIT_TITLES.get(action, action)}, "
                              f"юнит теперь {active}"}
        finally:
            ssh.close()

    def card_set_autostart(self, server_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        enabled = bool((params or {}).get("enabled"))
        ssh, server = self._card_ssh(server_id)
        try:
            self._card_check_installed(ssh, server)
            on = manage.set_autostart(ssh, server, enabled)
            return {"success": True, "enabled": on,
                    "output": f"Автозагрузка x-ui {'включена' if on else 'выключена'}"}
        finally:
            ssh.close()

    def card_change_username(self, server_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        username = validation.validate_username((params or {}).get("username") or "")
        restart = bool((params or {}).get("restart"))
        ssh, server = self._card_ssh(server_id)
        try:
            self._card_check_installed(ssh, server)
            manage.change_username(ssh, server, username, restart)
            return {"success": True,
                    "output": f"Логин панели изменён: {username}"
                              + ("; сервис перезапущен" if restart else "; перезапустите сервис для применения")}
        finally:
            ssh.close()

    def card_change_password(self, server_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        password = validation.validate_password((params or {}).get("password") or "")
        restart = bool((params or {}).get("restart"))
        ssh, server = self._card_ssh(server_id)
        try:
            self._card_check_installed(ssh, server)
            manage.change_password(ssh, server, password, restart)
            return {"success": True,
                    "output": "Пароль панели изменён (обновлён в secrets бота)"
                              + ("; сервис перезапущен" if restart else "; перезапустите сервис для применения")}
        finally:
            ssh.close()

    def card_change_port(self, server_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        port = validation.validate_port((params or {}).get("port"))
        restart = bool((params or {}).get("restart"))
        close_old_port = bool((params or {}).get("close_old_port", True))
        ssh, server = self._card_ssh(server_id)
        try:
            self._card_check_installed(ssh, server)
            res = manage.change_port(ssh, server, port, restart,
                                     close_old_port=close_old_port)
            return {"success": True, **res,
                    "output": f"Порт панели: {res['port']}; адрес: {res['panel_url']}"
                              + res.get("fw_notes", "")
                              + ("; сервис перезапущен" if restart else "")}
        finally:
            ssh.close()

    def card_change_path(self, server_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Изменение web base path: свой путь или случайный (path не задан)."""
        restart = bool((params or {}).get("restart"))
        path = str((params or {}).get("path") or "").strip() or None
        ssh, server = self._card_ssh(server_id)
        try:
            self._card_check_installed(ssh, server)
            res = manage.change_path(ssh, server, path, restart)
            return {"success": True, **res,
                    "output": f"Новый web base path: {res['web_base_path']}; "
                              f"адрес: {res['panel_url']}"
                              + ("; сервис перезапущен" if restart else "")}
        finally:
            ssh.close()

    def card_reset_settings(self, server_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Полный сброс: креды → admin/admin (их дефолт), честно говорим об этом."""
        restart = bool((params or {}).get("restart"))
        ssh, server = self._card_ssh(server_id)
        try:
            self._card_check_installed(ssh, server)
            res = manage.reset_settings(ssh, server, restart)
            return {"success": True, **res,
                    "output": "Настройки панели сброшены: логин/пароль admin/admin, "
                              f"порт {res['port']}. СМЕНИТЕ ПАРОЛЬ (карточка → Смена пароля)."}
        finally:
            ssh.close()

    def card_set_bbr(self, server_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        enable = bool((params or {}).get("enabled"))
        ssh, server = self._card_ssh(server_id)
        try:
            self._card_check_installed(ssh, server)
            res = manage.set_bbr(ssh, server, enable)
            return {"success": True, **res,
                    "output": f"BBR {'включён' if res['cc'] == 'bbr' else 'выключен'} "
                              f"(cc: {res['cc']}, qdisc: {res['qdisc']})"}
        finally:
            ssh.close()

    def card_update_geo(self, server_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        restart = bool((params or {}).get("restart", True))
        ssh, server = self._card_ssh(server_id)
        try:
            self._card_check_installed(ssh, server)
            dates = manage.update_geo(ssh, server, restart)
            note = "; сервис перезапущен" if restart else ""
            return {"success": True, "geo": dates,
                    "output": "Geo-файлы обновлены: "
                              + ", ".join(f"{k} ({v})" for k, v in dates.items()) + note}
        finally:
            ssh.close()

    # ------------------------------------------------------------------
    # Сертификат панели (зеркало их CLI SSL-меню) — certs.py
    # ------------------------------------------------------------------

    async def _cert_op(self, server_id: str, fn, progress_cb) -> Any:
        """Обвязка do_cert_*: SSH + installed-check + поток с прогрессом.
        fn(ssh, server, emit) → dict. Возвращает (res, None) либо
        (None, TaskResult с ошибкой)."""
        server = find_server(server_id)
        if not server:
            return None, TaskResult(success=False, error="Сервер не найден")

        async with sync_progress(progress_cb) as emit:
            def run():
                ssh = create_ssh_client(server)
                try:
                    self._card_check_installed(ssh, server)
                    return fn(ssh, server, emit)
                finally:
                    ssh.close()

            try:
                return await asyncio.to_thread(run), None
            except StepError as e:
                # str(StepError) — только заголовок; настоящий вывод команды
                # (stdout/stderr acme.sh и т.п.) лежит в e.detail — без него
                # пользователь видит бесполезное «завершилась с ошибкой (код 1)»
                return None, TaskResult(success=False, error=str(e), output=e.detail)
            except Exception as e:
                return None, TaskResult(success=False, error=str(e))

    async def do_cert_issue_domain(self, server_id: str, params: Dict[str, Any],
                                   progress_cb) -> TaskResult:
        """Выпуск LE-сертификата для домена (их пункт 1). Движок — выбор
        администратора в модалке: acme (их CLI, /root/cert) или certbot
        (/etc/letsencrypt). По умолчанию (не указан) — acme, как их CLI."""
        try:
            domain = validation.validate_domain((params or {}).get("domain") or "")
        except validation.ValidationError as e:
            return TaskResult(success=False, error=str(e))
        engine = str((params or {}).get("engine") or "acme").strip().lower()
        if engine not in ("acme", "certbot"):
            return TaskResult(success=False,
                              error="Движок: acme или certbot")
        fn = certs.issue_domain_certbot if engine == "certbot" else certs.issue_domain
        res, err = await self._cert_op(
            server_id,
            lambda ssh, srv, emit: fn(
                ssh, srv, domain, (params or {}).get("port") or 80,
                bool((params or {}).get("set_panel", True)), emit),
            progress_cb)
        if err:
            return err
        note = (f"; панель: {res['panel_url']}" if res.get("panel_url")
                else "; путь панели не менялся")
        eng_label = "certbot" if engine == "certbot" else "acme.sh"
        return TaskResult(success=True,
                          output=f"Сертификат для {res['domain']} выпущен "
                                 f"(Let's Encrypt, {eng_label}, авто-renew){note}")

    async def do_cert_issue_ip(self, server_id: str, params: Dict[str, Any],
                               progress_cb) -> TaskResult:
        """Короткоживущий сертификат для IP (~6 дней, их пункт 6)."""
        try:
            ip = validation.validate_ipv4((params or {}).get("ip") or "")
            ipv6_raw = str((params or {}).get("ipv6") or "").strip()
            ipv6 = validation.validate_ipv6(ipv6_raw) if ipv6_raw else None
        except validation.ValidationError as e:
            return TaskResult(success=False, error=str(e))
        res, err = await self._cert_op(
            server_id,
            lambda ssh, srv, emit: certs.issue_ip(
                ssh, srv, ip, ipv6, (params or {}).get("port") or 80,
                bool((params or {}).get("set_panel", True)), emit),
            progress_cb)
        if err:
            return err
        note = f"; панель: {res['panel_url']}" if res.get("panel_url") else ""
        return TaskResult(success=True,
                          output=f"Сертификат для {ip} выпущен (~6 дней, "
                                 f"обновляется автоматически){note}")

    async def do_cert_renew(self, server_id: str, params: Dict[str, Any],
                            progress_cb) -> TaskResult:
        """Принудительное продление (их пункт 3). Движок — выбор в модалке;
        по умолчанию движок серта панели (продлевать должен владелец)."""
        try:
            domain = validation.validate_certificate_identifier((params or {}).get("domain") or "")
        except validation.ValidationError as e:
            return TaskResult(success=False, error=str(e))
        engine = str((params or {}).get("engine") or "").strip().lower()
        if engine not in ("acme", "certbot", ""):
            return TaskResult(success=False,
                              error="Движок: acme или certbot")
        fn = certs.renew_certbot if engine == "certbot" else certs.renew
        res, err = await self._cert_op(
            server_id,
            lambda ssh, srv, emit: fn(ssh, srv, domain, emit),
            progress_cb)
        if err:
            return err
        eng_label = "certbot" if engine == "certbot" else "acme.sh"
        return TaskResult(success=True,
                          output=f"Сертификат {res['domain']} продлён ({eng_label}); "
                                 "хук авто-renew обновит файлы и перезапустит панель")

    async def do_cert_remove(self, server_id: str, params: Dict[str, Any],
                             progress_cb) -> TaskResult:
        """Отозвать и удалить сертификат (их пункт 2). Движок — как у
        продления: удаляет тот, чей это сертификат."""
        try:
            domain = validation.validate_certificate_identifier((params or {}).get("domain") or "")
        except validation.ValidationError as e:
            return TaskResult(success=False, error=str(e))
        engine = str((params or {}).get("engine") or "").strip().lower()
        if engine not in ("acme", "certbot", ""):
            return TaskResult(success=False,
                              error="Движок: acme или certbot")
        fn = (certs.remove_cert_certbot if engine == "certbot"
              else certs.remove_cert)
        res, err = await self._cert_op(
            server_id,
            lambda ssh, srv, emit: fn(ssh, srv, domain, emit),
            progress_cb)
        if err:
            return err
        note = "; пути сертификата панели сброшены" if res.get("panel_reset") else ""
        if res.get("domain") and res["domain"] != "ip":
            cleared = await asyncio.to_thread(clear_ssl_check, server_id, res["domain"])
            if cleared:
                note += "; SSL-мониторинг домена отключён"
        return TaskResult(success=True,
                          output=f"Сертификат {res['domain']} отозван и удалён{note}")

    def fetch_logs(self, server_id: str, name: str, tail: int = 200) -> str:
        """Логи юнита x-ui (generic-контракт /logs/{name}; name игнорируем —
        у сервиса один юнит, Xray пишется в тот же журнал)."""
        ssh, server = self._card_ssh(server_id)
        try:
            return manage.fetch_logs(ssh, server, tail)
        finally:
            ssh.close()

    def card_fakesite_info(self, server_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """SelfSNI usage data from cache only — deliberately no SSH."""
        state = read_cache("3x-ui", server_id) or {}
        fakesite_state = state.get("fakesite")
        if not isinstance(fakesite_state, dict):
            fakesite_state = {"present": False}
        return {"success": True, "fakesite": dict(fakesite_state)}

    async def _fakesite_op(self, server_id: str, fn, progress_cb) -> Any:
        """SSH + installed check + synchronous SelfSNI operation with progress."""
        server = find_server(server_id)
        if not server:
            return None, TaskResult(success=False, error="Сервер не найден")
        async with sync_progress(progress_cb) as emit:
            def run():
                ssh = create_ssh_client(server)
                try:
                    self._card_check_installed(ssh, server)
                    return fn(ssh, server, emit)
                finally:
                    ssh.close()
            try:
                return await asyncio.to_thread(run), None
            except StepError as e:
                return None, TaskResult(success=False, error=str(e), output=e.detail)
            except Exception as e:
                return None, TaskResult(success=False, error=str(e))

    async def do_fakesite_install(self, server_id: str, params: Dict[str, Any],
                                  progress_cb) -> TaskResult:
        """Install a random GitHub site for Reality Dest; does not touch inbounds."""
        try:
            domain = validation.validate_domain((params or {}).get("domain") or "")
        except validation.ValidationError as e:
            return TaskResult(success=False, error=str(e))
        previous = (read_cache("3x-ui", server_id) or {}).get("fakesite") or {}
        res, err = await self._fakesite_op(
            server_id,
            lambda ssh, srv, emit: fakesite.install(ssh, srv, domain, previous, emit),
            progress_cb,
        )
        if err:
            return err
        update_cache("3x-ui", server_id, fakesite=res)
        await asyncio.to_thread(enable_ssl_check, server_id, res["domain"])
        if progress_cb:
            await progress_cb("Назначение сертификата панели…")
        panel, panel_err = await self._fakesite_op(
            server_id,
            lambda ssh, srv, _emit: certs.set_paths(
                ssh, srv, res["certificate"], res["certificate_key"]),
            progress_cb,
        )
        if panel_err:
            return TaskResult(
                success=False,
                error="SelfSNI установлен, но сертификат панели не назначен. Повторите установку.",
                output=panel_err.output,
            )
        return TaskResult(
            success=True,
            output=(f"SelfSNI установлен: {res['domain']}; "
                    f"Dest {res['dest']}; SNI {res['sni']}; Xver 1; "
                    f"панель: {panel['panel_url']}"),
        )

    async def do_fakesite_remove(self, server_id: str, params: Dict[str, Any],
                                 progress_cb) -> TaskResult:
        """Remove only Bot4VPS SelfSNI configuration/content it can prove it owns."""
        previous = (read_cache("3x-ui", server_id) or {}).get("fakesite") or {}
        res, err = await self._fakesite_op(
            server_id,
            lambda ssh, srv, emit: fakesite.remove(ssh, srv, previous, emit),
            progress_cb,
        )
        if err:
            return err
        update_cache("3x-ui", server_id, fakesite={"present": False})
        removed_domain = str((previous or {}).get("domain") or "").strip()
        if removed_domain:
            await asyncio.to_thread(clear_ssl_check, server_id, removed_domain)
        suffix = "; прежний сайт восстановлен" if res.get("restored_content") else ""
        return TaskResult(success=True, output="SelfSNI удалён" + suffix)

    def card_export_db(self, server_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Экспорт x-ui.db: консистентная копия (sqlite3 .backup) → bytes.

        Чтение — не мутация, но оставляем card_-префикс: роутер action/
        дергает только card_*, и _sync_after после него лишним не будет.
        """
        ssh, server = self._card_ssh(server_id)
        try:
            self._card_check_installed(ssh, server)
            return dbops.export_db(ssh, server, server.get("name") or server_id)
        finally:
            ssh.close()

    async def do_db_import(self, server_id: str, params: Dict[str, Any],
                           progress_cb) -> TaskResult:
        """Импорт .db/.dump: файл уже в data/tmp (upload-эндпоинт положил),
        здесь — остановка панели, замена базы, migrate, авторестарт."""
        import os
        from pathlib import Path
        local_path = Path(str((params or {}).get("local_path") or ""))
        # только data/tmp бота: local_path приходит из upload-эндпоинта,
        # произвольные пути читать нельзя
        tmp_dir = (Path.cwd() / "data" / "tmp").resolve()
        try:
            inside = local_path.resolve().is_relative_to(tmp_dir)
        except (OSError, ValueError):
            inside = False
        if not inside or not local_path.is_file():
            return TaskResult(success=False, error="Файл импорта не найден")
        server = find_server(server_id)
        if not server:
            return TaskResult(success=False, error="Сервер не найден")

        def _read() -> bytes:
            with open(local_path, "rb") as f:
                data = f.read()
            os.unlink(local_path)  # tmp-файл живёт одну задачу
            return data

        async with sync_progress(progress_cb) as emit:
            def _import():
                ssh, srv = self._card_ssh(server_id)
                try:
                    self._card_check_installed(ssh, srv)
                    return dbops.import_db(ssh, srv, _read(), emit)
                finally:
                    ssh.close()
            try:
                res = await asyncio.to_thread(_import)
            except StepError as e:
                return TaskResult(success=False,
                                  error=str(e),
                                  output=getattr(e, "detail", None) or None)
        return TaskResult(success=True,
                          output="База восстановлена; панель перезапущена. "
                                 f"Прежняя база: {res.get('backup', 'сохранена')}")

    # ------------------------------------------------------------
    # Каталог релизов (тонкие прокси над impl/releases+release_cache;
    # UI вызывает через integrator.call — прямых импортов impl из web нет)
    # ------------------------------------------------------------

    def release_inventory(self) -> Dict[str, Any]:
        """Инвентарь для UI: версии в кэше, arch, что на GitHub."""
        info: Dict[str, Any] = {
            "cached_versions": release_cache.list_cached_versions(),
            "default_arch": None,
        }
        try:
            info["default_arch"] = release_cache.default_arch()
        except ReleaseError:
            pass  # arch машины бота не поддерживается — поле пустое, UI покажет
        try:
            info["latest_tag"] = releases.fetch_latest_tag()
        except ReleaseError as e:
            info["latest_error"] = str(e)
        return info

    def do_release_download(self, server_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Скачать релиз в кэш (кнопка «обновить кэш» / arch по спросу).

        server_id не используется — кэш общий на все серверы; параметр в
        сигнатуре для единообразия контракта do_*. Не ставит ничего.
        """
        tag = str(params.get("tag") or "")
        arch = params.get("arch")
        path = release_cache.download(tag, arch)
        return {"success": True, "path": str(path)}

    def do_resolve_source(self, server_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Превью источника для модалки (шаг 3): tag/source/пометки.

        arch: из params (модалка передаёт arch целевого сервера из /state),
        иначе дефолт (arch машины бота).
        """
        params = dict(params or {})
        try:
            default_arch = release_cache.default_arch()
        except ReleaseError:
            default_arch = "amd64"
        arch = params.get("arch") or default_arch
        out = lifecycle.resolve_source(params, default_arch)
        out["default_arch"] = default_arch
        out["arch_match"] = arch == default_arch
        return out


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------


def ssh_probe(ssh, server: dict, command: str) -> str:
    code, out, _ = exec_sudo(ssh, server, command, timeout=30)
    return out.strip()


def _grep_setting(text: str, key: str) -> Optional[str]:
    """«port: 54321» / «webBasePath: abc» из вывода x-ui setting -show."""
    for line in (text or "").splitlines():
        s = line.strip()
        if s.startswith(f"{key}:"):
            return s.split(":", 1)[1].strip() or None
    return None


# Секретные поля кэша: на диске — enc1: (core/secretbox), в памяти — plaintext.
# Единая точка преобразования — как _encrypt_passwords_for_disk в storage.py.
_SECRET_FIELDS = ("password", "api_token")


def _encrypt_secrets(data: Dict[str, Any]) -> Dict[str, Any]:
    from core.secretbox import encrypt
    out = dict(data)
    for f in _SECRET_FIELDS:
        v = out.get(f)
        if isinstance(v, str) and v:
            out[f] = encrypt(v)
    return out


def _decrypt_secrets(data: Dict[str, Any]) -> Dict[str, Any]:
    from core.secretbox import decrypt, is_encrypted
    out = dict(data)
    for f in _SECRET_FIELDS:
        v = out.get(f)
        if isinstance(v, str) and v and is_encrypted(v):
            out[f] = decrypt(v)
    return out
