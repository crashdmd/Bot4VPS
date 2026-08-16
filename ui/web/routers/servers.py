
from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from ..deps import err, task_brief, queue_state_dict

router = APIRouter(tags=["servers"])

class ExecBody(BaseModel):
    command: str = Field(..., min_length=1, max_length=2000)
    session: bool = True

_METRICS_CMD = (
    "grep '^cpu ' /proc/stat; sleep 0.2; grep '^cpu ' /proc/stat; "
    "echo '---'; free -m | awk '/Mem:/ {print $2,$3,$7}'; "
    "echo '---'; df -P / | awk 'NR==2 {print $2,$3,$5}'; "
    "echo '---'; cat /proc/loadavg | awk '{print $1,$2,$3}'; "
    "echo '---'; uptime -p 2>/dev/null || cat /proc/uptime"
)

def _parse_cpu_pair(line1, line2):
    try:
        def parts(line):
            nums = list(map(int, line.split()[1:]))
            idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
            return idle, sum(nums)
        i1, t1 = parts(line1)
        i2, t2 = parts(line2)
        d = t2 - t1
        return round(100.0 * (1 - (i2 - i1) / d), 1) if d > 0 else 0.0
    except Exception:
        return None

def _metrics_sync(server: dict) -> dict:
    from core.ssh import create_ssh_client
    out = {
        "ok": False, "cpu": None, "ram_pct": None, "ram": "N/A",
        "disk_pct": None, "disk": "N/A", "load": "N/A", "uptime": "N/A", "error": None,
    }
    try:
        ssh = create_ssh_client(server, timeout=8)
        try:
            _, stdout, stderr = ssh.exec_command(_METRICS_CMD, timeout=15)
            raw = stdout.read().decode("utf-8", errors="ignore")
            err_s = stderr.read().decode("utf-8", errors="ignore").strip()
            blocks = [b.strip() for b in raw.split("---")]
            if len(blocks) < 5:
                out["error"] = err_s or raw or "incomplete"
                return out
            cpu_lines = [ln for ln in blocks[0].splitlines() if ln.startswith("cpu ")]
            if len(cpu_lines) >= 2:
                out["cpu"] = _parse_cpu_pair(cpu_lines[0], cpu_lines[1])
            mem = blocks[1].split()
            if len(mem) >= 2:
                total, used = int(mem[0]), int(mem[1])
                out["ram_pct"] = round(100.0 * used / total, 1) if total else 0
                out["ram"] = f"{used} / {total} MB"
            disk = blocks[2].split()
            if len(disk) >= 3:
                try:
                    out["disk_pct"] = float(disk[2].rstrip("%"))
                except ValueError:
                    out["disk_pct"] = None
                try:
                    tk, uk = int(disk[0]), int(disk[1])
                    out["disk"] = f"{uk // 1024 // 1024} / {tk // 1024 // 1024} GB"
                except Exception:
                    out["disk"] = disk[2]
            out["load"] = blocks[3].strip() or "N/A"
            out["uptime"] = blocks[4].strip() or "N/A"
            out["ok"] = True
        finally:
            ssh.close()
    except Exception as e:
        out["error"] = str(e)
    return out

def _exec_sync(server: dict, command: str) -> dict:
    from core.ssh import create_ssh_client
    try:
        ssh = create_ssh_client(server, timeout=10)
        try:
            _, stdout, stderr = ssh.exec_command(command, timeout=60)
            out = stdout.read().decode("utf-8", errors="ignore")
            err_s = stderr.read().decode("utf-8", errors="ignore")
            code = stdout.channel.recv_exit_status()
            return {"ok": code == 0, "exit_code": code, "stdout": out[-12000:], "stderr": err_s[-3000:]}
        finally:
            ssh.close()
    except Exception as e:
        return {"ok": False, "exit_code": None, "stdout": "", "stderr": str(e)}


@router.get("/api/servers")
async def api_servers(group: Optional[str] = None, online: Optional[bool] = None):
    try:
        from core.storage import load_servers
        from core.monitor import load_monitor
        from core.task_manager import task_manager

        monitor = load_monitor()
        out = []
        for s in load_servers():
            if group and (s.get("group") or "") != group:
                continue
            mid = s.get("id")
            m = monitor.get(mid) or {}
            avail = m.get("availability") or {}
            cert = m.get("certificate") or {}
            is_online = avail.get("online")
            if online is not None and is_online is not online:
                continue
            running = task_manager.get_running(mid)
            out.append({
                "id": mid,
                "name": s.get("name"),
                "group": s.get("group") or "—",
                "host": s.get("host"),
                "port": s.get("port", 22),
                "user": s.get("user"),
                "auth_type": s.get("auth_type", "password"),
                "online": is_online,
                "availability_checked": avail.get("checked"),
                "ssl_status": cert.get("status"),
                "ssl_days_left": cert.get("days_left"),
                "ssl_expires": cert.get("expires"),
                "certificate_check": bool(s.get("certificate_check")),
                "has_running": running is not None,
                "queue_len": len(task_manager.get_queue(mid)),
                "running_task_id": running.id if running else None,
            })
        return {"servers": out}
    except Exception as e:
        return err(e)


@router.get("/api/servers/{server_id}")
async def api_server(server_id: str):
    try:
        from core.storage import find_server
        from core.monitor import get_server_monitor
        from core.task_manager import task_manager

        server = find_server(server_id)
        if not server:
            raise HTTPException(404, "Сервер не найден")
        mon = get_server_monitor(server_id) or {}
        return {
            "server": {k: server.get(k) for k in (
                "id", "name", "group", "host", "port", "user",
                "auth_type", "certificate_check", "ssl_host", "key_path",
            )},
            "monitor": mon,
            "running_task": task_brief(task_manager.get_running(server_id)),
            "queue": [task_brief(t) for t in task_manager.get_queue(server_id)],
            "queue_state": queue_state_dict(server_id),
        }
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.get("/api/servers/{server_id}/metrics")
async def api_metrics(server_id: str):
    try:
        from core.storage import find_server
        server = find_server(server_id)
        if not server:
            raise HTTPException(404, "Сервер не найден")
        return await asyncio.to_thread(_metrics_sync, server)
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.get("/api/servers/{server_id}/probe")
async def api_probe(server_id: str):
    try:
        from core.storage import find_server
        from core.servers import get_server_info, format_ssh_error
        server = find_server(server_id)
        if not server:
            raise HTTPException(404, "Сервер не найден")
        info = await asyncio.to_thread(get_server_info, server)
        return {"info": info, "ssh_error_human": format_ssh_error(info.get("ssh_error"))}
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.post("/api/servers/{server_id}/exec")
async def api_exec(server_id: str, body: ExecBody):
    try:
        from core.storage import find_server
        server = find_server(server_id)
        if not server:
            raise HTTPException(404, "Сервер не найден")
        cmd = body.command.strip()
        if not cmd:
            raise HTTPException(400, "Пустая команда")
        if body.session:
            return await asyncio.to_thread(_shell_exec_sync, server, cmd)
        return await asyncio.to_thread(_exec_sync, server, cmd)
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.post("/api/servers/{server_id}/reboot")
async def api_reboot(server_id: str):
    try:
        from core.storage import find_server
        from core.servers import reboot_server
        server = find_server(server_id)
        if not server:
            raise HTTPException(404, "Сервер не найден")
        return {"ok": await asyncio.to_thread(reboot_server, server)}
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


# ---- TCP latency ----
def _tcp_ping(host: str, port: int, timeout: float = 2.0) -> dict:
    import socket
    import time
    t0 = time.perf_counter()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            ms = round((time.perf_counter() - t0) * 1000)
        return {"ok": True, "ms": ms}
    except Exception as e:
        ms = round((time.perf_counter() - t0) * 1000)
        return {"ok": False, "ms": ms, "error": str(e)}


# ---- Persistent shell sessions (in-memory) ----
_shells: dict[str, dict] = {}  # server_id -> {ssh, chan, lock}


def _close_shell(server_id: str):
    rec = _shells.pop(server_id, None)
    if not rec:
        return
    try:
        rec["chan"].close()
    except Exception:
        pass
    try:
        rec["ssh"].close()
    except Exception:
        pass


def _get_shell(server: dict):
    import threading
    import time
    from core.ssh import create_ssh_client

    sid = server["id"]
    rec = _shells.get(sid)
    if rec and rec.get("chan") and not rec["chan"].closed:
        rec["last"] = time.time()
        return rec
    _close_shell(sid)
    ssh = create_ssh_client(server, timeout=10)
    chan = ssh.invoke_shell(width=120, height=40)
    chan.settimeout(0.0)
    # drain banner
    time.sleep(0.35)
    try:
        while chan.recv_ready():
            chan.recv(4096)
    except Exception:
        pass
    rec = {"ssh": ssh, "chan": chan, "lock": threading.Lock(), "last": time.time()}
    _shells[sid] = rec
    return rec


def _shell_exec_sync(server: dict, command: str, wait: float = 8.0) -> dict:
    import time
    rec = _get_shell(server)
    with rec["lock"]:
        chan = rec["chan"]
        # clear buffer
        try:
            while chan.recv_ready():
                chan.recv(8192)
        except Exception:
            pass
        chan.send(command.rstrip() + "\n")
        buf = []
        end = time.time() + wait
        idle_rounds = 0
        while time.time() < end:
            time.sleep(0.12)
            got = False
            try:
                while chan.recv_ready():
                    chunk = chan.recv(8192).decode("utf-8", errors="ignore")
                    if chunk:
                        buf.append(chunk)
                        got = True
            except Exception:
                break
            if got:
                idle_rounds = 0
            else:
                idle_rounds += 1
                if idle_rounds >= 6 and buf:
                    break
        text = "".join(buf)
        # strip echoed command line if present
        lines = text.splitlines()
        if lines and command.strip() in lines[0]:
            lines = lines[1:]
        # drop last prompt-ish line if short
        out = "\n".join(lines)
        if len(out) > 12000:
            out = out[-12000:]
        return {"ok": True, "exit_code": None, "stdout": out, "stderr": "", "session": True}


@router.get("/api/servers/{server_id}/ping")
async def api_ping_server(server_id: str):
    try:
        from core.storage import find_server
        server = find_server(server_id)
        if not server:
            raise HTTPException(404, "Сервер не найден")
        host = server.get("host") or ""
        port = int(server.get("port") or 22)
        return await asyncio.to_thread(_tcp_ping, host, port)
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.post("/api/servers/{server_id}/shell/close")
async def api_shell_close(server_id: str):
    _close_shell(server_id)
    return {"ok": True}


# ---------- settings / CRUD ----------

class ServerUpdate(BaseModel):
    name: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    user: Optional[str] = None
    group: Optional[str] = None
    auth_type: Optional[str] = None  # password | key
    password: Optional[str] = None
    key_path: Optional[str] = None
    certificate_check: Optional[bool] = None
    ssl_host: Optional[str] = None


class ServerCreate(BaseModel):
    name: str
    host: str
    group: str = "vps"
    port: int = 22
    user: str = "root"
    auth_type: str = "password"
    password: Optional[str] = None
    key_path: Optional[str] = None
    certificate_check: Optional[bool] = None
    ssl_host: Optional[str] = None
    test: bool = True


def _wizard():
    """Импорт core.server_wizard если есть."""
    try:
        import core.server_wizard as w
        return w
    except ImportError:
        return None


class GroupCreateBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    ssl_monitor: bool = False


class GroupPatchBody(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=64)
    ssl_monitor: Optional[bool] = None


@router.get("/api/groups")
async def api_groups():
    try:
        from core.storage import load_groups, load_servers
        groups = load_groups()
        servers = load_servers()
        out = []
        for g in groups:
            if isinstance(g, str):
                name, ssl = g, g == "vps"
            else:
                name, ssl = g.get("name"), bool(g.get("ssl_monitor"))
            count = sum(1 for s in servers if s.get("group") == name)
            out.append({"name": name, "ssl_monitor": ssl, "servers": count})
        return {"groups": out}
    except Exception as e:
        return err(e)


@router.post("/api/groups")
async def api_group_create(body: GroupCreateBody):
    try:
        from core.storage import create_group
        g = create_group(body.name, body.ssl_monitor)
        return {"ok": True, "group": g}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        return err(e)


@router.patch("/api/groups/{name}")
async def api_group_patch(name: str, body: GroupPatchBody):
    try:
        from core.storage import rename_group, set_group_ssl, get_group
        current = name
        result = None
        if body.name is not None and body.name.strip() != name:
            result = rename_group(name, body.name.strip())
            current = body.name.strip()
        if body.ssl_monitor is not None:
            result = set_group_ssl(current, body.ssl_monitor)
        if result is None:
            result = get_group(current)
        return {"ok": True, "group": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        return err(e)


@router.delete("/api/groups/{name}")
async def api_group_delete(name: str):
    try:
        from core.storage import delete_group, group_server_names
        delete_group(name)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        return err(e)


@router.get("/api/keys")
async def api_keys_list():
    try:
        keys_dir = Path("keys")
        keys_dir.mkdir(parents=True, exist_ok=True)
        items = []
        for f in sorted(keys_dir.iterdir()):
            if f.is_file() and not f.name.startswith(".") and not f.name.endswith(".pub"):
                items.append({"name": f.name, "path": str(f)})
        return {"keys": items}
    except Exception as e:
        return err(e)


@router.patch("/api/servers/{server_id}")
async def api_server_update(server_id: str, body: ServerUpdate):
    try:
        from core.storage import find_server, load_servers, save_servers, is_group_ssl_enabled
        from core.monitor import update_server_certificate

        server = find_server(server_id)
        if not server:
            raise HTTPException(404, "Сервер не найден")

        data = body.model_dump(exclude_unset=True)
        if not data:
            raise HTTPException(400, "Нет полей для обновления")

        w = _wizard()

        # port validation
        if "port" in data and data["port"] is not None:
            if w and hasattr(w, "validate_port"):
                ok, port, msg = w.validate_port(str(data["port"]))
                if not ok:
                    raise HTTPException(400, msg)
                data["port"] = port
            elif not (1 <= int(data["port"]) <= 65535):
                raise HTTPException(400, "Порт 1–65535")

        if "auth_type" in data and data["auth_type"] not in ("password", "key"):
            raise HTTPException(400, "auth_type: password|key")

        # group change → certificate_check
        if "group" in data and data["group"]:
            ssl_on = is_group_ssl_enabled(data["group"])
            if "certificate_check" not in data:
                data["certificate_check"] = ssl_on
            if ssl_on and not data.get("ssl_host") and not server.get("ssl_host"):
                # если host не IP — можно поставить host
                host = data.get("host") or server.get("host") or ""
                try:
                    import ipaddress
                    ipaddress.ip_address(host)
                except ValueError:
                    data.setdefault("ssl_host", host)

        servers = load_servers()
        target = None
        for s in servers:
            if s["id"] == server_id:
                target = s
                break
        if not target:
            raise HTTPException(404, "Сервер не найден")

        for k, v in data.items():
            if v is None and k in ("password", "key_path", "ssl_host"):
                # явный сброс только если передали пустую строку — None = не трогать already excluded
                continue
            if k == "password" and v == "":
                target.pop("password", None)
                continue
            if k == "key_path" and v == "":
                target.pop("key_path", None)
                continue
            target[k] = v

        # В password-режиме key_path не нужен. В key-режиме password хранит
        # отдельный sudo-пароль для non-root и поэтому должен сохраняться.
        if target.get("auth_type") == "password":
            target.pop("key_path", None)

        save_servers(servers)

        # SSL refresh
        if target.get("certificate_check") and target.get("ssl_host") or (
            target.get("certificate_check") and target.get("host")
        ):
            try:
                await asyncio.to_thread(update_server_certificate, target)
            except Exception as e:
                print(f"[WEB] ssl refresh: {e}", flush=True)

        return {"ok": True, "server": {k: target.get(k) for k in (
            "id", "name", "group", "host", "port", "user", "auth_type",
            "certificate_check", "ssl_host", "key_path",
        )}}
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.post("/api/servers")
async def api_server_create(body: ServerCreate):
    try:
        from core.storage import load_servers, save_servers, is_group_ssl_enabled
        import secrets

        if body.auth_type not in ("password", "key"):
            raise HTTPException(400, "auth_type: password|key")
        if body.auth_type == "password" and not body.password:
            raise HTTPException(400, "Нужен password")
        if body.auth_type == "key" and not body.key_path:
            raise HTTPException(400, "Нужен key_path")
        if not (1 <= body.port <= 65535):
            raise HTTPException(400, "Порт 1–65535")

        # test connection
        if body.test:
            w = _wizard()
            if w and hasattr(w, "test_server_connection"):
                ok, msg = await asyncio.to_thread(
                    w.test_server_connection,
                    body.host, body.port, body.user, body.auth_type,
                    body.password, body.key_path,
                )
                if not ok:
                    raise HTTPException(400, f"SSH: {msg}")
            else:
                from core.ssh import test_connection
                tmp = {
                    "host": body.host, "port": body.port, "user": body.user,
                    "auth_type": body.auth_type,
                }
                if body.password:
                    tmp["password"] = body.password
                if body.key_path:
                    tmp["key_path"] = body.key_path
                ok, msg = await asyncio.to_thread(test_connection, tmp)
                if not ok:
                    raise HTTPException(400, f"SSH: {msg}")

        cert = body.certificate_check
        if cert is None:
            cert = is_group_ssl_enabled(body.group)

        server = {
            "id": secrets.token_hex(4),
            "name": body.name.strip(),
            "group": body.group,
            "host": body.host.strip(),
            "port": body.port,
            "user": body.user.strip(),
            "auth_type": body.auth_type,
            "certificate_check": bool(cert),
        }
        if body.auth_type == "password":
            server["password"] = body.password
        else:
            server["key_path"] = body.key_path
        if body.ssl_host:
            server["ssl_host"] = body.ssl_host.strip()
        elif cert:
            try:
                import ipaddress
                ipaddress.ip_address(body.host)
            except ValueError:
                server["ssl_host"] = body.host.strip()

        servers = load_servers()
        servers.append(server)
        save_servers(servers)

        if server.get("certificate_check"):
            try:
                from core.monitor import update_server_certificate
                await asyncio.to_thread(update_server_certificate, server)
            except Exception as e:
                print(f"[WEB] ssl on create: {e}", flush=True)

        return {"ok": True, "id": server["id"], "server": server}
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.delete("/api/servers/{server_id}")
async def api_server_delete(server_id: str):
    try:
        from core.storage import load_servers, save_servers
        servers = load_servers()
        new = [s for s in servers if s.get("id") != server_id]
        if len(new) == len(servers):
            raise HTTPException(404, "Сервер не найден")
        save_servers(new)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.post("/api/servers/{server_id}/test")
async def api_server_test(server_id: str):
    try:
        from core.storage import find_server
        from core.ssh import test_connection
        server = find_server(server_id)
        if not server:
            raise HTTPException(404, "Сервер не найден")
        ok, msg = await asyncio.to_thread(test_connection, server)
        return {"ok": ok, "message": msg}
    except HTTPException:
        raise
    except Exception as e:
        return err(e)

class TestConnBody(BaseModel):
    host: str
    port: int = 22
    user: str = "root"
    auth_type: str = "password"
    password: Optional[str] = None
    key_path: Optional[str] = None


@router.post("/api/servers/test-connection")
async def api_test_connection(body: TestConnBody):
    """Тест SSH по полям формы (до сохранения)."""
    try:
        from core.ssh import test_connection
        if body.auth_type not in ("password", "key"):
            raise HTTPException(400, "auth_type: password|key")
        if not body.host.strip():
            raise HTTPException(400, "host обязателен")

        tmp = {
            "host": body.host.strip(),
            "port": int(body.port or 22),
            "user": (body.user or "root").strip(),
            "auth_type": body.auth_type,
        }
        if body.auth_type == "password":
            if not body.password:
                raise HTTPException(400, "Укажите пароль для теста")
            tmp["password"] = body.password
        else:
            kp = (body.key_path or "").strip()
            if not kp:
                raise HTTPException(400, "Выберите SSH-ключ")
            key = Path(kp)
            if not key.is_absolute():
                # keys/name или просто name
                cand = Path("keys") / key.name
                if cand.is_file():
                    key = cand.resolve()
                else:
                    key = key.resolve()
            if not key.is_file():
                raise HTTPException(400, f"Файл ключа не найден: {key}")
            tmp["key_path"] = str(key)

        ok, msg = await asyncio.to_thread(test_connection, tmp)
        return {"ok": bool(ok), "message": msg or ("OK" if ok else "Ошибка")}
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


class TestDraftBody(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = None
    user: Optional[str] = None
    auth_type: Optional[str] = None
    password: Optional[str] = None
    key_path: Optional[str] = None


@router.post("/api/servers/{server_id}/test-draft")
async def api_test_draft(server_id: str, body: TestDraftBody):
    """
    Тест SSH по полям формы.
    host/port/user/auth — из формы (если переданы).
    password/key — из формы, иначе из сохранённого сервера.
    """
    try:
        from core.storage import find_server
        from core.ssh import test_connection

        saved = find_server(server_id)
        if not saved:
            raise HTTPException(404, "Сервер не найден")

        host = (body.host if body.host is not None else saved.get("host") or "").strip()
        port = int(body.port if body.port is not None else saved.get("port") or 22)
        user = (body.user if body.user is not None else saved.get("user") or "root").strip()
        auth = body.auth_type or saved.get("auth_type") or "password"

        if not host:
            raise HTTPException(400, "host пуст")
        if auth not in ("password", "key"):
            raise HTTPException(400, "auth_type: password|key")

        tmp = {
            "host": host,
            "port": port,
            "user": user,
            "auth_type": auth,
        }

        if auth == "password":
            pwd = body.password if body.password else saved.get("password")
            if not pwd:
                raise HTTPException(400, "Нет пароля (введите в форму или сохраните на сервере)")
            tmp["password"] = pwd
        else:
            kp = (body.key_path or "").strip() or saved.get("key_path") or ""
            if not kp:
                raise HTTPException(400, "Нет ключа")
            key = Path(kp)
            if not key.is_absolute():
                cand = Path("keys") / key.name
                key = cand.resolve() if cand.is_file() else key.resolve()
            if not key.is_file():
                raise HTTPException(400, f"Ключ не найден: {key}")
            tmp["key_path"] = str(key)

        ok, msg = await asyncio.to_thread(test_connection, tmp)
        return {
            "ok": bool(ok),
            "message": msg or ("OK" if ok else "Ошибка"),
            "tested": {"host": host, "port": port, "user": user, "auth_type": auth},
        }
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


class SshTestBody(BaseModel):
    """Универсальный тест SSH (форма настроек / новый сервер)."""
    server_id: Optional[str] = None  # если есть — пароль/ключ можно взять из сохранённого
    host: str
    port: int = 22
    user: str = "root"
    auth_type: str = "password"
    password: Optional[str] = None
    key_path: Optional[str] = None


@router.post("/api/ssh/test")
async def api_ssh_test(body: SshTestBody):
    """
    Всегда тестирует host:port из body.
    Secrets: из body, иначе из server_id (сохранённый сервер).
    """
    try:
        from core.storage import find_server
        from core.ssh import test_connection

        saved = find_server(body.server_id) if body.server_id else None
        host = body.host.strip()
        port = int(body.port or 22)
        user = (body.user or "root").strip()
        auth = body.auth_type or "password"
        if not host:
            raise HTTPException(400, "host обязателен")
        if auth not in ("password", "key"):
            raise HTTPException(400, "auth_type: password|key")

        tmp = {"host": host, "port": port, "user": user, "auth_type": auth}

        if auth == "password":
            pwd = body.password or (saved.get("password") if saved else None)
            if not pwd:
                raise HTTPException(400, "Нет пароля для теста")
            tmp["password"] = pwd
        else:
            kp = (body.key_path or "").strip() or (saved.get("key_path") if saved else "") or ""
            if not kp:
                raise HTTPException(400, "Нет ключа для теста")
            key = Path(kp)
            if not key.is_absolute():
                cand = Path("keys") / key.name
                key = cand.resolve() if cand.is_file() else key.resolve()
            if not key.is_file():
                raise HTTPException(400, f"Ключ не найден: {key}")
            tmp["key_path"] = str(key)

        ok, msg = await asyncio.to_thread(test_connection, tmp)
        return {
            "ok": bool(ok),
            "message": msg or ("OK" if ok else "Ошибка"),
            "tested": {"host": host, "port": port, "user": user, "auth_type": auth},
        }
    except HTTPException:
        raise
    except Exception as e:
        return err(e)

