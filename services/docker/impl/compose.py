# -*- coding: utf-8 -*-
"""Удалённые операции с Compose-проектами.

ДВА УРОВНЯ ХРАНЕНИЯ (не смешивать):
  * compose_store.py — локальная библиотека Bot4VPS:
        data/services/docker/compose/<stack>/  (проект = директория)
  * ЭТОТ модуль — управляемый сервер:
        /opt/bot4vps/<stack>/                  (рабочая копия Bot4VPS)
    плюс ЛЮБЫЕ внешние проекты в их собственных каталогах.

DEPLOYMENT IDENTITY (§14): проект на сервере опознаётся не по имени, а по
тройке (project, working_dir, config_files) — одноимённые проекты из разных
каталогов не сливаются.

Безопасность операций:
  * deploy (§9): temp-каталог → все файлы → `config -q` → и только при успехе
    атомарная замена рабочего каталога → `up -d`. При провале рабочий проект
    не тронут.
  * down (§11): без `-v` (тома живут) и без `|| true`; каталог удаляется
    только после успешного down.

Всё через StepRunner + exec_sudo — своё sudo/экранирование не пишем.
"""
from __future__ import annotations

import base64
import ipaddress
import json
import shlex
import uuid
from typing import Any, Dict, List, Optional, Tuple

from core.integrator import StepError, StepRunner
from core.ssh import create_ssh_client, exec_sudo

from . import compose_store

# Корень рабочих копий Bot4VPS на управляемом сервере.
REMOTE_ROOT = "/opt/bot4vps"

# Источник проекта для операций (§19): библиотека или сам сервер.
SOURCE_LIBRARY = "library"
SOURCE_SERVER = "server"

# Максимальный размер каталога проекта, который имеет смысл тянуть в память
# через tar+base64. Всё крупнее — это данные (тома, дампы, БД), а не конфиг:
# импортировать их в библиотеку бессмысленно и очень долго.
PROJECT_READ_LIMIT = 5 * 1024 * 1024


# --------------------------------------------------
# Пути рабочей копии Bot4VPS
# --------------------------------------------------

def remote_dir(stack: str) -> str:
    """Каталог рабочей копии Bot4VPS (имя валидируется — traversal исключён)."""
    return f"{REMOTE_ROOT}/{compose_store.validate_stack_name(stack)}"


def is_managed_dir(working_dir: str) -> bool:
    """Каталог принадлежит Bot4VPS (лежит внутри REMOTE_ROOT)?"""
    wd = (working_dir or "").rstrip("/")
    if not wd.startswith(REMOTE_ROOT + "/"):
        return False
    rest = wd[len(REMOTE_ROOT) + 1:]
    return bool(rest) and "/" not in rest


# --------------------------------------------------
# Выбор бинаря compose (v2-плагин или legacy v1)
# --------------------------------------------------

_DETECT_CMD = (
    "if docker compose version >/dev/null 2>&1; then echo v2; "
    "elif command -v docker-compose >/dev/null 2>&1; then echo v1; "
    "else echo none; fi"
)


def detect_compose_cmd(ssh, server) -> str:
    """Префикс команды: «docker compose» (v2) или «docker-compose» (v1)."""
    _, out, _ = exec_sudo(ssh, server, _DETECT_CMD)
    flavor = (out or "").strip().splitlines()[-1].strip() if out.strip() else "none"
    if flavor == "v2":
        return "docker compose"
    if flavor == "v1":
        return "docker-compose"
    raise StepError(
        "detect_compose", -1, title="Docker Compose не найден",
        detail=(
            "на сервере нет ни «docker compose» (плагин v2), ни «docker-compose» (v1). "
            "Переустановите Docker — официальный скрипт get.docker.com ставит "
            "docker-compose-plugin."
        ),
    )


# --------------------------------------------------
# Deployment: идентичность и аргументы команд
# --------------------------------------------------

class Deployment:
    """Развёртывание Compose на сервере — то, с чем работают операции.

    Опознаётся тройкой (project, working_dir, config_files) — §14. Все команды
    выполняются в РЕАЛЬНОМ каталоге проекта (§16), поэтому относительные пути
    (./config, ./.env) разрешаются как задумано автором проекта.
    """

    def __init__(
        self, project: str, working_dir: str,
        config_files: Optional[List[str]] = None,
    ):
        self.project = project
        self.working_dir = (working_dir or "").rstrip("/")
        self.config_files = [c for c in (config_files or []) if c]

    @property
    def managed(self) -> bool:
        return is_managed_dir(self.working_dir)

    @property
    def key(self) -> str:
        """Стабильный идентификатор развёртывания (для UI и сопоставления)."""
        cfg = ",".join(sorted(self.config_files))
        return f"{self.project}|{self.working_dir}|{cfg}"

    @property
    def ignore_key(self) -> str:
        """Ключ игнор-листа: «project|working_dir» (docs/compose-model.md §2).

        В отличие от key НЕ включает config_files: добавление override-файла
        не должно сбрасывать игнор проекта.
        """
        return f"{self.project}|{self.working_dir}"

    def args(self) -> str:
        """Аргументы compose: project name + рабочий каталог + файлы конфигурации.

        --project-directory фиксирует базу относительных путей; -f перечисляет
        реальные config_files (их может быть несколько — override-файлы).
        """
        parts = [f"-p {shlex.quote(self.project)}"]
        if self.working_dir:
            parts.append(f"--project-directory {shlex.quote(self.working_dir)}")
        for cfg in self.config_files:
            parts.append(f"-f {shlex.quote(cfg)}")
        return " ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project": self.project,
            "working_dir": self.working_dir,
            "config_files": list(self.config_files),
            "managed": self.managed,
            "key": self.key,
            "ignore_key": self.ignore_key,
        }

    def __repr__(self) -> str:  # для логов/диагностики
        return f"<Deployment {self.key}>"


def managed_deployment(stack: str) -> Deployment:
    """Развёртывание для проекта из библиотеки (рабочая копия Bot4VPS)."""
    stack_name = compose_store.validate_stack_name(stack)
    directory = remote_dir(stack_name)
    return Deployment(stack_name, directory, [])


# --------------------------------------------------
# Обнаружение Compose-проектов на сервере (§12, §13)
# --------------------------------------------------

# Лейблы Compose несут всё нужное для идентичности развёртывания. Берём их из
# контейнеров (включая остановленные) — работает и для v1, и для v2, и для
# проектов, поднятых мимо Bot4VPS.
_PS_LABELS_CMD = (
    "docker ps -a --no-trunc "
    "--filter label=com.docker.compose.project "
    "--format '{{.Label \"com.docker.compose.project\"}}\\t"
    "{{.Label \"com.docker.compose.project.working_dir\"}}\\t"
    "{{.Label \"com.docker.compose.project.config_files\"}}\\t{{.State}}' "
    "2>/dev/null || true"
)

# Для удаления нужен ID контейнера: если проект уже остановлен, Compose-файл
# может быть повреждён, поэтому его состояние и очистку контейнеров определяем
# только по Docker labels, не через `docker compose config/down`.
_PS_CONTAINER_IDENTITIES_CMD = (
    "docker ps -a --no-trunc "
    "--filter label=com.docker.compose.project "
    "--format '{{.ID}}\\t{{.Label \"com.docker.compose.project\"}}\\t"
    "{{.Label \"com.docker.compose.project.working_dir\"}}\\t{{.State}}'"
)

# Каталоги рабочих копий Bot4VPS: проект может быть развёрнут, но остановлен —
# тогда контейнеров нет и лейблы не найдутся.
_FIND_MANAGED_CMD = (
    "for d in " + REMOTE_ROOT + "/*/; do "
    "for f in compose.yaml compose.yml docker-compose.yaml docker-compose.yml; do "
    "[ -f \"$d$f\" ] && printf '%s\\t%s\\n' \"${d%/}\" \"$d$f\" && break; "
    "done; done 2>/dev/null || true"
)

# Поиск external Compose-проектов (§2): после `docker compose down` контейнеры
# удаляются → metadata нет → нужен FS-поиск. Не сканируем весь /, только
# известные локации. Исключаем managed /opt/bot4vps — он уже покрыт выше.
_FIND_EXTERNAL_CMD = (
    "find /opt /home /srv /root -maxdepth 3 -type f "
    "\\( -name compose.yaml -o -name compose.yml "
    "-o -name docker-compose.yaml -o -name docker-compose.yml \\) "
    "-not -path '" + REMOTE_ROOT + "/*' "
    "-not -path '/proc/*' -not -path '/sys/*' -not -path '/dev/*' "
    "-not -path '/run/*' -not -path '/var/lib/docker/*' "
    "2>/dev/null || true"
)


def parse_ps_labels(text: str) -> Dict[str, Dict[str, Any]]:
    """Разобрать «project\\tworking_dir\\tconfig_files\\tstate» → развёртывания.

    Чистая функция (тестируется без SSH). Ключ — Deployment.key, поэтому
    одноимённые проекты из разных каталогов остаются раздельными (§14).
    config_files в лейбле перечислены через запятую.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for line in (text or "").splitlines():
        line = line.rstrip()
        if not line or "\t" not in line:
            continue
        parts = line.split("\t")
        while len(parts) < 4:
            parts.append("")
        project, working_dir, config_files, state = (p.strip() for p in parts[:4])
        if not project:
            continue
        cfgs = [c.strip() for c in config_files.split(",") if c.strip()]
        dep = Deployment(project, working_dir, cfgs)
        entry = out.setdefault(dep.key, {
            "deployment": dep,
            "containers_total": 0,
            "containers_running": 0,
        })
        entry["containers_total"] += 1
        if state.lower() == "running":
            entry["containers_running"] += 1
    return out


def parse_managed_dirs(text: str) -> List[Tuple[str, str]]:
    """Разобрать «dir\\tcompose_file» из _FIND_MANAGED_CMD."""
    out: List[Tuple[str, str]] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or "\t" not in line:
            continue
        directory, cfg = line.split("\t", 1)
        directory, cfg = directory.strip().rstrip("/"), cfg.strip()
        if directory and cfg:
            out.append((directory, cfg))
    return out


def parse_external_compose(text: str) -> List[Tuple[str, str]]:
    """Разобрать список найденных compose-файлов (§2): абсолютный путь к файлу →
    (working_dir, config_file). Чистая функция (тестируется без SSH).
    """
    out: List[Tuple[str, str]] = []
    for line in (text or "").splitlines():
        cfg = line.strip()
        if not cfg or not cfg.startswith("/"):
            continue
        wd = cfg.rsplit("/", 1)[0]
        if wd and wd != cfg:
            out.append((wd, cfg))
    return out


def _read_remote_project_files(
    ssh, server, deployment: "Deployment", limit_bytes: int = PROJECT_READ_LIMIT,
) -> Dict[str, bytes]:
    """Прочитать с сервера КОНФИГ-НАБОР проекта как {rel_path: bytes}.

    Нужно и для импорта (§17), и для сравнения версий (§23). Передаём одним
    tar+base64, чтобы не делать по SSH-вызову на файл и не терять бинарные
    данные. Пустой dict, если каталог недоступен.

    Один и тот же конфиг-предикат (compose_store §3) действует на всех
    уровнях: tar-исключения на сервере отсекают основную массу данных ДО
    передачи, прочитанный набор фильтруется повторно — по размеру и
    бинарности, которые tar не проверял.

    Размер проверяем ДО tar: иначе каталог на 60 ГБ будет минуты гнаться через
    base64 (это ещё +33 % к объёму), чтобы затем упасть на limit_bytes.
    """
    wd = deployment.working_dir
    if not wd:
        return {}
    size = _du_bytes(ssh, server, wd, config_only=True)
    if size > limit_bytes:
        return {}
    _, out, _ = exec_sudo(
        ssh, server,
        f"cd {shlex.quote(wd)} 2>/dev/null && "
        f"tar -cf - --exclude-vcs {_config_excludes_args()} . 2>/dev/null "
        f"| base64 -w0 || true",
    )
    raw = (out or "").strip()
    if not raw:
        return {}
    try:
        blob = base64.b64decode(raw, validate=False)
    except Exception:
        return {}
    if len(blob) > limit_bytes:
        return {}

    import io
    import tarfile
    files: Dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:") as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                name = member.name
                if name.startswith("./"):
                    name = name[2:]
                if not name:
                    continue
                try:
                    # Пути с сервера тоже проверяем — tar мог прийти враждебным.
                    rel = compose_store.safe_relative_path(name).as_posix()
                except StepError:
                    continue
                fh = tf.extractfile(member)
                if fh is None:
                    continue
                files[rel] = fh.read()
    except (tarfile.TarError, EOFError):
        return {}
    # Финальный фильтр тем же предикатом, что и локальную библиотеку:
    # tar-исключения не знают размера/бинарности конкретных файлов.
    return {rel: files[rel] for rel in compose_store.filter_config_files(files)}


def _config_excludes_args() -> str:
    """Аргументы --exclude для tar/du по конфиг-набору (compose_store §3).

    Дублирует CONFIG_EXCLUDE_DIRS на стороне сервера: шаблон '*/<dir>'
    матчится на любой глубине, поэтому основная масса runtime-данных
    (data/, logs/, …) отсекается ещё ДО передачи. Это оптимизация, не
    защита — прочитанный набор фильтруется предикатом повторно.
    """
    parts = [
        f"--exclude='*/{d}'"
        for d in sorted(compose_store.CONFIG_EXCLUDE_DIRS)
    ]
    # '?*' — не меньше одного символа перед '_data': каталог, названный ровно
    # «_data», локальным предикатом не исключается, держим паритет.
    parts.append("--exclude='*/?*_data'")
    return " ".join(parts)


def _du_bytes(ssh, server, wd: str, config_only: bool = False) -> int:
    """Размер каталога через du на уже открытом SSH. 0, если не определить.

    config_only=True — размер без runtime-каталогов (для лимита чтения
    конфиг-набора): живой проект с гигабайтами в data/ обязан проходить
    5-МиБ лимит, если сами конфиги маленькие.
    """
    if not wd:
        return 0
    excludes = f" {_config_excludes_args()}" if config_only else ""
    try:
        _, out, _ = exec_sudo(
            ssh, server,
            f"du -sb{excludes} {shlex.quote(wd)} 2>/dev/null | cut -f1 || echo 0",
        )
        return int((out or "0").strip() or "0")
    except Exception:
        return 0


def list_server_stacks(server: dict) -> List[Dict[str, Any]]:
    """Фактические Compose-проекты на сервере (§12 + §2).

    Три источника:
    1. Лейблы контейнеров (Docker metadata) — любые проекты, в т.ч. внешние.
    2. Каталоги рабочих копий Bot4VPS — развёрнутые, но остановленные managed.
    3. Поиск compose-файлов в /opt, /home, /srv, /root — внешние после down.

    Возвращает список записей вида:
        {name, working_dir, config_files, managed, key, ignore_key, deployed,
         containers_total, containers_running, fingerprint}
    fingerprint считается только при одноимённом проекте в библиотеке
    (для сравнения с ней, docs/compose-model.md §3); для остальных чтение
    tar+base64 по SSH — пустая трата времени.
    """
    ssh = create_ssh_client(server)
    try:
        _, ps_out, _ = exec_sudo(ssh, server, _PS_LABELS_CMD)
        found = parse_ps_labels(ps_out)

        _, dirs_out, _ = exec_sudo(ssh, server, _FIND_MANAGED_CMD)
        for directory, cfg in parse_managed_dirs(dirs_out):
            name = directory.rsplit("/", 1)[-1]
            # Уже найдено по лейблам (контейнеры есть) — не дублируем.
            if any(
                e["deployment"].working_dir == directory
                and e["deployment"].project == name
                for e in found.values()
            ):
                continue
            dep = Deployment(name, directory, [cfg])
            found.setdefault(dep.key, {
                "deployment": dep,
                "containers_total": 0,
                "containers_running": 0,
            })

        # §2: external Compose-проекты, которые остановлены (контейнеры удалены).
        _, ext_out, _ = exec_sudo(ssh, server, _FIND_EXTERNAL_CMD)
        for directory, cfg in parse_external_compose(ext_out):
            # project name из последнего компонента каталога (как делает Docker).
            name = directory.rsplit("/", 1)[-1] or "unknown"
            dep = Deployment(name, directory, [cfg])
            # Не дублируем, если уже найден через metadata или managed-каталоги.
            if dep.key in found:
                continue
            found.setdefault(dep.key, {
                "deployment": dep,
                "containers_total": 0,
                "containers_running": 0,
            })

        out: List[Dict[str, Any]] = []
        for entry in found.values():
            dep: Deployment = entry["deployment"]
            record = dep.to_dict()
            record["name"] = dep.project
            record["deployed"] = entry["containers_total"] > 0
            record["containers_total"] = entry["containers_total"]
            record["containers_running"] = entry["containers_running"]
            record["fingerprint"] = None
            # Fingerprint нужен, чтобы сравнить серверную версию с библиотечной
            # и решить, показывать ли «Импортировать». Сравнение имеет смысл
            # только когда в библиотеке есть одноимённый проект; для остальных
            # чтение tar+base64 по SSH — пустая трата времени.
            if compose_store.stack_exists_safe(dep.project):
                try:
                    files = _read_remote_project_files(ssh, server, dep)
                    if files:
                        record["fingerprint"] = compose_store.fingerprint_files(files)
                except Exception:
                    pass
            out.append(record)
        out.sort(key=lambda r: (r["name"], r["working_dir"]))
        return out
    finally:
        ssh.close()


def resolve_deployment(server: dict, stack: str, key: Optional[str] = None) -> Deployment:
    """Найти развёртывание на сервере по имени (и по key, если задан).

    key нужен, когда на сервере несколько проектов с одним именем из разных
    каталогов (§14) — UI передаёт его, чтобы операция ушла в нужный каталог.
    """
    stacks = list_server_stacks(server)
    if key:
        for rec in stacks:
            if rec.get("key") == key:
                return Deployment(rec["name"], rec["working_dir"], rec["config_files"])
        raise StepError(
            "resolve_deployment", -1, title="Проект не найден на сервере",
            detail=f"развёртывание {key!r} отсутствует — обновите список",
        )
    matches = [r for r in stacks if r.get("name") == stack]
    if not matches:
        raise StepError(
            "resolve_deployment", -1, title="Проект не найден на сервере",
            detail=f"на сервере нет Compose-проекта «{stack}»",
        )
    if len(matches) > 1:
        dirs = ", ".join(m["working_dir"] for m in matches)
        raise StepError(
            "resolve_deployment", -1, title="Неоднозначный проект",
            detail=(
                f"на сервере несколько проектов «{stack}» ({dirs}). "
                f"Выберите нужный в списке — Bot4VPS не угадывает."
            ),
        )
    rec = matches[0]
    return Deployment(rec["name"], rec["working_dir"], rec["config_files"])


# --------------------------------------------------
# Защита от конфликта подсетей (§22)
# --------------------------------------------------

def _parse_server_networks(ip_addr_output: str) -> List[Any]:
    """Сети из `ip -4 addr show` (inet 192.168.35.10/24 → 192.168.35.0/24)."""
    out: List[Any] = []
    for line in (ip_addr_output or "").splitlines():
        line = line.strip()
        if not line.startswith("inet "):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            net = ipaddress.ip_network(parts[1], strict=False)
            if net not in out:
                out.append(net)
        except ValueError:
            pass
    return out


def _parse_routed_networks(ip_route_output: str) -> List[Any]:
    """Сети из `ip route show` (192.168.35.0/24 dev eth0 → сеть)."""
    out: List[Any] = []
    for line in (ip_route_output or "").splitlines():
        line = line.strip()
        if not line or line.startswith("default"):
            continue
        parts = line.split()
        if not parts:
            continue
        try:
            net = ipaddress.ip_network(parts[0], strict=False)
            if net not in out:
                out.append(net)
        except ValueError:
            pass
    return out


def _check_subnets(ssh, server, yaml_text: str, emit) -> None:
    """Отказать, если подсети из compose пересекаются с сетью сервера.

    Docker, создав bridge с подсетью сервера, перетянет на него маршрут и
    оборвёт SSH (реальный инцидент 2026-08-11 с 192.168.35.0/24). Поэтому
    проверка идёт ДО любых изменений — и для library, и для server (§21).
    """
    declared = compose_store.parse_declared_subnets(yaml_text)
    if not declared:
        return
    emit("• Проверка подсетей на конфликт с адресацией сервера")
    _, addr_out, _ = exec_sudo(ssh, server, "ip -4 addr show 2>/dev/null || true")
    _, route_out, _ = exec_sudo(ssh, server, "ip route show 2>/dev/null || true")
    server_nets = _parse_server_networks(addr_out)
    routed_nets = _parse_routed_networks(route_out)

    conflicts: List[Tuple[str, str]] = []
    for subnet_str in declared:
        try:
            declared_net = ipaddress.ip_network(subnet_str, strict=False)
        except ValueError:
            continue  # битый CIDR поймает `compose config -q`
        for net in server_nets:
            if declared_net.overlaps(net):
                conflicts.append((subnet_str, f"адресом сервера {net}"))
                break
        else:
            for net in routed_nets:
                if declared_net.overlaps(net):
                    conflicts.append((subnet_str, f"маршрутом {net}"))
                    break

    if conflicts:
        lines = [f"• {s} пересекается с {what}" for s, what in conflicts]
        raise StepError(
            "subnet_conflict", -1,
            title="Конфликт подсетей compose с адресацией сервера",
            detail=(
                "Объявленные в compose подсети пересекаются с сетью этого сервера:\n"
                + "\n".join(lines)
                + "\n\nDocker перетянет маршрут на свой bridge → потеря SSH-связи. "
                "Измените подсети на свободные (например, 10.77.0.0/24) или уберите "
                "секцию networks (порты публикуются и без неё)."
            ),
        )


def detect_subnet_conflicts(server: dict, yaml_text: str) -> None:
    """Публичная обёртка проверки подсетей (открывает свой SSH)."""
    if not compose_store.parse_declared_subnets(yaml_text):
        return
    ssh = create_ssh_client(server)
    try:
        _check_subnets(ssh, server, yaml_text, lambda _line: None)
    finally:
        ssh.close()


# --------------------------------------------------
# Загрузка файлов проекта на сервер
# --------------------------------------------------

def _upload_files(runner: StepRunner, target_dir: str, files: Dict[str, bytes]) -> None:
    """Залить все файлы проекта в указанный каталог на сервере.

    Для non-root SSH: SFTP пишет во временный доступный каталог, затем sudo cp
    переносит в target. Защита от traversal уже выполнена
    compose_store.safe_relative_path, поэтому здесь проверять не нужно.
    """
    # Доступный временный каталог (для non-root SSH). Уникальный суффикс гарантирует,
    # что параллельные deploy на одном сервере не пересекаются.
    import uuid
    sftp_temp = f"/tmp/bot4vps_{uuid.uuid4().hex[:12]}"
    sftp = runner.ssh.open_sftp()
    try:
        created: set = set()

        def ensure_dir(path: str) -> None:
            if not path or path in created:
                return
            parent = path.rsplit("/", 1)[0]
            if parent and parent != path:
                ensure_dir(parent)
            try:
                sftp.stat(path)
            except IOError:
                try:
                    sftp.mkdir(path)
                except IOError:
                    pass
            created.add(path)

        ensure_dir(sftp_temp)
        for rel in sorted(files.keys()):
            dest = f"{sftp_temp}/{rel}"
            parent = dest.rsplit("/", 1)[0]
            ensure_dir(parent)
            with sftp.file(dest, "wb") as f:
                f.write(files[rel])
    finally:
        sftp.close()
    runner.emit(f"   загружено файлов во временный каталог: {len(files)}")

    # Теперь с правами sudo перемещаем содержимое в staging-каталог.
    # target_dir создан install -d ранее с root-правами — обычный SSH-пользователь
    # туда писать не может, поэтому делаем через sudo.
    runner.run(
        "move_to_staging",
        f"install -d -m 755 {shlex.quote(target_dir)} && "
        f"cp -rT {shlex.quote(sftp_temp)} {shlex.quote(target_dir)} && "
        f"rm -rf {shlex.quote(sftp_temp)}",
        title="Перенос файлов в staging-каталог",
    )


# --------------------------------------------------
# Атомарный deploy проекта из библиотеки (§9, §10)
# --------------------------------------------------

def _restore_runtime_dirs_cmd(target: str, backup: str) -> str:
    """Команда переноса runtime-каталогов из backup в новую рабочую копию.

    Список тот же, что и в конфиг-предикате (CONFIG_EXCLUDE_DIRS + *_data):
    что не входит в конфиг-набор, то живёт на сервере и переживает деплой.
    Каталоги ищем на любой глубине — как data/ в корне, так и config/data/.
    tar-пайп вместо find -exec: во временной копии runtime-каталогов быть не
    может (библиотека несёт только конфиг-набор), так что перезапись
    невозможна, а копирование сохраняет структуру путей как есть.
    """
    names = " -o ".join(
        [f"-name {shlex.quote(d)}" for d in sorted(compose_store.CONFIG_EXCLUDE_DIRS)]
        + [f"-name {shlex.quote('?*_data')}"]
    )
    return (
        f"if [ -d {shlex.quote(backup)} ]; then "
        f"(cd {shlex.quote(backup)} && "
        f"find . -type d \\( {names} \\) -print 2>/dev/null "
        f"| tar -cf - -T - 2>/dev/null "
        f"| (cd {shlex.quote(target)} && tar -xf -)) || true; fi"
    )


def _deploy_atomic(runner: StepRunner, cmd: str, stack: str, files: Dict[str, bytes],
                   compose_file: str) -> Deployment:
    """Развернуть проект в /opt/bot4vps/<stack> без риска потерять рабочую копию.

    Порядок строго такой (§9):
      1. temp-каталог рядом с целевым (тот же fs → атомарный mv);
      2. загрузить ВСЕ файлы проекта;
      3. `compose config -q` в temp — относительные пути (./config, ./.env)
         разрешаются уже в правильном контексте;
      4. только при успехе — атомарно заменить рабочий каталог;
      5. при любой ошибке — снести temp, рабочий каталог не тронуть (§10).
    """
    stack_name = compose_store.validate_stack_name(stack)
    target = remote_dir(stack_name)
    tmp = f"{target}.new"
    backup = f"{target}.old"

    # Чистим возможные остатки прошлой неудачной попытки. Создавать tmp не нужно —
    # _upload_files сделает temp в /tmp через SFTP.
    runner.run(
        "prepare_tmp",
        f"rm -rf {shlex.quote(tmp)} {shlex.quote(backup)}",
        title="Подготовка временного каталога",
    )
    try:
        runner.emit(f"• Загрузка файлов проекта ({len(files)}) во временный каталог")
        _upload_files(runner, tmp, files)

        # Валидация в temp: рабочая копия ещё не тронута.
        tmp_dep = Deployment(stack_name, tmp, [f"{tmp}/{compose_file}"])
        runner.run(
            "compose_config", f"{cmd} {tmp_dep.args()} config -q",
            title="Проверка конфигурации (compose config)",
        )

        # Атомарная замена: рабочий каталог уезжает в backup, temp встаёт на его
        # место. Между двумя mv нет валидации — только переименования.
        runner.run(
            "activate",
            f"if [ -d {shlex.quote(target)} ]; then "
            f"mv {shlex.quote(target)} {shlex.quote(backup)}; fi && "
            f"mv {shlex.quote(tmp)} {shlex.quote(target)}",
            title="Активация новой версии проекта",
        )
        # Библиотека несёт только конфиг-набор (§3), а рабочая копия содержит
        # ещё и runtime-данные (data/, logs/, …). Переносим их из backup в
        # новый каталог ДО удаления backup: повторный деплой не стирает данные
        # контейнеров. Провал переноса не откатывает деплой (конфиг уже
        # валиден и активирован), но и не сносит данные.
        runner.run(
            "restore_runtime_dirs",
            _restore_runtime_dirs_cmd(target, backup),
            title="Перенос runtime-данных в новую версию",
        )
        runner.run(
            "cleanup_backup", f"rm -rf {shlex.quote(backup)}",
            title="Удаление резервной копии",
        )
    except Exception:
        # Возвращаем прежнюю рабочую копию, если успели её отодвинуть.
        exec_sudo(
            runner.ssh, runner.server,
            f"if [ -d {shlex.quote(backup)} ] && [ ! -d {shlex.quote(target)} ]; then "
            f"mv {shlex.quote(backup)} {shlex.quote(target)}; fi; "
            f"rm -rf {shlex.quote(tmp)}",
        )
        raise
    return managed_deployment(stack_name)


def _library_files(stack: str) -> Tuple[Dict[str, bytes], str, str]:
    """Файлы проекта из библиотеки + имя compose-файла + текст compose."""
    stack_name = compose_store.validate_stack_name(stack)
    if not compose_store.stack_exists(stack_name):
        raise StepError(
            "read_stack", -1, title="Стек не найден",
            detail=f"проект «{stack_name}» отсутствует в библиотеке",
        )
    compose_file = compose_store.find_compose_filename(
        compose_store.stack_dir(stack_name)
    ) or compose_store.DEFAULT_COMPOSE_FILENAME

    files: Dict[str, bytes] = {}
    for rel in compose_store.iter_config_files(stack_name):
        key = rel.as_posix()
        files[key] = compose_store.read_project_bytes(stack_name, key)
    if compose_file not in files:
        raise StepError(
            "read_stack", -1, title="Не найден Compose-файл",
            detail=f"в проекте «{stack_name}» нет {compose_file}",
        )
    text = compose_store.validate_compose_yaml(files[compose_file].decode("utf-8"))
    files[compose_file] = text.encode("utf-8")
    return files, compose_file, text


# --------------------------------------------------
# Единые операции (§19): source = library | server
# --------------------------------------------------

def up(server: dict, stack: str, emit, source: str = SOURCE_LIBRARY,
       key: Optional[str] = None) -> Deployment:
    """Запустить проект.

    source=library — выложить проект из библиотеки (атомарно) и поднять;
    source=server  — поднять уже существующий на сервере проект в его каталоге.
    В обоих случаях сначала subnet-check и `compose config -q` (§21).
    """
    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit)
    try:
        cmd = detect_compose_cmd(ssh, server)
        if source == SOURCE_SERVER:
            dep = resolve_deployment(server, stack, key)
            text = _read_remote_compose_text(ssh, server, dep)
            _check_subnets(ssh, server, text, emit)
            runner.run(
                "compose_config", f"{cmd} {dep.args()} config -q",
                title="Проверка конфигурации (compose config)",
            )
        else:
            files, compose_file, text = _library_files(stack)
            _check_subnets(ssh, server, text, emit)
            dep = _deploy_atomic(runner, cmd, stack, files, compose_file)
        runner.run(
            "compose_up", f"{cmd} {dep.args()} up -d",
            title=f"Запуск проекта «{dep.project}»",
        )
    finally:
        ssh.close()
    return dep


def restart(server: dict, stack: str, emit, source: str = SOURCE_LIBRARY,
            key: Optional[str] = None) -> Deployment:
    """Перезапустить/применить конфигурацию.

    Семантика — `up -d` (§20): именно она пересоздаёт контейнеры под изменённый
    Compose-файл, тогда как `compose restart` только передёргивает старые.
    """
    return up(server, stack, emit, source=source, key=key)


def down(server: dict, stack: str, emit, source: str = SOURCE_LIBRARY,
         key: Optional[str] = None) -> Deployment:
    """Остановить и удалить контейнеры проекта.

    Без `-v` — тома с данными сохраняются (§11). Без `|| true` — ошибка down
    остаётся ошибкой задачи и не даёт удалить каталог.
    """
    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit)
    try:
        cmd = detect_compose_cmd(ssh, server)
        dep = (resolve_deployment(server, stack, key) if source == SOURCE_SERVER
               else managed_deployment(stack))
        if source != SOURCE_SERVER:
            exists = runner.probe(
                f"test -d {shlex.quote(dep.working_dir)} && echo yes || echo no"
            )
            if exists != "yes":
                raise StepError(
                    "not_deployed", -1, title="Проект не развёрнут",
                    detail=(
                        f"на сервере нет каталога {dep.working_dir} — проект ещё не "
                        f"развёртывался или удалён вручную"
                    ),
                )
        runner.run(
            "compose_down", f"{cmd} {dep.args()} down",
            title=f"Остановка проекта «{dep.project}» (тома сохраняются)",
        )
    finally:
        ssh.close()
    return dep


def _read_remote_compose_text(ssh, server, deployment: Deployment) -> str:
    """Текст основного Compose-файла развёртывания (для subnet-check)."""
    candidates = list(deployment.config_files)
    if not candidates and deployment.working_dir:
        candidates = [
            f"{deployment.working_dir}/{n}" for n in compose_store.COMPOSE_FILENAMES
        ]
    for path in candidates:
        _, out, _ = exec_sudo(
            ssh, server, f"cat {shlex.quote(path)} 2>/dev/null || true"
        )
        if (out or "").strip():
            return out
    return ""


def fetch_logs(server: dict, stack: str, tail: int = 200,
               source: str = SOURCE_LIBRARY, key: Optional[str] = None) -> str:
    """Логи проекта (read-only). Работает и для library, и для server."""
    try:
        tail_n = int(tail)
    except (TypeError, ValueError):
        tail_n = 200
    tail_n = max(1, min(tail_n, 2000))

    ssh = create_ssh_client(server)
    try:
        cmd = detect_compose_cmd(ssh, server)
        dep = (resolve_deployment(server, stack, key) if source == SOURCE_SERVER
               else managed_deployment(stack))
        _, out, err = exec_sudo(
            ssh, server,
            f"{cmd} {dep.args()} logs --no-color --tail {tail_n} 2>&1 || true",
        )
        return out or err or ""
    finally:
        ssh.close()


# --------------------------------------------------
# Файловые операции на сервере (docs/compose-model.md §9)
# --------------------------------------------------

def _resolve_remote_path(dep: "Deployment", rel_path: str) -> str:
    """Абсолютный путь файла внутри working_dir развёртывания.

    rel_path проходит ту же валидацию, что и в библиотеке (safe_relative_path):
    без абсолютных путей, «..» и имён дисков — защита от выхода за пределы
    каталога проекта на сервере.
    """
    rel = compose_store.safe_relative_path(rel_path)
    if not dep.working_dir:
        raise StepError(
            "resolve_remote_path", -1, title="Путь на сервере",
            detail="у развёртывания нет working_dir",
        )
    return f"{dep.working_dir}/{rel.as_posix()}"


def list_remote_files(server: dict, stack: str, key: Optional[str] = None) -> List[Dict[str, Any]]:
    """Файлы развёртывания на сервере для UI: [{path, size, is_compose}].

    Обход тем же конфиг-набором (§3), что и библиотека — пользователь видит
    ровно то, что попадает в бэкап/fingerprint, без data/ и logs/.
    """
    dep = resolve_deployment(server, stack, key)
    wd = dep.working_dir
    if not wd:
        return []
    # find -path '*/<dir>/*' — те же исключения, что и у tar (любая глубина);
    # 'путь\tразмер' на строку. Найденное перепроверяется по размеру (конфиг-
    # предикат §3: >1 МиБ — не конфиг).
    excludes = " ".join(
        f"! -path '*/{d}/*'" for d in sorted(compose_store.CONFIG_EXCLUDE_DIRS)
    ) + " ! -path '*/?*_data/*'"
    ssh = create_ssh_client(server)
    try:
        _, out, _ = exec_sudo(
            ssh, server,
            f"cd {shlex.quote(wd)} 2>/dev/null && "
            f"find . -type f {excludes} -printf '%p\\t%s\\n' 2>/dev/null || true",
        )
    finally:
        ssh.close()
    out_list: List[Dict[str, Any]] = []
    cfg_set = {c.rsplit("/", 1)[-1] for c in dep.config_files if c}
    for line in (out or "").splitlines():
        line = line.strip()
        if not line or "\t" not in line:
            continue
        p, s = line.rsplit("\t", 1)
        p = p.strip()
        if p.startswith("./"):
            p = p[2:]
        if not p:
            continue
        try:
            rel = compose_store.safe_relative_path(p).as_posix()
        except StepError:
            continue
        try:
            size = int(s.strip() or "0")
        except ValueError:
            size = 0
        if size > compose_store.CONFIG_MAX_FILE_SIZE:
            continue
        out_list.append({
            "path": rel,
            "size": size,
            # Основной Compose-файл помечаем для UI (его нельзя удалять).
            "is_compose": rel in cfg_set or rel in compose_store.COMPOSE_FILENAMES,
        })
    out_list.sort(key=lambda f: f["path"])
    return out_list


def fetch_remote_file(server: dict, stack: str, rel_path: str,
                      key: Optional[str] = None) -> Dict[str, Any]:
    """Прочитать файл развёртывания: {path, size, text?, binary?, b64?, mime?}.

    Текст читается для редактора; бинарные (jpg/png/webp/gif) — base64 для
    превью (§9). Размер файла ≤ MAX_PROJECT_FILE_SIZE (5 МиБ).
    """
    dep = resolve_deployment(server, stack, key)
    path = _resolve_remote_path(dep, rel_path)
    ssh = create_ssh_client(server)
    try:
        # Размер заранее: cat гигабайта в base64 — не то, что нам нужно.
        _, sz_out, _ = exec_sudo(
            ssh, server, f"stat -c %s {shlex.quote(path)} 2>/dev/null || echo 0",
        )
        try:
            size = int((sz_out or "").strip().splitlines()[0] or "0")
        except (ValueError, IndexError):
            size = 0
        if size > compose_store.MAX_PROJECT_FILE_SIZE:
            raise StepError(
                "file_too_large", -1, title="Файл слишком велик",
                detail=(
                    f"«{rel_path}» занимает {size / (1024 * 1024):.1f} МБ "
                    f"(лимит {compose_store.MAX_PROJECT_FILE_SIZE // (1024 * 1024)} МБ)."
                ),
            )
        _, out, _ = exec_sudo(
            ssh, server,
            f"base64 -w0 {shlex.quote(path)} 2>/dev/null || true",
        )
        raw_b64 = (out or "").strip()
        if not raw_b64:
            raise StepError(
                "read_remote_file", -1, title="Файл не найден",
                detail=f"{path} отсутствует или недоступен на сервере",
            )
        data = base64.b64decode(raw_b64, validate=False)
        mime = _sniff_mime(data)
        is_binary = mime.startswith("image/") or _is_binary_bytes(data)
        result: Dict[str, Any] = {"path": rel_path, "size": len(data)}
        if is_binary:
            result["binary"] = True
            result["b64"] = raw_b64
            result["mime"] = mime
        else:
            result["binary"] = False
            result["text"] = data.decode("utf-8", errors="replace")
        return result
    finally:
        ssh.close()


def write_remote_file(server: dict, stack: str, rel_path: str, content: str,
                      key: Optional[str] = None) -> Dict[str, Any]:
    """Записать файл развёртывания (редактор §8). Возврат: {path, size}.

    Запись через тот же приём, что и деплой: SFTP → /tmp → sudo mv (non-root
    не пишет в каталог проекта напрямую). Перезапись с проверкой размера.
    """
    dep = resolve_deployment(server, stack, key)
    path = _resolve_remote_path(dep, rel_path)
    data = content.encode("utf-8")
    if len(data) > compose_store.MAX_PROJECT_FILE_SIZE:
        raise StepError(
            "file_too_large", -1, title="Файл слишком велик",
            detail=f"лимит {compose_store.MAX_PROJECT_FILE_SIZE // (1024 * 1024)} МБ",
        )
    remote_tmp = f"/tmp/bot4vps_edit_{uuid.uuid4().hex[:12]}"
    sftp = None
    ssh = create_ssh_client(server)
    try:
        sftp = ssh.open_sftp()
        with sftp.file(remote_tmp, "wb") as f:
            f.write(data)
        sftp.close()
        sftp = None
        runner = StepRunner(ssh, server, lambda _msg: None)
        runner.run(
            "write_remote_file",
            f"cp {shlex.quote(remote_tmp)} {shlex.quote(path)} && "
            f"rm -f {shlex.quote(remote_tmp)}",
            title="Запись файла",
        )
        return {"path": rel_path, "size": len(data)}
    finally:
        if sftp is not None:
            try:
                sftp.close()
            except Exception:
                pass
        ssh.close()


def delete_remote_file(server: dict, stack: str, rel_path: str,
                       key: Optional[str] = None) -> str:
    """Удалить файл развёртывания (кроме основного Compose-файла)."""
    dep = resolve_deployment(server, stack, key)
    path = _resolve_remote_path(dep, rel_path)
    cfg_bases = {c.rsplit("/", 1)[-1] for c in dep.config_files if c}
    if rel_path in cfg_bases or rel_path in compose_store.COMPOSE_FILENAMES:
        raise StepError(
            "delete_compose_file", -1, title="Нельзя удалить",
            detail="основной Compose-файл удалить нельзя",
        )
    ssh = create_ssh_client(server)
    try:
        runner = StepRunner(ssh, server, lambda _msg: None)
        runner.run(
            "delete_remote_file",
            f"rm -f {shlex.quote(path)}",
            title="Удаление файла",
        )
        return rel_path
    finally:
        ssh.close()


def _is_binary_bytes(data: bytes) -> bool:
    """Бинарность по содержимому — как конфиг-предикат (NUL в первых 8 КиБ)."""
    return b"\x00" in data[:8192]


def _sniff_mime(data: bytes) -> str:
    """Минимальный сниффер для превью (§9): jpg/png/webp/gif, иначе octet-stream."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "application/octet-stream"


# --------------------------------------------------
# Импорт проекта с сервера в библиотеку (§17)
# --------------------------------------------------

def import_from_server(server: dict, stack: str, overwrite: bool, emit,
                       key: Optional[str] = None,
                       target_name: Optional[str] = None) -> str:
    """Импортировать проект с сервера в библиотеку ЦЕЛИКОМ.

    Переносится вся структура каталога проекта (compose + .env + config/ + …),
    а не только YAML. Работает и для внешних проектов — по их реальному
    working_dir (§16).
    """
    name = compose_store.validate_stack_name(target_name or stack)
    if not overwrite and compose_store.stack_exists(name):
        raise StepError(
            "already_exists", -1, title="Стек уже существует",
            detail=(
                f"проект «{name}» уже есть в библиотеке Bot4VPS. "
                f"Разрешите перезапись или выберите другое имя."
            ),
        )

    ssh = create_ssh_client(server)
    try:
        dep = resolve_deployment(server, stack, key)
        # Размер проверяем до чтения (только конфиг-набор — данные не тянем),
        # чтобы дать внятную ошибку вместо многоминутного base64 впустую.
        size = _du_bytes(ssh, server, dep.working_dir, config_only=True)
        if size > PROJECT_READ_LIMIT:
            raise StepError(
                "import_too_large", -1, title="Проект слишком велик",
                detail=(
                    f"{dep.working_dir} занимает {size / (1024 * 1024):.0f} МБ "
                    f"(лимит {PROJECT_READ_LIMIT // (1024 * 1024)} МБ).\n\n"
                    f"Похоже, рядом с Compose-файлом лежат данные: тома, дампы "
                    f"или БД. Библиотека хранит конфигурацию, а не данные — "
                    f"перенесите их из каталога проекта либо правьте "
                    f"Compose-файл на сервере."
                ),
            )
        emit(f"• Чтение проекта с сервера ({dep.working_dir})")
        files = _read_remote_project_files(ssh, server, dep)
        if not files:
            raise StepError(
                "import_failed", -1, title="Не удалось прочитать проект",
                detail=f"каталог {dep.working_dir} пуст или недоступен",
            )
        # Compose-файл может лежать под нестандартным именем — приводим к
        # ожидаемому, иначе библиотека не опознает проект.
        if not any(n in files for n in compose_store.COMPOSE_FILENAMES):
            cfg_name = ""
            for cfg in dep.config_files:
                base = cfg.rsplit("/", 1)[-1]
                if base in files:
                    cfg_name = base
                    break
            if cfg_name:
                files[compose_store.DEFAULT_COMPOSE_FILENAME] = files.pop(cfg_name)
                emit(f"   {cfg_name} → {compose_store.DEFAULT_COMPOSE_FILENAME}")
        emit(f"• Сохранение в библиотеку ({len(files)} файлов)")
        compose_store.write_project(name, files)
    finally:
        ssh.close()
    return name


# --------------------------------------------------
# Удаление проекта с сервера (§11, §18)
# --------------------------------------------------

def _deployment_containers(text: str, deployment: Deployment) -> List[Tuple[str, str]]:
    """Вернуть ``[(container_id, state)]`` для точного deployment по labels.

    Compose YAML намеренно не читается: удаление остановленного проекта должно
    работать даже с повреждённым конфигом. Working dir не даёт смешать
    одноимённые проекты из разных каталогов.
    """
    expected_dir = deployment.working_dir.rstrip("/")
    out: List[Tuple[str, str]] = []
    for line in (text or "").splitlines():
        parts = line.rstrip().split("\t")
        if len(parts) < 4:
            continue
        container_id, project, working_dir, state = (p.strip() for p in parts[:4])
        if (
            container_id
            and project == deployment.project
            and working_dir.rstrip("/") == expected_dir
        ):
            out.append((container_id, state.lower()))
    return out


def delete_from_server(server: dict, stack: str, emit,
                       source: str = SOURCE_LIBRARY,
                       key: Optional[str] = None) -> str:
    """Удалить Compose-проект и его файлы с сервера.

    У работающего проекта сохраняется строгий порядок: успешный ``compose down``
    (без ``-v``), затем удаление каталога. Если все контейнеры уже остановлены,
    Compose-файл не разбирается: остановленные контейнеры удаляются напрямую по
    Docker labels, затем удаляется каталог. Локальную библиотеку не трогаем.
    """
    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit)
    try:
        dep = (resolve_deployment(server, stack, key) if source == SOURCE_SERVER
               else managed_deployment(stack))
        target = dep.working_dir
        if not target or target == "/" or target.count("/") < 2:
            raise StepError(
                "unsafe_path", -1, title="Небезопасный путь",
                detail=f"отказ удалять каталог {target!r}",
            )

        exists = runner.probe(f"test -d {shlex.quote(target)} && echo yes || echo no")
        if exists != "yes":
            raise StepError(
                "not_found", -1, title="Каталог проекта не найден",
                detail=f"на сервере нет {target}",
            )

        identities_rc, identities_out, identities_err = exec_sudo(
            ssh, server, _PS_CONTAINER_IDENTITIES_CMD
        )
        if identities_rc != 0:
            raise StepError(
                "inspect_project_containers", identities_rc,
                title="Не удалось проверить контейнеры проекта",
                detail=(identities_err or identities_out or "docker ps завершился с ошибкой"),
            )
        project_containers = _deployment_containers(identities_out, dep)
        running = any(state == "running" for _, state in project_containers)

        if running:
            # Для реально работающего проекта down обязателен. Ошибка Compose
            # прерывает операцию: файлы не удаляем и успех не изображаем.
            cmd = detect_compose_cmd(ssh, server)
            runner.run(
                "compose_down", f"{cmd} {dep.args()} down",
                title=f"Остановка проекта «{dep.project}» (тома сохраняются)",
            )
        elif project_containers:
            # Контейнеры уже остановлены: повреждённый YAML не должен мешать
            # удалению. docker rm без -v сохраняет именованные тома. Если какой-то
            # контейнер успел запуститься, rm завершится ошибкой до удаления файлов.
            ids = " ".join(shlex.quote(container_id) for container_id, _ in project_containers)
            runner.run(
                "remove_stopped_containers", f"docker rm {ids}",
                title=f"Удаление остановленных контейнеров проекта «{dep.project}»",
            )

        runner.run(
            "remove_dir", f"rm -rf {shlex.quote(target)}",
            title=f"Удаление каталога {target}",
        )
    finally:
        ssh.close()
    return dep.project


# --------------------------------------------------
# Сравнение версий (§23)
# --------------------------------------------------

def remote_fingerprint(server: dict, stack: str, key: Optional[str] = None,
                       source: str = SOURCE_LIBRARY) -> Optional[str]:
    """Fingerprint файлов проекта на сервере — для сравнения с библиотекой."""
    ssh = create_ssh_client(server)
    try:
        dep = (resolve_deployment(server, stack, key) if source == SOURCE_SERVER
               else managed_deployment(stack))
        files = _read_remote_project_files(ssh, server, dep)
        if not files:
            return None
        return compose_store.fingerprint_files(files)
    finally:
        ssh.close()
