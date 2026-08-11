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
    """Прочитать файлы проекта с сервера как {rel_path: bytes}.

    Нужно и для импорта (§17), и для сравнения версий (§23). Передаём одним
    tar+base64, чтобы не делать по SSH-вызову на файл и не терять бинарные
    данные. Пустой dict, если каталог недоступен.

    Размер проверяем ДО tar: иначе каталог на 60 ГБ будет минуты гнаться через
    base64 (это ещё +33 % к объёму), чтобы затем упасть на limit_bytes.
    """
    wd = deployment.working_dir
    if not wd:
        return {}
    size = _du_bytes(ssh, server, wd)
    if size > limit_bytes:
        return {}
    _, out, _ = exec_sudo(
        ssh, server,
        f"cd {shlex.quote(wd)} 2>/dev/null && "
        f"tar -cf - --exclude-vcs . 2>/dev/null | base64 -w0 || true",
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
    return files


def _du_bytes(ssh, server, wd: str) -> int:
    """Размер каталога через du на уже открытом SSH. 0, если не определить."""
    if not wd:
        return 0
    try:
        _, out, _ = exec_sudo(
            ssh, server,
            f"du -sb {shlex.quote(wd)} 2>/dev/null | cut -f1 || echo 0",
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
        {name, working_dir, config_files, managed, key, deployed,
         containers_total, containers_running, fingerprint}
    fingerprint считается только для managed-каталогов (для сравнения с
    библиотекой); для внешних он не нужен и стоил бы лишнего чтения.
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
            # (§23) и решить, показывать ли «Импортировать». Считаем его и для
            # ВНЕШНИХ проектов — иначе для них сравнение невозможно и кнопка
            # импорта работала бы «слепо», рискуя перезаписать локальную копию.
            # Чтение пропускаем, если одноимённого проекта в библиотеке нет:
            # сравнивать не с чем, а tar+base64 по SSH не бесплатен.
            if dep.managed or compose_store.stack_exists_safe(dep.project):
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
    for rel in compose_store.iter_project_files(stack_name):
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
        # Размер проверяем до чтения, чтобы дать внятную ошибку вместо
        # многоминутного base64 впустую.
        size = _du_bytes(ssh, server, dep.working_dir)
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

def delete_from_server(server: dict, stack: str, emit,
                       source: str = SOURCE_LIBRARY,
                       key: Optional[str] = None) -> str:
    """Остановить проект и удалить его файлы с сервера.

    Строгий порядок (§18): сначала `compose down` (без -v). Если down упал —
    НИЧЕГО не удаляем и возвращаем ошибку. Библиотеку не трогаем вообще.
    """
    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit)
    try:
        cmd = detect_compose_cmd(ssh, server)
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

        # down БЕЗ «|| true»: провал прерывает операцию до удаления файлов.
        runner.run(
            "compose_down", f"{cmd} {dep.args()} down",
            title=f"Остановка проекта «{dep.project}» (тома сохраняются)",
        )
        # Сюда попадаем только после успешного down.
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
