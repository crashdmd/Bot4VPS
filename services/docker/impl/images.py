# -*- coding: utf-8 -*-
"""Операции с образами Docker (Phase 4).

list_images   - список образов (docker images)
pull_image    - загрузка образа (docker pull)
remove_image  - удаление образа (docker rmi)
prune_images  - очистка неиспользуемых образов (docker image prune -f)
"""
from __future__ import annotations

import json
import shlex
import uuid
from typing import Any, Dict, List, Tuple

from core.integrator import StepError, StepRunner
from core.ssh import create_ssh_client, exec_sudo

from . import pull_progress, validation


class PullCancelled(Exception):
    """Загрузка образа отменена пользователем (кнопка ✕ на вкладке «Образы»).

    Специально НЕ StepError: предзагрузка compose трактует StepError как
    «не страшно, compose попробует сам», а отмена должна прервать запуск
    стека/контейнера целиком — до docker run / up -d дело не доходит.
    """

    def __init__(self, image: str):
        self.image = image
        super().__init__(f"Загрузка образа «{image}» отменена пользователем")


def _parse_images_json(text: str) -> List[Dict[str, Any]]:
    """Разобрать вывод `docker images --format '{{json .}}'` → список образов."""
    out: List[Dict[str, Any]] = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        repo = str(obj.get("Repository") or "")
        tag = str(obj.get("Tag") or "")
        if not repo or repo == "<none>":
            continue
        out.append({
            "id": str(obj.get("ID") or "")[:12],
            "repository": repo,
            "tag": tag,
            "size": str(obj.get("Size") or ""),
            "created": str(obj.get("CreatedSince") or ""),
        })
    return out


def list_images(server: dict) -> List[Dict[str, Any]]:
    """Получить список образов на сервере (read-only, без изменений).

    Возвращает:
        [{"id", "repository", "tag", "size", "created"}, ...]

    Если демон Docker остановлен — [], и никакой docker-CLI не выполняем:
    подключение к сокету подняло бы демон обратно (socket activation).
    """
    from core.ssh import exec_sudo
    ssh = create_ssh_client(server)
    try:
        _, daemon_out, _ = exec_sudo(
            ssh, server, "systemctl is-active docker 2>/dev/null || echo inactive")
        if daemon_out.strip() != "active":
            return []
        _, out, _ = exec_sudo(
            ssh, server,
            "docker images --no-trunc --format '{{json .}}' 2>/dev/null || true",
        )
        return _parse_images_json(out)
    finally:
        ssh.close()


def pull_image(server: dict, image: str, emit) -> str:
    """Загрузить образ (docker pull). Валидация + живой прогресс.

    Args:
        image: имя образа (например nginx:alpine)
        emit: progress callback

    Returns:
        Провалидированное имя образа
    """
    image_val = validation.validate_image(image)
    ssh = create_ssh_client(server)
    try:
        pull_image_on(ssh, server, image_val, emit)
    finally:
        ssh.close()
    return image_val


def _split_image_ref(image: str) -> Tuple[str, str]:
    """«repo/app:tag» → («repo/app», «tag»). Без тега — latest.

    Двоеточие ДО последнего слэша — порт реестра, не тег. Дайджест-ссылки
    (repo@sha256:…) здесь не поддерживаются — для них вызывающий код уходит
    в CLI-фолбэк.
    """
    last = image.rsplit("/", 1)[-1]
    if ":" in last:
        repo, tag = image.rsplit(":", 1)
        return repo, tag
    return image, "latest"


def _api_pull_available(ssh, server: dict) -> bool:
    """Основной путь тяги — Docker HTTP API через curl на сокете демона.

    Даёт структурированный прогресс-стрим (NDJSON с current/total), который
    не зависит от версии CLI: новые docker (29+) в терминальном выводе без
    TTY прогресс вообще не печатают. Требует curl на сервере — его нет не
    везде, поэтому недоступность не ошибка, а переключение на фолбэк.
    """
    _, out, _ = exec_sudo(
        ssh, server,
        "command -v curl >/dev/null 2>&1 && test -S /var/run/docker.sock "
        "&& echo yes || echo no",
    )
    return out.strip() == "yes"


def _api_pull(ssh, server: dict, image: str, emit, tracker) -> None:
    """Тяга образа через POST /images/create с разбором NDJSON-стрима.

    Строки события идут в лог задачи в человеческом виде (как у docker CLI),
    байты — в трекер. Успех = строка «Status: …» в стриме; ошибка — поле
    error у события (Docker отдаёт его в теле 4xx/5xx) или ненулевой exit
    curl.
    """
    from urllib.parse import quote
    repo, tag = _split_image_ref(image)
    url = (f"http://localhost/images/create"
           f"?fromImage={quote(repo, safe='')}&tag={quote(tag, safe='')}")
    # Уникальный маркер в аргументах curl: по нему кнопка «✕» находит и убивает
    # именно этот процесс на сервере (pkill -f). Квадратные скобки в kill_pattern
    # не дают pkill сматчить собственную командную строку.
    uid = uuid.uuid4().hex
    header = f"X-Bot4Vps-Pull-{uid}"
    tracker.kill_pattern = f"[X]-Bot4Vps-Pull-{uid}"
    command = (
        "curl -sS --unix-socket /var/run/docker.sock -X POST "
        f"-H {shlex.quote(header)} " + shlex.quote(url)
    )
    error_detail: List[str] = []
    saw_status = False

    def on_line(line: str) -> None:
        nonlocal saw_status
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return  # мусорный кусок стрима — пропускаем
        status = str(obj.get("status") or "")
        layer = str(obj.get("id") or "")
        detail = obj.get("progressDetail") or {}
        err = obj.get("error") or (obj.get("errorDetail") or {}).get("message")
        if err:
            error_detail.append(str(err))
            return
        tracker.feed_event(status, layer, detail.get("current"), detail.get("total"))
        if status.startswith("Status:"):
            saw_status = True
        if not status:
            return
        # Лог — в стиле docker CLI: «слой: статус байты». Downloading-строк
        # в стриме много (каждые ~1 МиБ) — пишем только когда процент образа
        # изменился, иначе лог тонет в повторах.
        human = f"{layer}: {status}" if layer else status
        if status == "Downloading":
            if tracker.progress[0] != getattr(on_line, "_last_pct", -1):
                on_line._last_pct = tracker.progress[0]  # type: ignore[attr-defined]
                current, total = detail.get("current"), detail.get("total")
                if current is not None and total:
                    human = f"{layer}: Downloading {_fmt(current)} / {_fmt(total)}"
                    emit("   " + human)
        else:
            emit("   " + human)

    exit_code, out, err = exec_sudo(ssh, server, command, emit=on_line)
    if tracker.cancelled:
        # Кнопка «✕»: обрыв соединения с демоном — Docker сам откатывает
        # недокачанные слои; StepError тут был бы неверной трактовкой.
        raise PullCancelled(image)
    if error_detail:
        raise StepError(
            "pull_image", exit_code or 1,
            title=f"Загрузка образа «{image}»",
            detail="\n".join(error_detail)[:500],
        )
    if exit_code != 0:
        raise StepError(
            "pull_image", exit_code,
            title=f"Загрузка образа «{image}»",
            detail=(err.strip() or out.strip())[:500],
        )
    if not saw_status:
        # API ответил, но стрим без «Status:» — так выглядит, например,
        # 404 «pull access denied» с телом {"message": ...}.
        message = ""
        for line in (out or "").splitlines():
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if obj.get("message"):
                message = str(obj["message"])
                break
        raise StepError(
            "pull_image", 1,
            title=f"Загрузка образа «{image}»",
            detail=message[:500] or (out or "").strip()[:500],
        )


def _fmt(n) -> str:
    """Байты события → «14.2MB» (десятичные суффиксы, как у docker)."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "?"
    for div, suf in ((10 ** 9, "GB"), (10 ** 6, "MB"), (10 ** 3, "kB")):
        if n >= div:
            return f"{n / div:.1f}{suf}"
    return f"{n}B"


def _cli_pull(ssh, server: dict, image: str, emit, tracker) -> None:
    """Фолбэк без curl: обычный docker pull с текстовым парсингом.

    На новых CLI (29+) без TTY прогресса в тексте нет — покажем факт
    загрузки без процентов; на старых строки Downloading распарсятся.
    """
    # Отмена CLI-пути: маркера в аргументах нет, убираем по самой команде.
    tracker.kill_pattern = f"[d]ocker pull {image}"
    exit_code, out, err = exec_sudo(
        ssh, server, f"docker pull {shlex.quote(image)}",
        emit=lambda line: (tracker.feed(line), emit("   " + line)),
    )
    if tracker.cancelled:
        raise PullCancelled(image)
    if exit_code != 0:
        raise StepError(
            "pull_image", exit_code,
            title=f"Загрузка образа «{image}»",
            detail=(err.strip() or out.strip())[:500],
        )


def pull_image_on(ssh, server: dict, image: str, emit) -> None:
    """Загрузить образ на уже открытом SSH — общий код вкладки «Образы» и compose.

    Строки прогресса идут и в лог задачи, и в pull_progress: вкладка «Образы»
    видит процент загрузки. Основной путь — Docker HTTP API (структурированный
    прогресс); фолбэк без curl — docker pull CLI. Шаг именованный (pull_image
    в StepError) — как у остальных шагов.
    """
    emit(f"• Загрузка образа «{image}»")
    server_id = str(server.get("id") or "")
    tracker = pull_progress.PullTracker(
        server_id, image, ssh=ssh, server=server,
    )
    try:
        # Дайджест-ссылки API-путём не передаём (fromImage/tag их не кодируют) —
        # сразу CLI.
        try:
            if "@" not in image and _api_pull_available(ssh, server):
                _api_pull(ssh, server, image, emit, tracker)
            else:
                _cli_pull(ssh, server, image, emit, tracker)
        except PullCancelled:
            emit(f"⚠ Загрузка «{image}» отменена — запуск прерван")
            raise
    finally:
        tracker.close()


def cancel_pull(server_id: str, image: str) -> bool:
    """Отменить активную загрузку образа (кнопка ✕ на вкладке «Образы»).

    Убивает процесс загрузки на сервере (pkill -f по уникальному маркеру
    curl или «docker pull <image>»): Docker отменяет тянущиеся слои при
    обрыве соединения. SSH-клиент и параметры сервера берём у самого
    трекера — нового подключения не открываем (paramiko держит параллельные
    каналы, задача и отмена не мешают друг другу). False — загрузка уже
    завершилась (кнопка нажата в последний момент).
    """
    tracker = pull_progress.find_tracker(server_id, image)
    if tracker is None or not tracker.kill_pattern or tracker.ssh is None:
        return False
    tracker.mark_cancelled()
    try:
        exec_sudo(
            tracker.ssh, tracker.server,
            f"pkill -f -- {shlex.quote(tracker.kill_pattern)} || true",
            timeout=30,
        )
    except Exception:
        # Флаг уже поднят: даже если pkill не прошёл, задача не завершится
        # «успехом» — exec вернётся с ошибкой, и загрузка не продолжится.
        pass
    return True


def remove_image(server: dict, image: str, emit) -> str:
    """Удалить образ (docker rmi). Валидация + StepRunner.

    Args:
        image: полное имя образа (repo:tag или image_id)
        emit: progress callback

    Returns:
        Провалидированное имя образа
    """
    # Для удаления можем принять либо полное имя, либо ID (12 символов hex)
    image_val = image.strip()
    if not image_val:
        from core.integrator import StepError
        raise StepError("remove_image", -1, title="Удаление образа",
                        detail="имя образа не может быть пустым")

    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit)
    try:
        runner.run(
            "remove_image", f"docker rmi {shlex.quote(image_val)}",
            title=f"Удаление образа «{image_val}»",
        )
    finally:
        ssh.close()
    return image_val


def prune_images(server: dict, emit) -> str:
    """Удалить неиспользуемые образы (docker image prune -a -f).

    Удаляет ВСЕ образы, не привязанные к контейнерам (включая tagged).

    Returns:
        Краткая статистика освобождённого места
    """
    ssh = create_ssh_client(server)
    runner = StepRunner(ssh, server, emit)
    try:
        output = runner.run(
            "prune_images", "docker image prune -a -f",
            title="Очистка неиспользуемых образов",
        )
        # Вывод docker image prune содержит строку "Total reclaimed space: ..."
        for line in output.split("\n"):
            if "reclaimed" in line.lower():
                return line.strip()
        return "Очистка завершена"
    finally:
        ssh.close()
