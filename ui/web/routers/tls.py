"""HTTPS панели (Настройки → Безопасность → карточка «HTTPS»).

Механика — core/web_tls.py (детached-раннер с откатом юнита); здесь только
HTTP-слой:

- ``GET  /api/settings/web/tls``        — режим (config), фактический
  транспорт (юнит — единственная правда), метаданные сертификата;
- ``GET  /api/settings/web/tls/status`` — состояние раннера (поллинг
  прогресс-модали) + finalize_config(): web-процесс, переживший рестарт,
  применяет отложенный web.tls при успехе и выбрасывает при неудаче;
- ``POST /api/settings/web/tls/...``    — запуск операций. Содержимое
  сертификатов и ключей через API НЕ отдаётся и не логируется — только
  метаданные (subject/эмитент/срок).
"""
from __future__ import annotations

import asyncio
import re

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from ..deps import err

router = APIRouter(tags=["tls"])


def _launch_guard() -> None:
    """Общие проверки перед запуском операции (понятные тексты ошибок)."""
    from core.web_tls import busy, changeable

    ok, reason = changeable()
    if not ok:
        raise HTTPException(400, reason or "управление HTTPS недоступно")
    if busy():
        raise HTTPException(409, "Операция HTTPS уже выполняется — дождитесь её завершения")


def _domain_or_400(domain: str | None) -> str:
    domain = (domain or "").strip().lower()
    # FQDN: метки по букве/цифре/дефис (не в начале/конце), 1+ точка.
    # Суффикс «*.» разрешаем — wildcard домены Let's Encrypt существуют.
    if not re.fullmatch(r"(\*\.)?([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}", domain):
        raise HTTPException(
            400,
            "Укажите корректный домен, например panel.example.com "
            "(он должен указывать на этот сервер)",
        )
    return domain


def _email_or_400(email: str | None) -> str | None:
    email = (email or "").strip() or None
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(
            400,
            "E-mail для Let's Encrypt выглядит некорректно — укажите настоящий "
            "адрес или оставьте поле пустым (без e-mail лимиты ниже)",
        )
    return email


async def _start(params: dict, action: str, config: dict | None) -> dict:
    from core.web_tls import launch

    pid = await asyncio.to_thread(launch, params, action, config)
    return {"ok": True, "status": "pending", "action": action, "pid": pid}


# ==================================================================
# Состояние
# ==================================================================

@router.get("/api/settings/web/tls")
async def api_tls_get():
    try:
        from core.config import get_tls_config
        from core.web_tls import cert_info, changeable, busy, finalize_config, unit_tls_state

        # Самолечение provenance: после http→https-переключения исходная
        # вкладка не может дотянуться до /status (старая схема мертва),
        # и отложенный web.tls повисает. Финализируем и здесь — карточка
        # Настроек всегда показывает согласованное состояние.
        try:
            finalize_config()
        except Exception as e:
            print(f"[WEB] TLS config finalize failed: {e}", flush=True)
        ok, reason = changeable()
        unit = unit_tls_state()
        cfg = get_tls_config()
        # Метаданные сертификата — только если он реально используется юнитом.
        cert = cert_info(unit["cert_path"]) if unit.get("cert_path") else None
        return {
            "config": cfg,
            # Фактический транспорт из юнита: после отката раннера или
            # restore config может расходиться с реальностью — верим юниту.
            "unit": unit,
            "cert": cert,
            "changeable": ok,
            "reason": reason,
            "busy": busy(),
        }
    except Exception as e:
        return err(e)


@router.get("/api/settings/web/tls/status")
async def api_tls_status():
    """Состояние раннера + финализация provenance (см. finalize_config)."""
    try:
        from core.web_tls import finalize_config, read_state

        # До чтения состояния: если операция завершилась, применяем/выбрасываем
        # отложенный web.tls. Ошибка финализации не должна ломать поллинг.
        try:
            finalize_config()
        except Exception as e:
            print(f"[WEB] TLS config finalize failed: {e}", flush=True)
        return read_state()
    except Exception as e:
        return err(e)


# ==================================================================
# Включение режимов
# ==================================================================

class SelfSignedBody(BaseModel):
    # CN сертификата: IP или домен; пусто — публичный IP этого сервера.
    common_name: str | None = None


@router.post("/api/settings/web/tls/self-signed")
async def api_tls_self_signed(body: SelfSignedBody):
    try:
        _launch_guard()
        common_name = (body.common_name or "").strip() or None
        if common_name and not re.fullmatch(
            r"(\*\.)?([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)*[a-z0-9]([a-z0-9-]*[a-z0-9])?|"
            r"\d{1,3}(\.\d{1,3}){3}",
            common_name.lower(),
        ):
            raise HTTPException(
                400, "Имя для сертификата — домен или IP, например panel.example.com")
        return await _start(
            {"mode": "self-signed", "common_name": common_name},
            "enable",
            # common_name в provenance: иначе «Перевыпустить» сгенерирует
            # сертификат с IP вместо выбранного имени.
            {"mode": "self-signed", "common_name": common_name},
        )
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


class LetsEncryptBody(BaseModel):
    domain: str
    email: str | None = None


@router.post("/api/settings/web/tls/letsencrypt")
async def api_tls_letsencrypt(body: LetsEncryptBody):
    try:
        _launch_guard()
        domain = _domain_or_400(body.domain)
        email = _email_or_400(body.email)
        return await _start(
            {"mode": "letsencrypt", "domain": domain, "email": email},
            "enable",
            {"mode": "letsencrypt", "domain": domain},
        )
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


class CustomBody(BaseModel):
    cert_path: str
    key_path: str


@router.post("/api/settings/web/tls/custom")
async def api_tls_custom(body: CustomBody):
    """Свой сертификат по путям ФС: копия НЕ делается (сертификатом
    управляет другой сервис) — юнит ссылается на эти пути напрямую."""
    try:
        _launch_guard()
        cert_path = (body.cert_path or "").strip()
        key_path = (body.key_path or "").strip()
        if not cert_path or not key_path:
            raise HTTPException(400, "Укажите оба пути: сертификат (PEM) и закрытый ключ")
        if cert_path.startswith("-") or key_path.startswith("-"):
            raise HTTPException(400, "Путь не может начинаться с «-»")
        return await _start(
            {"mode": "custom", "cert_path": cert_path, "key_path": key_path},
            "enable",
            {"mode": "custom", "cert_path": cert_path, "key_path": key_path},
        )
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.post("/api/settings/web/tls/upload")
async def api_tls_upload(
    cert: UploadFile = File(...), key: UploadFile = File(...)
):
    """Загрузка своей пары cert+key с компьютера.

    НЕ запускает перезапуск панели: файлы классифицируются по содержимому
    (BEGIN CERTIFICATE / BEGIN * PRIVATE KEY — порядок выбора не важен),
    пара проверяется и устанавливается в keys/web/ (0600). Ответ — пути
    установленной пары: UI вписывает их в поля, HTTPS включает «Применить».
    """
    try:
        _launch_guard()
        from core.web_tls import CERT_FILE, KEY_FILE, classify_pem, validate_pair

        blobs: dict[str, bytes] = {}
        for upload, what in ((cert, "первого файла"), (key, "второго файла")):
            if not upload.filename:
                raise HTTPException(400, "Не выбран %s" % what)
            data = await upload.read()
            if not data:
                raise HTTPException(400, "%s пуст" % what.capitalize())
            if len(data) > 1024 * 1024:
                raise HTTPException(
                    400, "%s слишком большой (лимит 1 МБ)" % what.capitalize())
            kind = classify_pem(data)
            if kind is None:
                raise HTTPException(
                    400,
                    "%s (%s) не выглядит как PEM — ожидается текст, "
                    "начинающийся с -----BEGIN…" % (what.capitalize(), upload.filename),
                )
            if kind in blobs:
                raise HTTPException(
                    400,
                    "Оба файла — %s: нужны сертификат и закрытый ключ"
                    % ("сертификаты" if kind == "cert" else "ключи"),
                )
            blobs[kind] = data

        CERT_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Копия пары ложится в keys/web/cert.pem+key.pem; валидация — ДО
        # перезаписи текущей рабочей пары (не оставляем панель с битыми
        # файлами, если пользователь привёз кривую пару).
        staging = CERT_FILE.parent / "upload-staging.pem"
        staging_key = CERT_FILE.parent / "upload-staging-key.pem"
        try:
            staging.write_bytes(blobs["cert"])
            staging.chmod(0o600)
            staging_key.write_bytes(blobs["key"])
            staging_key.chmod(0o600)
            try:
                validate_pair(staging, staging_key)
            except ValueError as e:
                raise HTTPException(400, str(e))
            CERT_FILE.write_bytes(blobs["cert"])
            CERT_FILE.chmod(0o600)
            KEY_FILE.write_bytes(blobs["key"])
            KEY_FILE.chmod(0o600)
        finally:
            for path in (staging, staging_key):
                try:
                    path.unlink()
                except OSError:
                    pass
        return {
            "ok": True,
            "cert_path": str(CERT_FILE),
            "key_path": str(KEY_FILE),
            "message": "Пара проверена и сохранена — нажмите «Применить», "
                       "чтобы включить HTTPS",
        }
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


class ProxyBody(BaseModel):
    # IP и/или CIDR прокси-серверов, которым панель доверяет X-Forwarded-*.
    trusted_proxies: list[str]


@router.post("/api/settings/web/tls/proxy")
async def api_tls_proxy(body: ProxyBody):
    try:
        _launch_guard()
        from core.config import normalize_trusted_proxies

        try:
            proxies = normalize_trusted_proxies(body.trusted_proxies or [])
        except ValueError as e:
            raise HTTPException(400, str(e))
        if not proxies:
            raise HTTPException(
                400,
                "Укажите хотя бы один доверенный proxy — IP или подсеть, "
                "например 192.168.1.10 или 192.168.1.0/24",
            )
        return await _start(
            {"mode": "proxy", "trusted_proxies": proxies},
            "enable",
            {"mode": "proxy", "trusted_proxies": proxies},
        )
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


# ==================================================================
# Выключение и перевыпуск
# ==================================================================

@router.post("/api/settings/web/tls/off")
async def api_tls_off():
    try:
        _launch_guard()
        from core.web_tls import unit_tls_state

        unit = unit_tls_state()
        if not unit["ssl"] and not unit["proxy"]:
            raise HTTPException(400, "HTTPS уже выключен — панель работает по HTTP")
        return await _start({}, "disable", {"mode": "off"})
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


class RenewBody(BaseModel):
    # Кнопка «Перевыпустить» — осознанное действие: force=true у LE
    # (certbot --force-renewal) и регенерация self-signed.
    force: bool = False


@router.post("/api/settings/web/tls/renew")
async def api_tls_renew(body: RenewBody):
    try:
        _launch_guard()
        from core.config import get_tls_config
        from core.web_tls import unit_tls_state

        cfg = get_tls_config()
        unit = unit_tls_state()
        mode = cfg.get("mode")
        if mode not in ("letsencrypt", "self-signed", "custom"):
            raise HTTPException(
                400,
                "Перевыпуск имеет смысл для Let's Encrypt, self-signed или "
                "своего сертификата — сейчас режим: %s" % mode,
            )
        if mode != "off" and not unit["ssl"]:
            raise HTTPException(
                409,
                "Конфигурация говорит «%s», но панель сейчас работает без "
                "TLS — сначала включите режим заново" % mode,
            )
        params = {
            "mode": mode,
            "domain": cfg.get("domain"),
            "email": None,          # renew не перерегистрирует аккаунт LE
            "cert_path": cfg.get("cert_path"),
            "key_path": cfg.get("key_path"),
            "common_name": cfg.get("common_name"),
            "trusted_proxies": cfg.get("trusted_proxies"),
            "force": bool(body.force),
        }
        # Режим не меняется — provenance обновлять нечего.
        return await _start(params, "renew", None)
    except HTTPException:
        raise
    except Exception as e:
        return err(e)
