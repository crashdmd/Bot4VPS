"""HTTPS панели (Настройки → Безопасность, CLI, install.sh).

Режимы (config.json -> web.tls.mode, см. core/config.py::get_tls_config):

- ``off``         — HTTP, как сегодня;
- ``letsencrypt`` — certbot standalone HTTP-01 + фоновый перевыпуск;
- ``self-signed`` — генерация библиотекой cryptography;
- ``custom``      — свои cert+key: внешние пути (юнит ссылается прямо на
  них, без копирования — сертификатом управляет другой сервис/ACME-клиент)
  либо upload (копия в keys/web/, 0600);
- ``proxy``       — TLS терминирует реверс-прокси (может быть на другой
  машине LAN): панель доверяет X-Forwarded-* только от trusted_proxies.

Владение артефактами (урок design-ownership-first):

- **systemd-юнит владеет транспортом.** Что реально слушает uvicorn —
  флаги в ExecStart. app.py берёт https_only для куки и CLI показывает
  адрес из юнита (unit_tls_state), а НЕ из config: после отката раннера
  или restore старого архива config и юнит могут расходиться, и «правдой»
  обязан быть юнит.
- **config web.tls владеет происхождением**: режим/домен/пути/прокси —
  метаданные для UI, CLI и задачи перевыпуска.

Включение/выключение перезапускает сам сервис и убивает обработчик
HTTP-запроса — работу выполняет отсоединённый раннер
(``python -m core.web_tls``), переживший restart благодаря
``systemd-run --scope`` (паттерн core/web_port.py / core/update/updater.py).

Файл состояния ``data/web_tls.json`` — источник истины для UI/CLI:
``status: pending → restarting → done | failed``. На любом сбое раннер
откатывает юнит к сохранённому содержимому и возвращает сервис к прежней
схеме. Ошибки — только человекопонятные пары {title, hint}
(explain_failure): пользователь никогда не видит голое «Ошибка».

Модуль импортируется web/CLI-слоем (хелперы) и запускается как ``__main__``
раннер — stdlib в импортах верхнего уровня; cryptography — лениво.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
STATE_FILE = APP_DIR / "data" / "web_tls.json"
# Тот же юнит, что core/web_port.py — дублируем литерал: раннер обязан
# обходиться без импорта core.
UNIT_PATH = Path("/etc/systemd/system/bot4vps.service")
SERVICE_NAME = "bot4vps"

# Сертификаты, которыми управляет сам Bot4VPS (letsencrypt / self-signed /
# custom-upload). Custom по внешним путям живёт по своим путям и сюда
# НЕ копируется. 0600: ключ web-TLS — секрет того же класса, что SSH-ключи.
CERT_DIR = APP_DIR / "keys" / "web"
CERT_FILE = CERT_DIR / "cert.pem"
KEY_FILE = CERT_DIR / "key.pem"
# Live-сертификаты certbot (для копии в keys/web/ и автопродления).
LE_LIVE_ROOT = Path("/etc/letsencrypt/live")

HEALTH_INTERVAL = 3
HEALTH_TIMEOUT = 60
ROLLBACK_HEALTH_TIMEOUT = 30
LOG_LIMIT = 30

# Действия раннера (state.action)
ACTIONS = ("enable", "disable", "renew")


# ==================================================================
# Состояние (data/web_tls.json)
# ==================================================================

def _default_state() -> dict:
    return {
        "status": "idle",  # idle|pending|restarting|done|failed
        "action": None,    # enable|disable|renew
        # Параметры действия (validate на стороне раннера ещё раз):
        # mode, domain, email, cert_path, key_path, trusted_proxies, upload
        "params": {},
        # Отложенный web.tls (целиком) — применяет finalize_config() при успехе
        "config": None,
        "started_at": None,
        "finished_at": None,
        "pid": None,
        "error": None,     # {title, hint} — человекопонятный разбор
        "log": [],
    }


def read_state() -> dict:
    """Толерантное чтение: битый/отсутствующий файл -> состояние по умолчанию."""
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("web_tls.json: ожидается объект")
        state = _default_state()
        state.update(data)
        return state
    except (OSError, ValueError):
        return _default_state()


def write_state(**patches) -> dict:
    """Read-modify-write + атомарная запись (tmp -> fsync -> os.replace)."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state = read_state()
    state.update(patches)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, STATE_FILE)
    return state


def _log(message: str) -> None:
    """Строка в journald (через scope-юнит) + в state.log для UI."""
    print("[web_tls] %s" % message, flush=True)
    state = read_state()
    entries = list(state.get("log") or [])
    entries.append("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), message))
    write_state(log=entries[-LOG_LIMIT:])


def _fail(title: str, hint: str) -> dict:
    """Зафиксировать failure с человекопонятной парой (никаких голых «Ошибка»)."""
    state = write_state(
        status="failed",
        error={"title": title, "hint": hint},
        finished_at=datetime.now().isoformat(),
    )
    _log("ошибка: %s" % title)
    return state


# ==================================================================
# Человекопонятные ошибки (explain_failure)
# ==================================================================

def explain_certbot_failure(stdout: str, stderr: str) -> tuple[str, str]:
    """Сырой вывод certbot -> {title, hint}. Порядок правил важен."""
    text = "\n".join(part for part in (stdout, stderr) if part)

    if "Problem binding to port 80" in text or "Address already in use" in text \
            or "Could not bind TCP port 80" in text:
        # Третья формулировка — certbot ≥ 5.x: «Could not bind TCP port 80
        # because it is already in use by another process».
        return (
            "Порт 80 уже занят другим сервисом",
            "Проверка Let's Encrypt (HTTP-01) требует ненадолго свободный порт 80. "
            "Посмотрите, кто его занимает: ss -ltnp | grep :80 — и освободите порт "
            "или выпустите сертификат на машине, где он свободен. "
            "Существующий сервис не останавливается автоматически.",
        )
    if "DNS problem" in text or (
        "Failed authorization" in text and "no valid A record" in text
    ):
        return (
            "Домен не указывает на этот сервер",
            "Проверьте A-запись домена: она должна вести на публичный IP этой "
            "машины, а порт 80 — быть достижим из интернета (проброс на роутере, "
            "открытый firewall). Проверить можно так: dig +short <домен>.",
        )
    if "rate limit" in text.lower() or "too many certificates" in text.lower() \
            or "too many failed authorizations" in text.lower():
        return (
            "Let's Encrypt ограничил выпуск сертификатов",
            "Слишком много выпусков/попыток для этого домена за последнее время. "
            "Повторите через несколько часов — лимиты снимаются автоматически.",
        )
    if "Failed authorization" in text:
        return (
            "Let's Encrypt не смог подтвердить владение доменом",
            "Проверьте, что домен указывает на этот сервер и порт 80 достижим "
            "из интернета. Подробности — в выводе certbot ниже.",
        )
    # Неизвестный сбой: последние содержательные строки вывода + где смотреть
    tail = "\n".join(
        line for line in text.strip().splitlines() if line.strip()
    )[-500:]
    return (
        "certbot завершился с ошибкой",
        (tail or "вывод пуст — полный лог: journalctl -u bot4vps | grep web_tls"),
    )


# ==================================================================
# Юнит: фактическое состояние транспорта
# ==================================================================

def unit_tls_state(unit_path: Path = UNIT_PATH) -> dict:
    """Транспорт из ExecStart юнита — ЕДИНСТВЕННАЯ правда о схеме панели.

    Возвращает {scheme, ssl, proxy, cert_path, key_path, forwarded_allow}:
    - ssl:   в ExecStart есть --ssl-certfile/--ssl-keyfile;
    - proxy: есть --proxy-headers (+ список forwarded-allow-ips).

    scheme — ФАКТИЧЕСКИЙ транспорт сокета панели (http|https): в proxy-
    режиме панель слушает плоский HTTP (TLS терминирует реверс-прокси),
    scheme остаётся "http". «Панель доступна по HTTPS» = ssl ИЛИ proxy —
    это отдельные флаги (куки Secure, статус CLI). Health-проверка и
    прямой адрес всегда идут по scheme: https в http-сокет = обрыв.
    """
    out = {
        "scheme": "http", "ssl": False, "proxy": False,
        "cert_path": None, "key_path": None, "forwarded_allow": None,
    }
    try:
        text = unit_path.read_text(encoding="utf-8")
    except OSError:
        return out
    m = re.search(r'--ssl-certfile\s+("[^"]*"|\S+)', text)
    if m:
        out["ssl"] = True
        out["cert_path"] = m.group(1).strip('"')
        k = re.search(r'--ssl-keyfile\s+("[^"]*"|\S+)', text)
        out["key_path"] = k.group(1).strip('"') if k else None
    if "--proxy-headers" in text:
        out["proxy"] = True
        a = re.search(r"--forwarded-allow-ips\s+(\S+)", text)
        out["forwarded_allow"] = a.group(1) if a else None
    if out["ssl"]:
        out["scheme"] = "https"
    return out


def _managed_flags() -> str:
    """Флаги для сертификатов, которыми управляет Bot4VPS (keys/web/)."""
    return "--ssl-certfile %s --ssl-keyfile %s" % (CERT_FILE, KEY_FILE)


def _unit_path_arg(path: str) -> str:
    """Путь-аргумент ExecStart: с пробелами — в двойных кавычках.

    systemd разбирает аргументы командной строки юнита с shell-подобным
    квотированием; без кавычек путь с пробелом разваливался бы на
    несколько аргументов и юнит не стартовал. Двойная кавычка внутри
    пути не поддерживается — честный отказ лучше сломанного юнита.
    """
    if '"' in path:
        raise ValueError(
            "путь сертификата содержит двойную кавычку — переименуйте файл: %s" % path)
    if any(ch.isspace() for ch in path):
        return '"%s"' % path
    return path


def unit_tls_flags(tls_config: dict) -> str:
    """Флаги ExecStart по config web.tls (для write_web_unit CLI/install.sh).

    Пустая строка = HTTP как сегодня. Custom по внешним путям ссылается
    на них напрямую (без копирования).
    """
    mode = tls_config.get("mode") or "off"
    if mode in ("letsencrypt", "self-signed"):
        return _managed_flags()
    if mode == "custom":
        cert = tls_config.get("cert_path")
        key = tls_config.get("key_path")
        if cert and key:
            return "--ssl-certfile %s --ssl-keyfile %s" % (
                _unit_path_arg(cert), _unit_path_arg(key))
        return _managed_flags()
    if mode == "proxy":
        proxies = ",".join(tls_config.get("trusted_proxies") or [])
        if not proxies:
            proxies = "127.0.0.1"
        return "--proxy-headers --forwarded-allow-ips %s" % proxies
    return ""


def tls_asset_paths(tls_config: dict) -> list:
    """Пути cert/key, которые ОБЯЗАНЫ существовать для режима.

    Гард для write_web_unit (включение Web после HTTPS-режима): юнит со
    ssl-флагами на отсутствующие файлы не стартует вовсе — лучше отказ с
    понятным текстом, чем молчаливый даунгрейд на HTTP. Для off/proxy
    файлов нет — пустой список.
    """
    mode = tls_config.get("mode") or "off"
    if mode in ("letsencrypt", "self-signed"):
        return [CERT_FILE, KEY_FILE]
    if mode == "custom":
        cert = tls_config.get("cert_path")
        key = tls_config.get("key_path")
        if cert and key:
            return [Path(cert), Path(key)]
        return [CERT_FILE, KEY_FILE]
    return []


def _append_tls_flags(execstart: str, flags: str) -> str:
    """Добавить TLS-флаги к строке ExecStart (после --port N)."""
    return execstart.rstrip() + (" " + flags if flags else "")


# ==================================================================
# Хелперы для web/CLI-слоя
# ==================================================================

def changeable() -> tuple[bool, str | None]:
    """Управление HTTPS доступно: юнит есть, systemd-инструменты в PATH."""
    if not UNIT_PATH.exists():
        return False, "systemd-юнит %s не найден" % UNIT_PATH
    if shutil.which("systemd-run") is None or shutil.which("systemctl") is None:
        return False, "systemd недоступен (разработка без systemd)"
    return True, None


def busy() -> bool:
    return read_state().get("status") in ("pending", "restarting")


def launch(params: dict, action: str = "enable", config: dict | None = None) -> int:
    """Запустить раннер отдельным процессом, переживающим restart сервиса.

    systemd-run --scope даёт раннеру собственный cgroup: KillMode=mixed
    юнита при stop SIGKILL-ит все процессы сервисного cgroup через 3с —
    раннер, запущенный обычным Popen, был бы убит собственным restart'ом.
    Popen-фолбэк — только для dev-окружений без systemd-run.

    ``config`` — отложенный provenance (web.tls целиком): раннер stdlib-only
    и config.json не пишет; при успехе его применяет finalize_config()
    (поллинг статуса / CLI-ожидание / reconcile на старте), при неудаче —
    выбрасывает (юнит откачен, config обязан остаться прежним).
    """
    if action not in ACTIONS:
        raise ValueError("web_tls: неизвестное действие %r" % action)
    # Предыдущая операция могла завершиться (done/failed), но её provenance
    # ещё не применён — поллинга /status не было. Финализируем ДО затирания
    # state, иначе config навсегда разойдётся с юнитом (дважды случалось
    # в live-прогонах вне UI; в UI модалка поллит каждые 2 с — там не видно).
    try:
        finalize_config()
    except Exception as e:
        # Прошлый итог применить не вышло — не повод блокировать новый запуск
        print("[web_tls] прошлый provenance не применён: %s" % e, flush=True)
    write_state(
        status="pending",
        action=action,
        params=params,
        config=config,
        started_at=datetime.now().isoformat(),
        finished_at=None,
        pid=None,
        error=None,
        log=[],
    )
    cmd = [sys.executable, "-m", "core.web_tls"]
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    try:
        proc = subprocess.Popen(
            ["systemd-run", "--scope", "--collect",
             "--unit", "bot4vps-tls-%s" % ts] + cmd,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
            cwd=str(APP_DIR),
        )
        pid = proc.pid
    except (FileNotFoundError, OSError):
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
            cwd=str(APP_DIR),
        )
        pid = proc.pid
    write_state(pid=pid)
    return pid


def finalize_config() -> None:
    """Применить/выбросить отложенный config web.tls по итогам операции.

    Вызывается web-слоем (поллинг статуса, reconcile на старте) и CLI
    (ожидание раннера). При ``done`` provenance применяется целиком, при
    ``failed`` — отбрасывается: юнит откачен к прежней схеме, config не
    должен опережать реальность. Терминальность „done/failed“ плюс то, что
    каждый вызывающий сначала видит свежий state.json, защищают от двойного
    применения; повторный вызов — no-op (config уже очищен).
    """
    state = read_state()
    cfg = state.get("config")
    if not cfg:
        return
    status = state.get("status")
    if status in ("pending", "restarting"):
        # Операция ещё идёт — provenance ждёт итога.
        return
    if status == "done":
        from core.config import apply_tls_config

        apply_tls_config(cfg)
    # failed (или неизвестный терминал) — юнит откачен, config выбрасываем.
    write_state(config=None)


# ==================================================================
# Операции с сертификатами (cryptography — лениво)
# ==================================================================

def cert_info(cert_pem_path: str | Path) -> dict | None:
    """Метаданные сертификата для UI (содержимое ключа не отдаётся никогда)."""
    try:
        from cryptography import x509
        with open(cert_pem_path, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
    except Exception:
        return None

    def _cn(name) -> str:
        attrs = name.get_attributes_for_oid(x509.NameOID.COMMON_NAME)
        return str(attrs[0].value) if attrs else "—"

    try:
        from cryptography.hazmat.primitives.asymmetric import ec, rsa
        public = cert.public_key()
        if isinstance(public, rsa.RSAPublicKey):
            key_type = "RSA %d" % public.key_size
        elif isinstance(public, ec.EllipticCurvePublicKey):
            key_type = "EC %s" % public.curve.name
        else:
            key_type = type(public).__name__
    except Exception:
        key_type = ""
    expires = cert.not_valid_after_utc
    days_left = (expires - datetime.now(tz=expires.tzinfo)).days
    return {
        "subject": _cn(cert.subject),
        "issuer": _cn(cert.issuer),
        "key_type": key_type,
        "not_before": cert.not_valid_before_utc.isoformat(),
        "not_after": expires.isoformat(),
        "days_left": days_left,
    }


# PEM-маркеры: определить по содержимому, где сертификат, а где ключ
# (все три варианта приватного PEM — PKCS#8, RSA, EC — плюс сертификат).
CERT_PEM_MARKER = b"-----BEGIN CERTIFICATE-----"
KEY_PEM_MARKERS = (
    b"-----BEGIN PRIVATE KEY-----",
    b"-----BEGIN RSA PRIVATE KEY-----",
    b"-----BEGIN EC PRIVATE KEY-----",
)


def classify_pem(blob: bytes) -> str | None:
    """Определить по содержимому PEM: «cert», «key» или None (не PEM).

    Используется upload-каналом: пользователь выбирает два файла в любом
    порядке — сервер сам понимает, где сертификат, а где закрытый ключ.
    """
    if CERT_PEM_MARKER in blob:
        return "cert"
    if any(marker in blob for marker in KEY_PEM_MARKERS):
        return "key"
    return None


def validate_pair(cert_pem_path: str | Path, key_pem_path: str | Path) -> dict:
    """Проверить пару cert+key перед записью юнита.

    Возвращает метаданные сертификата; при любой проблеме — ValueError
    с ЧЕЛОВЕКОПОНЯТНЫМ текстом (title + подсказка, разделены « — »).
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec, ed25519, ed448, rsa

    for path, what in ((cert_pem_path, "сертификат"), (key_pem_path, "ключ")):
        try:
            blob = Path(path).read_bytes()
        except FileNotFoundError:
            raise ValueError(
                "Не найден файл (%s): %s — проверьте путь" % (what, path))
        except PermissionError:
            raise ValueError(
                "Нет прав на чтение %sа: %s — проверьте права файла" % (what, path))
        except OSError as e:
            raise ValueError(
                "Не удалось прочитать %s (%s): %s" % (what, path, e))
        if what == "сертификат":
            if CERT_PEM_MARKER not in blob:
                raise ValueError(_pem_error(what, path))
        elif not any(marker in blob for marker in KEY_PEM_MARKERS):
            raise ValueError(_pem_error(what, path))

    try:
        with open(cert_pem_path, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
    except Exception:
        raise ValueError(_pem_error("сертификат", cert_pem_path))
    try:
        with open(key_pem_path, "rb") as f:
            key = serialization.load_pem_private_key(f.read(), password=None)
    except Exception:
        raise ValueError(_pem_error("ключ", key_pem_path))

    def _fp(obj) -> bytes:
        if isinstance(obj, rsa.RSAPublicKey):
            return obj.public_numbers().n.to_bytes(
                (obj.public_numbers().n.bit_length() + 7) // 8, "big")
        if isinstance(obj, ec.EllipticCurvePublicKey):
            return obj.public_bytes(
                serialization.Encoding.X962,
                serialization.PublicFormat.UncompressedPoint)
        if isinstance(obj, (ed25519.Ed25519PublicKey, ed448.Ed448PublicKey)):
            return obj.public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        return obj.public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)

    if _fp(cert.public_key()) != _fp(key.public_key()):
        raise ValueError(
            "Сертификат и закрытый ключ не соответствуют друг другу — "
            "проверьте, что это пара от одного выпуска")

    expires = cert.not_valid_after_utc
    now = datetime.now(tz=expires.tzinfo)
    if expires <= now:
        raise ValueError(
            "Сертификат истёк %s — перевыпустите его или возьмите свежий"
            % expires.strftime("%d.%m.%Y"))

    return {
        "subject": str(cert.subject.get_attributes_for_oid(
            x509.NameOID.COMMON_NAME)[0].value)
        if cert.subject.get_attributes_for_oid(x509.NameOID.COMMON_NAME) else "",
        "not_after": expires.isoformat(),
        "days_left": (expires - now).days,
    }


def _pem_error(what: str, path) -> str:
    return (
        "Файл не выглядит как PEM-%s: %s — ожидается текст, начинающийся "
        "с «-----BEGIN ...»" % (what, path))


def generate_self_signed(common_name: str | None = None) -> None:
    """Сгенерировать self-signed пару в keys/web/ (cert.pem + key.pem, 0600).

    CN/SAN = переданное имя (домен или IP), иначе — IP машины. Срок ~2 года:
    фактический expiry читается из сертификата и показывается в UI.
    """
    import ipaddress as _ipaddress

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    name = common_name or _detect_ip()
    try:
        san = x509.IPAddress(_ipaddress.ip_address(name))
    except ValueError:
        san = x509.DNSName(name)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(tz=_utc())
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=730))
        .add_extension(x509.SubjectAlternativeName([san]), critical=False)
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write(CERT_FILE, cert.public_bytes(serialization.Encoding.PEM))
    _atomic_write(
        KEY_FILE,
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ),
    )


def _utc():
    from datetime import timezone
    return timezone.utc


def _detect_ip() -> str:
    try:
        result = subprocess.run(
            ["hostname", "-I"], capture_output=True, text=True, timeout=10)
        fields = (result.stdout or "").split()
        if fields:
            return fields[0]
    except Exception:
        pass
    return "localhost"


def _atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    """Атомарная запись файла с правами (tmp -> fsync -> replace -> chmod)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


# ==================================================================
# Let's Encrypt (certbot)
# ==================================================================

def find_certbot() -> str | None:
    """Путь до certbot: системный → venv/bin/certbot."""
    found = shutil.which("certbot")
    if found:
        return found
    venv_certbot = APP_DIR / "venv" / "bin" / "certbot"
    if venv_certbot.exists():
        return str(venv_certbot)
    return None


def install_certbot() -> str | None:
    """Установить certbot в venv (в requirements.txt НЕ включён — ставим
    по требованию). Возвращает путь или None при неудаче."""
    pip = APP_DIR / "venv" / "bin" / "pip"
    if not pip.exists():
        return None
    try:
        r = subprocess.run(
            [str(pip), "install", "--quiet", "certbot"],
            capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            return None
    except (OSError, subprocess.TimeoutExpired):
        return None
    return find_certbot()


def _certbot_cmd(email: str | None, domain: str, force: bool = False) -> list[str]:
    cmd = [
        "certonly", "--standalone",
        "-d", domain,
        "--non-interactive", "--agree-tos",
    ]
    # Существующий сертификат: без force — не трогаем до срока (--keep),
    # с force (кнопка «Перевыпустить») — перевыпускаем обязательно.
    cmd += ["--force-renewal"] if force else ["--keep-until-expiring"]
    if email:
        cmd += ["-m", email]
    else:
        cmd += ["--register-unsafely-without-email"]
    return cmd


def run_certbot(certbot: str, email: str | None, domain: str,
                force: bool = False) -> tuple[bool, str, str]:
    """Выпустить/перевыпустить сертификат. Возвращает (ok, stdout, stderr)."""
    try:
        r = subprocess.run(
            [certbot] + _certbot_cmd(email, domain, force),
            capture_output=True, text=True, timeout=300)
        return r.returncode == 0, r.stdout or "", r.stderr or ""
    except subprocess.TimeoutExpired:
        return False, "", "certbot не завершился за 300 с"
    except OSError as e:
        return False, "", str(e)


def copy_le_certificate(domain: str) -> None:
    """Копия live-сертификата Let's Encrypt в keys/web/ (0600, атомарно)."""
    live = LE_LIVE_ROOT / domain
    src_cert = live / "fullchain.pem"
    src_key = live / "privkey.pem"
    for src in (src_cert, src_key):
        if not src.is_file():
            raise ValueError(
                "Let's Encrypt не положил файл по пути %s — проверьте вывод "
                "certbot (journalctl -u bot4vps | grep web_tls)" % src)
    _atomic_write(CERT_FILE, src_cert.read_bytes())
    _atomic_write(KEY_FILE, src_key.read_bytes())


def le_expiry_days() -> int | None:
    """Сколько дней осталось сертификату в keys/web/ (для задачи перевыпуска)."""
    info = cert_info(CERT_FILE)
    return info["days_left"] if info else None


# ==================================================================
# Фоновый автоперевыпуск Let's Encrypt (Core JobQueue, раз в сутки)
# ==================================================================

# LE-сертификаты живут 90 дней; продлеваем, когда осталось ≤30.
RENEW_THRESHOLD_DAYS = 30


def _tls_event(level: str, title: str, message: str) -> None:
    """Событие журнала из TLS-задачи; сбой журналирования её не роняет.

    ``level`` — значение EventLevel ("info" | "critical"); CRITICAL
    автоматически уходит в очередь уведомлений (ТГ).
    """
    try:
        from core.event_service import create_event
        from core.event_types import EventLevel, EventType

        create_event(
            event_type=EventType.SSL,
            level=EventLevel(level),
            title=title,
            message=message,
        )
    except Exception as e:  # журнал не должен маскировать саму задачу
        print("[web_tls] event «%s» не записан: %s" % (title, e), flush=True)


def _renew_le_if_due(domain: str | None) -> None:
    """Синхронная часть автопродления (выполняется в to_thread).

    «Голый» ``certbot renew`` без ``--force-renewal``: перевыпускает только
    то, чему пора. Перезапуск Web — ТОЛЬКО если наш сертификат реально
    изменился; никаких рестартов «на всякий случай».
    """
    days = le_expiry_days()
    if days is None:
        _tls_event(
            "critical",
            "Сертификат панели не удаётся прочитать",
            "Режим Let's Encrypt включён, но файл %s не читается — проверьте "
            "файл или перевыпустите сертификат: Настройки → Безопасность → "
            "HTTPS → Перевыпустить." % CERT_FILE,
        )
        return
    if days > RENEW_THRESHOLD_DAYS:
        return

    certbot = find_certbot()
    if not certbot:
        _tls_event(
            "critical",
            "Не найден certbot для автопродления сертификата",
            "Сертификату панели осталось %d дн. Установите certbot "
            "(apt install certbot либо venv/bin/pip install certbot) и "
            "нажмите «Перевыпустить»: Настройки → Безопасность → HTTPS." % days,
        )
        return

    live_cert = (LE_LIVE_ROOT / (domain or "") / "fullchain.pem")
    before = live_cert.read_bytes() if live_cert.is_file() else None
    try:
        r = subprocess.run(
            [certbot, "renew", "--non-interactive"],
            capture_output=True, text=True, timeout=600,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        _tls_event(
            "critical",
            "Автопродление сертификата не удалось",
            "certbot не завершился: %s — полный лог: "
            "journalctl -u bot4vps | grep web_tls" % e,
        )
        return
    if r.returncode != 0:
        title, hint = explain_certbot_failure(r.stdout, r.stderr)
        _tls_event("critical", "Автопродление: " + title, hint)
        return

    after = live_cert.read_bytes() if live_cert.is_file() else None
    if after is None:
        _tls_event(
            "critical",
            "Сертификат истекает, но certbot им не управляет",
            "В /etc/letsencrypt/live нет сертификата домена %r (осталось %d "
            "дн.). Перевыпустите вручную: Настройки → Безопасность → HTTPS → "
            "Перевыпустить." % (domain, days),
        )
        return
    if before == after:
        # renew продлевает только то, чему пора; наш сертификат не менялся
        return

    live = LE_LIVE_ROOT / domain
    try:
        validate_pair(live / "fullchain.pem", live / "privkey.pem")
        copy_le_certificate(domain)
    except ValueError as e:
        _tls_event(
            "critical",
            "Обновлённый сертификат не прошёл проверку",
            "%s — панель продолжает работать со старым сертификатом; "
            "проверьте вручную: Настройки → Безопасность → HTTPS." % e,
        )
        return

    # Событие — ДО рестарта: он завершает и этот процесс.
    _tls_event(
        "info",
        "Сертификат Let's Encrypt продлён",
        "Панель перезапускается с новым сертификатом (домен %s)." % domain,
    )
    r = _systemctl("restart", SERVICE_NAME)
    if r.returncode != 0:
        # Перезапуск не удался, но наш процесс ещё жив (systemctl вернул
        # ошибку до stop) — говорим, что делать.
        _tls_event(
            "critical",
            "Сертификат продлён, но перезапуск не удался",
            "%s — перезапустите вручную: systemctl restart bot4vps"
            % (r.stderr or "").strip()[:300],
        )


async def tls_renew_job(_context=None) -> None:
    """Суточная задача Core JobQueue: продление LE-сертификата панели.

    Работает только при mode=letsencrypt в config И живом TLS в юните
    (config после неудачной операции/restore может опережать реальность).
    """
    from core.config import get_tls_config

    cfg = get_tls_config()
    if cfg.get("mode") != "letsencrypt":
        return
    if not unit_tls_state()["ssl"]:
        return
    try:
        await asyncio.to_thread(_renew_le_if_due, cfg.get("domain"))
    except Exception as e:
        _tls_event(
            "critical",
            "Не удалось продлить сертификат Let's Encrypt",
            "%s — полный лог: journalctl -u bot4vps | grep web_tls" % e,
        )


# ==================================================================
# Раннер (python -m core.web_tls)
# ==================================================================

def _atomic_write_unit(text: str) -> None:
    """Атомарная запись юнита: tmp в каталоге юнита -> fsync -> replace."""
    UNIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(UNIT_PATH.parent), prefix="bot4vps.service.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, UNIT_PATH)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _systemctl(*args: str, timeout: int = 90) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["systemctl", *args], capture_output=True, text=True, timeout=timeout
    )


def _health_ok(unit_state: dict, port: int, timeout: float) -> bool:
    """GET /api/upd/health по схеме юнита; успех = 2 OK подряд.

    https (в т.ч. self-signed) — с непроверяемым контекстом: цель —
    убедиться, что процесс жив и отвечает, валидацию доверия делает браузер.
    """
    scheme = unit_state["scheme"]
    url = "%s://127.0.0.1:%d/api/upd/health" % (scheme, port)
    ctx = None
    if scheme == "https":
        import ssl
        ctx = ssl._create_unverified_context()
    deadline = time.monotonic() + timeout
    streak = 0
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "bot4vps-web-tls"}
            )
            with urllib.request.urlopen(req, timeout=5, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok"):
                streak += 1
                if streak >= 2:
                    return True
            else:
                streak = 0
        except Exception:
            streak = 0
        time.sleep(HEALTH_INTERVAL)
    return False


def _current_port() -> int | None:
    try:
        text = UNIT_PATH.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"--port\s+(\d+)", text)
    return int(m.group(1)) if m else None


def _new_unit_text(unit_text: str, flags: str) -> str:
    """ExecStart текущего юнита + TLS-флаги (старые TLS-флаги убираются)."""
    m = re.search(r"^ExecStart=(.*)$", unit_text, re.MULTILINE)
    if not m:
        raise ValueError("в юните нет строки ExecStart")
    execstart = m.group(1)
    # Снимаем прежние TLS-флаги (переезд между режимами); пути могут
    # быть закавычены (пробелы) — см. _unit_path_arg
    execstart = re.sub(
        r'\s+--ssl-certfile\s+("[^"]*"|\S+)\s+--ssl-keyfile\s+("[^"]*"|\S+)',
        "", execstart)
    execstart = re.sub(
        r"\s+--proxy-headers\s+--forwarded-allow-ips\s+\S+", "", execstart)
    execstart = _append_tls_flags(execstart, flags)
    return unit_text[:m.start(1)] + execstart + unit_text[m.end(1):]


def _rollback(unit_backup: str, reason_title: str, reason_hint: str) -> None:
    """Вернуть исходный юнит, перезапустить сервис, зафиксировать failed."""
    _log("откат: %s" % reason_title)
    try:
        _atomic_write_unit(unit_backup)
        r = _systemctl("daemon-reload", timeout=60)
        if r.returncode != 0:
            _log("daemon-reload при откате не удался: %s" % (r.stderr or "").strip()[:300])
        r = _systemctl("restart", SERVICE_NAME)
        if r.returncode != 0:
            _log("restart при откате не удался: %s" % (r.stderr or "").strip()[:300])
            raise RuntimeError(r.stderr or "systemctl restart failed")
        # Прежняя схема должна ответить; если нет — юнит уже восстановлен,
        # сервис перезапущен (следующий старт поднимет его).
        old_state = unit_tls_state()
        port = _current_port() or 8080
        if not _health_ok(old_state, port, ROLLBACK_HEALTH_TIMEOUT):
            _log("сервис не ответил на прежней схеме (порт %d)" % port)
        _fail(
            "Сервис не поднялся с новой схемой HTTPS — конфигурация "
            "возвращена, панель работает как раньше",
            "Причина: %s %s" % (reason_title, reason_hint),
        )
    except Exception as e:
        _fail(
            "Сервис не поднялся с новой схемой HTTPS — конфигурация "
            "возвращена, панель работает как раньше",
            "Причина: %s %s; откат завершился ошибкой: %s"
            % (reason_title, reason_hint, e),
        )


def _prepare_assets(params: dict, log: bool = True) -> tuple[str, str]:
    """Подготовить сертификаты для режима — до записи юнита.

    Возвращает (ok, error) — error это {title, hint} при неудаче.
    """
    mode = params.get("mode")

    if mode == "self-signed":
        try:
            generate_self_signed(params.get("common_name"))
        except Exception as e:
            return "", _explain_exception(e)
        if log:
            _log("self-signed сертификат сгенерирован (%s)" % CERT_FILE)
        return _managed_flags(), ""

    if mode == "letsencrypt":
        domain = params.get("domain") or ""
        if not domain:
            return "", {"title": "Не указан домен",
                        "hint": "Для Let's Encrypt укажите домен, например "
                                "panel.example.com"}
        certbot = find_certbot() or install_certbot()
        if not certbot:
            return "", {
                "title": "Не удалось установить certbot",
                "hint": "Установите вручную: apt install certbot (или "
                        "venv/bin/pip install certbot), либо используйте "
                        "self-signed/свой сертификат",
            }
        if log:
            _log("выпускаю сертификат Let's Encrypt для %s (порт 80)…" % domain)
        ok, stdout, stderr = run_certbot(
            certbot, params.get("email"), domain, force=bool(params.get("force")))
        if not ok:
            title, hint = explain_certbot_failure(stdout, stderr)
            return "", {"title": title, "hint": hint}
        try:
            copy_le_certificate(domain)
        except ValueError as e:
            return "", _explain_exception(e)
        if log:
            _log("сертификат Let's Encrypt установлен в %s" % CERT_FILE)
        return _managed_flags(), ""

    if mode == "custom":
        if params.get("upload"):
            # Загруженная пара уже положена web-слоем в keys/web/
            # (upload-эндпоинт сам определил cert/key по содержимому и
            # провёл первичную валидацию) — здесь финальная проверка.
            try:
                validate_pair(CERT_FILE, KEY_FILE)
            except ValueError as e:
                return "", _explain_exception(e)
            if log:
                _log("загруженная пара установлена в %s" % CERT_FILE)
            return _managed_flags(), ""
        cert_path = params.get("cert_path")
        key_path = params.get("key_path")
        if not cert_path or not key_path:
            return "", {"title": "Не указаны пути к сертификату и ключу",
                        "hint": "Укажите оба пути: файлы сертификата (PEM) и "
                                "закрытого ключа"}
        try:
            validate_pair(cert_path, key_path)
        except ValueError as e:
            return "", _explain_exception(e)
        if log:
            _log("использую внешнюю пару %s + %s (без копирования)" % (
                cert_path, key_path))
        try:
            return "--ssl-certfile %s --ssl-keyfile %s" % (
                _unit_path_arg(cert_path), _unit_path_arg(key_path)), ""
        except ValueError as e:
            return "", _explain_exception(e)

    if mode == "proxy":
        proxies = params.get("trusted_proxies") or []
        if not proxies:
            return "", {"title": "Не указаны доверенные proxy",
                        "hint": "Укажите хотя бы один IP или подсеть прокси, "
                                "например 192.168.1.10 или 192.168.1.0/24"}
        return "--proxy-headers --forwarded-allow-ips %s" % ",".join(proxies), ""

    return "", ""


def _explain_exception(e: BaseException) -> dict:
    """ValueError с готовым текстом → как есть; прочее — обобщённо."""
    if isinstance(e, ValueError):
        return {"title": str(e).split(" — ")[0], "hint": str(e)}
    return {
        "title": "Неожиданная ошибка при работе с сертификатом",
        "hint": "%s — полный лог: journalctl -u bot4vps | grep web_tls" % e,
    }


def _apply() -> int:
    state = read_state()
    if state.get("status") != "pending":
        # Идемпотентность против двойного запуска
        print("[web_tls] статус %r — ничего не делаю" % state.get("status"), flush=True)
        return 0

    action = state.get("action")
    params = state.get("params") or {}
    port = _current_port()
    if port is None:
        _fail("Порт Web UI не найден в systemd-юните",
              "Web выключен (tg-only) — сначала включите Web: bot4vps → "
              "Безопасность → Включить")
        return 1

    try:
        unit_text = UNIT_PATH.read_text(encoding="utf-8")
    except OSError as e:
        _fail("Не удалось прочитать systemd-юнит",
              "%s — проверьте права на %s" % (e, UNIT_PATH))
        return 1

    write_state(status="restarting")

    # ── Шаг 1: сертификаты/флаги БЕЗ мутации юнита ─────────────────
    if action == "enable":
        flags, error = _prepare_assets(params)
        if error:
            _fail(error["title"], error["hint"])
            return 1
    elif action == "disable":
        flags = ""
        _log("выключаю HTTPS (возврат на HTTP)")
    elif action == "renew":
        # Перевыпуск: caller передаёт плоские параметры текущего режима
        # (mode/domain/email/cert_path/key_path/trusted_proxies).
        if not params.get("mode"):
            _fail("Не указан режим для перевыпуска",
                  "Внутренняя ошибка состояния — запустите операцию заново")
            return 1
        flags, error = _prepare_assets(params)
        if error:
            _fail(error["title"], error["hint"])
            return 1
    else:
        _fail("Неизвестное действие %r" % action,
              "Внутренняя ошибка состояния — запустите операцию заново")
        return 1

    # ── Шаг 2: юнит ────────────────────────────────────────────────
    try:
        new_text = _new_unit_text(unit_text, flags)
    except ValueError as e:
        _fail("Не удалось изменить строку запуска сервиса", str(e))
        return 1
    try:
        _atomic_write_unit(new_text)
    except OSError as e:
        _fail("Не удалось записать systemd-юнит", "%s — проверьте права" % e)
        return 1
    _log("юнит обновлён (%s)" % (flags or "HTTP, без TLS-флагов"))

    # ── Шаг 3: reload + restart ───────────────────────────────────
    r = _systemctl("daemon-reload", timeout=60)
    if r.returncode != 0:
        _rollback(unit_text, "daemon-reload не удался",
                  (r.stderr or "").strip()[:300])
        return 1
    r = _systemctl("restart", SERVICE_NAME)
    if r.returncode != 0:
        _rollback(unit_text, "systemctl restart не удался",
                  (r.stderr or "").strip()[:300])
        return 1

    # ── Шаг 4: health по новой схеме ──────────────────────────────
    new_state = unit_tls_state()
    _log("сервис перезапущен, ждём health (%s://127.0.0.1:%d)"
         % (new_state["scheme"], port))
    if _health_ok(new_state, port, HEALTH_TIMEOUT):
        write_state(status="done", finished_at=datetime.now().isoformat())
        _log("готово: панель работает по %s" % new_state["scheme"].upper())
        return 0

    _rollback(unit_text,
              "сервис не поднялся за %d с" % HEALTH_TIMEOUT,
              "подробности в журнале: journalctl -u bot4vps -n 50")
    return 1


if __name__ == "__main__":
    # Утилитарный вызов из install.sh (self-signed до старта сервиса):
    #   python -m core.web_tls --gen-self-signed [CN]
    if len(sys.argv) >= 2 and sys.argv[1] == "--gen-self-signed":
        try:
            generate_self_signed(sys.argv[2] if len(sys.argv) > 2 else None)
        except Exception as e:
            print("[web_tls] %s" % e, file=sys.stderr)
            sys.exit(1)
        sys.exit(0)
    sys.exit(_apply())
