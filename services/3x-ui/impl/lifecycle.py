# -*- coding: utf-8 -*-
"""Установка/удаление/обновление 3x-ui на сервере + выбор источника артефакта.

Логика источника (согласовано с пользователем):
    GitHub свежее кэша  → source='github' (сервер тянет сам) +
                          параллельный докач в кэш (делает вызывающий/job);
    паритет версий      → source='push' (scp из кэша);
    GitHub недоступен   → source='push' + пометка «свежесть не проверена».

Self-healing: провал fetch с GitHub на сервере → авто-fallback на push
(если версия есть в кэше) — передаём fallback_local_tarball в installer.

Удаление — по образцу их uninstall: остановка, удаление /usr/local/x-ui,
/usr/bin/x-ui, unit, /etc/x-ui (state! — только с явного params['remove_data']),
jail-файлы fail2ban. /var/log/x-ui сохраняем (диагностика), как их скрипт.
"""
from __future__ import annotations

from typing import Any, Dict

from core.integrator import StepError, StepRunner
from core.ssh import create_ssh_client

from . import installer, release_cache, releases, templates
from .releases import ReleaseError


def resolve_source(params: Dict[str, Any], default_arch: str) -> Dict[str, Any]:
    """Решить источник артефакта: сравнить GitHub latest с кэшем.

    Возвращает дополненные params: source, local_tarball,
    fallback_local_tarball, cache_stale (GitHub недоступен — не проверена
    свежесть). UI покажет это в превью шага 3 (этап 3).
    """
    tag = str(params.get("tag") or "")
    arch = str(params.get("arch") or default_arch)
    out = dict(params)
    out["arch"] = arch

    cached = release_cache.list_cached_versions()
    has_cache = bool(tag) and release_cache.has_version(tag, arch)

    try:
        latest = releases.fetch_latest_tag().lstrip("v")
    except ReleaseError as e:
        # GitHub лежит с точки зрения бота → кэш, честная пометка
        if not cached:
            raise ReleaseError(
                f"GitHub недоступен и в кэше нет ни одной версии ({arch}): {e}"
            )
        # самой свежей в кэше; если пользователь просил конкретную и она
        # есть — берём её, иначе последнюю кэшированную
        if tag and release_cache.has_version(tag, arch):
            fallback_tag = tag
        else:
            fallback_tag = cached[0]
        out["tag"] = fallback_tag
        out["source"] = "push"
        out["cache_stale"] = True
        out["local_tarball"] = str(release_cache.tarball_path(fallback_tag, arch))
        if fallback_tag != tag:
            out["fallback_downgrade"] = True
        return out

    if not tag:
        tag = latest
        out["tag"] = tag
        has_cache = release_cache.has_version(tag, arch)

    if has_cache and not releases.is_version_newer(latest, tag):
        # паритет (или кэш свежее — так не бывает, но безопасно): локально
        out["source"] = "push"
        out["local_tarball"] = str(release_cache.tarball_path(tag, arch))
    else:
        # на GitHub свежее (или в кэше нет): сервер тянет сам. Фолбэк для
        # self-healing — самый свежий кэш той же arch, пусть и старее тега
        # (лучше рабочая старая версия, чем никакая; пометку ставит installer)
        out["source"] = "github"
        fb = tag if has_cache else (cached[0] if cached else None)
        if fb:
            out["fallback_tag"] = fb
            out["fallback_local_tarball"] = str(release_cache.tarball_path(fb, arch))
    return out


def install(server: dict, params: Dict[str, Any], emit, *, resolved: bool = False) -> StepRunner:
    """Установка с авто-выбором источника (resolve_source) и прогоном.

    resolved=True: источник уже резолвнут вызывающим (do_install резолвит
    ДО прогона — превью шага 3 и установка видят один выбор; повторный
    резолв означал бы второй fetch_latest и возможный другой ответ).
    """
    if not resolved:
        arch = str(params.get("arch") or release_cache.default_arch())
        params = resolve_source(params, arch)

    return installer.run_install(
        server, params, emit,
        source=params["source"],
        local_tarball=params.get("local_tarball"),
        fallback_local_tarball=params.get("fallback_local_tarball"),
        fallback_tag=params.get("fallback_tag"),
    )


def update(server: dict, params: Dict[str, Any], emit) -> StepRunner:
    """Обновление установленного 3x-ui. Тот же прогон, что install:
    распаковка поверх сохраняет /etc/x-ui (state), x-ui migrate доводит БД.
    В params тот же источник-резолвер."""
    return install(server, params, emit)


def remove(server: dict, params: Dict[str, Any], emit) -> StepRunner:
    """Удаление 3x-ui (по мотивам их uninstall, наши шаги).

    params['remove_data']: True → снести и /etc/x-ui (SQLite-база,
    инбаунды, клиенты). False (по умолчанию) → state сохраняется,
    переустановка поднимет всё как было.
    """
    remove_data = bool(params.get("remove_data"))
    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit)
    try:
        runner.run("stop_service", "systemctl stop x-ui 2>/dev/null; exit 0",
                   title="Остановка x-ui.service")
        runner.run(
            "remove_code",
            f"systemctl disable x-ui 2>/dev/null; rm -rf {templates.XUI_FOLDER}; exit 0",
            title="Удаление /usr/local/x-ui",
        )
        runner.run(
            "remove_cli_unit",
            f"rm -f {templates.XUI_BIN} {templates.XUI_UNIT} && systemctl daemon-reload",
            title="Удаление CLI и systemd unit",
        )
        if remove_data:
            runner.run(
                "remove_data",
                f"rm -rf {templates.XUI_ETC}",
                title="Удаление /etc/x-ui (база данных, инбаунды)",
            )
        else:
            runner.emit("• /etc/x-ui сохранён (state; переустановка поднимет как было)")
        runner.run(
            "remove_iplimit_jail",
            f"rm -f {templates.IPLIMIT_JAIL} {templates.IPLIMIT_FILTER} "
            f"{templates.IPLIMIT_ACTION} {templates.IPLIMIT_BACKEND} && "
            "(fail2ban-client -t 2>/dev/null && systemctl restart fail2ban 2>/dev/null; exit 0)",
            title="Удаление jail IP Limit из fail2ban",
        )
        runner.emit("• /var/log/x-ui сохранён (диагностика)")
        return runner
    finally:
        ssh.close()
