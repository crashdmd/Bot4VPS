"""WebSocket-терминал: мост между браузером (xterm.js) и :class:`core.terminal.ShellSession`.

Тонкий адаптер: принимает WS-соединение, авторизует по сессионной куке (как
``require_auth``), открывает свою PTY-сессию и гонит байты в обе стороны.
Вся SSH/PTY-логика — в ядре (``core.terminal``), здесь нет работы с paramiko.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

# Без активного ввода/вывода столько секунд — закрываем сессию (не висит вечно).
_IDLE_TIMEOUT = 15 * 60


def _ws_authorized(websocket: WebSocket) -> bool:
    """Та же проверка, что require_auth, но для WS: сессия приходит в scope."""
    from ui.web.security import auth_enabled

    if not auth_enabled():
        return True
    session = websocket.scope.get("session") or {}
    return bool(session.get("user"))


async def _notify(websocket: WebSocket, text: str) -> None:
    try:
        await websocket.send_text(text)
    except Exception:
        pass


@router.websocket("/api/servers/{server_id}/shell/ws")
async def shell_ws(websocket: WebSocket, server_id: str):
    await websocket.accept()

    # 1) авторизация
    if not _ws_authorized(websocket):
        await _notify(websocket, "\r\n\x1b[31mТребуется авторизация.\x1b[0m\r\n")
        await websocket.close(code=4401)
        return

    # 2) сервер существует?
    from core.storage import find_server
    from core.terminal import ShellSession

    server = find_server(server_id)
    if not server:
        await _notify(websocket, "\r\n\x1b[31mСервер не найден.\x1b[0m\r\n")
        await websocket.close(code=4404)
        return

    # 3) открываем собственную PTY-сессию
    session = ShellSession(server)
    try:
        await asyncio.to_thread(session.open)
    except Exception as e:
        await _notify(websocket, f"\r\n\x1b[31mНе удалось подключиться по SSH: {e}\x1b[0m\r\n")
        await websocket.close(code=4503)
        return

    last_activity = time.monotonic()
    stop = asyncio.Event()
    # Авто-ввод sudo-пароля при запуске скрипта на не-root сервере (как в TG).
    # armed=True сразу после отправки «sudo bash …»; reader снимет флаг и
    # подставит пароль, когда sudo напечатает свой запрос пароля (эхо уже выключено,
    # поэтому пароль не виден в терминале).
    sudo_pw = {"armed": False, "password": ""}

    # PTY → браузер
    async def reader():
        nonlocal last_activity
        while not stop.is_set() and not session.closed:
            try:
                data = await asyncio.to_thread(session.recv)
            except Exception:
                break  # recv пробросил фатальную ошибку — сессия умерла
            if data:
                text = data.decode("utf-8", errors="replace")
                last_activity = time.monotonic()
                # sudo запросил пароль — подставляем автоматически (как в TG).
                # Эхо уже выключено самим sudo, поэтому пароль не виден в терминале.
                if sudo_pw["armed"] and ("[sudo]" in text or "password for" in text):
                    sudo_pw["armed"] = False
                    try:
                        await asyncio.to_thread(session.send, sudo_pw["password"] + "\n")
                    except Exception:
                        break
                try:
                    await websocket.send_text(text)
                except Exception:
                    break  # клиент отвалился
            elif time.monotonic() - last_activity > _IDLE_TIMEOUT:
                await _notify(websocket, "\r\n\x1b[33mСессия закрыта по таймауту бездействия.\x1b[0m\r\n")
                break

    # браузер → PTY (ввод + resize)
    async def writer():
        nonlocal last_activity
        while not stop.is_set():
            try:
                msg = await websocket.receive_text()
            except (WebSocketDisconnect, Exception):
                break  # клиент закрыл соединение
            last_activity = time.monotonic()
            try:
                payload = json.loads(msg)
            except Exception:
                continue
            kind = payload.get("type")

            # запуск скрипта в этой PTY-сессии: stage (mktemp + sftp + chmod) + авторан.
            # Сами баннеры идут через _notify (out-of-band, не в shell); команда —
            # отдельным send, её печатает эхом сама оболочка после свежего промпта.
            if kind == "run_script":
                name = (payload.get("name") or "").strip()
                if not name or Path(name).name != name or not name.endswith(".sh"):
                    await _notify(websocket, "\r\n\x1b[31mНекорректное имя скрипта.\x1b[0m\r\n")
                    continue
                await _notify(websocket, f"\r\n\x1b[36m📜 Готовлю {name}…\x1b[0m\r\n")
                try:
                    remote = await asyncio.to_thread(session.stage_script, name)
                except Exception as e:
                    await _notify(websocket, f"\r\n\x1b[31mНе удалось подготовить скрипт: {e}\x1b[0m\r\n")
                    continue
                await _notify(websocket, f"\x1b[32m✅ Готов: {remote}\x1b[0m\r\n\x1b[36m▶ Запускаю…\x1b[0m\r\n\r\n")
                try:
                    # root-сервер — напрямую. Не-root — через sudo; если пароль известен,
                    # он подставится автоматически (sudo_pw + reader), как в TG-пути.
                    is_root = (server.get("user", "") or "").lower() == "root"
                    sudo_pass = server.get("password", "") or ""
                    if not is_root and sudo_pass:
                        sudo_pw["password"] = sudo_pass
                        sudo_pw["armed"] = True
                    run_cmd = f"bash {remote}" if is_root else f"sudo bash {remote}"
                    # ведущий \n → свежий промпт; дальше команда печатается эхом оболочки
                    await asyncio.to_thread(session.send, f"\n{run_cmd}\n")
                except Exception:
                    break  # send пробросил — канал умер
                continue

            try:
                if kind == "input":
                    await asyncio.to_thread(session.send, payload.get("data", ""))
                elif kind == "resize":
                    await asyncio.to_thread(
                        session.resize, int(payload.get("cols") or 120), int(payload.get("rows") or 40)
                    )
            except Exception:
                break  # send пробросил — канал умер

    # FIRST_COMPLETED: какая задача ни завершится первой (SSH умер / клиент ушёл /
    # idle) — вторую отменяем. Иначе writer, заблокированный в receive_text,
    # держал бы WS открытым при уже мёртвом канале («терминал жив, хотя канал умер»).
    rt = asyncio.create_task(reader())
    wt = asyncio.create_task(writer())
    try:
        await asyncio.wait({rt, wt}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop.set()
        for t in (rt, wt):
            if not t.done():
                t.cancel()
        for t in (rt, wt):
            try:
                await t
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        await asyncio.to_thread(session.close)
        try:
            await websocket.close()
        except Exception:
            pass
