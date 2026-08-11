
from __future__ import annotations
import os
import re
import subprocess
from pathlib import Path
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from ..deps import err

router = APIRouter(tags=["files"])

FILE_ROOTS = {
    "scripts": Path("scripts"),
    "keys": Path("keys"),
    # Библиотека Compose-проектов Bot4VPS: здесь объект — КАТАЛОГ проекта,
    # внутри compose-файл, .env и любые вложенные файлы. Поэтому этот root
    # (в отличие от scripts/keys) работает с двумя уровнями и вложенными путями.
    "docker": Path("data/services/docker/compose"),
}

# Где разрешено редактирование. keys исключены сознательно: приватный ключ
# правят не в браузере, а пересоздают.
EDITABLE_ROOTS = {"scripts", "docker"}

# Расширения, которые открываем в редакторе как текст. Файл без расширения
# (например .env) проверяется отдельно — см. _is_texty.
TEXT_SUFFIXES = {
    ".sh", ".yml", ".yaml", ".env", ".conf", ".cfg", ".ini", ".json",
    ".txt", ".md", ".toml", ".properties", ".service",
}
TEXT_NAMES = {".env", "Dockerfile", "Makefile"}

MAX_EDIT_SIZE = 512 * 1024


def _root_path(root: str) -> Path:
    if root not in FILE_ROOTS:
        raise HTTPException(400, "root: " + "|".join(FILE_ROOTS))
    p = FILE_ROOTS[root].resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_name(name: str) -> str:
    name = Path(name).name
    if not name or name in (".", ".."):
        raise HTTPException(400, "Некорректное имя")
    return name


def _safe_rel(base: Path, rel: str) -> Path:
    """Разрешить относительный путь ВНУТРИ base (для вложенных файлов проекта).

    Отклоняет абсолютные пути, «..», имена дисков. Итог дополнительно
    проверяется на принадлежность base — двойная защита от traversal.
    """
    raw = str(rel or "").strip().replace("\\", "/")
    if not raw:
        raise HTTPException(400, "Пустой путь")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
        raise HTTPException(400, "Абсолютные пути запрещены")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise HTTPException(400, "Недопустимый путь")
    target = (base / Path(*parts)).resolve()
    if target != base and base not in target.parents:
        raise HTTPException(400, "Путь вне разрешённого каталога")
    return target


def _is_texty(path: Path) -> bool:
    """Можно ли открыть файл в редакторе как текст."""
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in TEXT_NAMES


@router.get("/api/files")
async def api_files(root: str = Query("scripts"), project: str = Query("")):
    """Список файлов.

    scripts/keys — плоский список файлов каталога.
    docker — два уровня: без project отдаём проекты (каталоги), с project —
    все файлы внутри него, включая вложенные (config/nginx/site.conf).
    """
    try:
        base = _root_path(root)

        # --- docker: уровень 1 — список проектов ---
        if root == "docker" and not project:
            projects = []
            for d in sorted(base.iterdir(), key=lambda x: x.name.lower()):
                if not d.is_dir() or d.name.startswith("."):
                    continue
                files = [f for f in d.rglob("*") if f.is_file()]
                total = 0
                newest = 0
                for f in files:
                    try:
                        st = f.stat()
                        total += st.st_size
                        newest = max(newest, int(st.st_mtime))
                    except OSError:
                        pass
                projects.append({
                    "name": d.name,
                    "is_dir": True,
                    "files": len(files),
                    "size": total,
                    "mtime": newest,
                })
            return {"root": root, "path": str(base), "level": "projects", "items": projects}

        # --- docker: уровень 2 — файлы конкретного проекта (рекурсивно) ---
        if root == "docker":
            pdir = _safe_rel(base, _safe_name(project))
            if not pdir.is_dir():
                raise HTTPException(404, "Проект не найден")
            items = []
            for f in sorted(pdir.rglob("*"), key=lambda x: x.as_posix().lower()):
                if not f.is_file():
                    continue
                st = f.stat()
                items.append({
                    "name": f.relative_to(pdir).as_posix(),
                    "is_dir": False,
                    "size": st.st_size,
                    "mtime": int(st.st_mtime),
                    "editable": _is_texty(f) and st.st_size <= MAX_EDIT_SIZE,
                })
            return {
                "root": root, "path": str(pdir), "level": "files",
                "project": pdir.name, "items": items,
            }

        # --- scripts / keys: как было ---
        items = []
        for f in sorted(base.iterdir(), key=lambda x: (not x.is_file(), x.name.lower())):
            if f.name.startswith("."):
                continue
            # не показываем публичные ключи
            if root == "keys" and f.name.endswith(".pub"):
                continue
            if not f.is_file():
                continue
            st = f.stat()
            items.append({
                "name": f.name,
                "is_dir": False,
                "size": st.st_size,
                "mtime": int(st.st_mtime),
                "editable": (
                    root in EDITABLE_ROOTS and _is_texty(f) and st.st_size <= MAX_EDIT_SIZE
                ),
            })
        return {"root": root, "path": str(base), "level": "files", "items": items}
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


def _resolve_target(root: str, name: str, project: str = "") -> Path:
    """Путь к файлу с учётом двухуровневой модели docker-root."""
    base = _root_path(root)
    if root == "docker":
        if not project:
            raise HTTPException(400, "Не указан проект")
        pdir = _safe_rel(base, _safe_name(project))
        return _safe_rel(pdir, name)
    fp = (base / _safe_name(name)).resolve()
    if not str(fp).startswith(str(base)):
        raise HTTPException(400, "Путь вне разрешённого каталога")
    return fp


@router.get("/api/files/download")
async def api_files_download(root: str, name: str, project: str = Query("")):
    try:
        fp = _resolve_target(root, name, project)
        if not fp.is_file():
            raise HTTPException(404, "Файл не найден")
        return FileResponse(fp, filename=fp.name)
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.get("/api/files/read")
async def api_files_read(root: str, name: str, project: str = Query("")):
    """Содержимое текстового файла для редактора."""
    try:
        fp = _resolve_target(root, name, project)
        if not fp.is_file():
            raise HTTPException(404, "Файл не найден")
        if fp.stat().st_size > MAX_EDIT_SIZE:
            raise HTTPException(
                400, f"Файл больше {MAX_EDIT_SIZE // 1024} КБ — откройте его локально"
            )
        try:
            content = fp.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise HTTPException(400, "Файл не является текстовым (UTF-8)")
        return {
            "root": root, "project": project, "name": name,
            "content": content, "editable": root in EDITABLE_ROOTS,
        }
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


class FileWriteBody(BaseModel):
    root: str
    name: str
    content: str
    project: str = ""


@router.post("/api/files/write")
async def api_files_write(body: FileWriteBody):
    """Сохранить текстовый файл.

    Для docker-root запись идёт через compose_store: он валидирует Compose-файл
    и пишет атомарно, поэтому битый YAML не портит рабочий проект. Для scripts
    пишем напрямую, сохраняя бит исполнения.
    """
    try:
        if body.root not in EDITABLE_ROOTS:
            raise HTTPException(403, f"Редактирование «{body.root}» запрещено")
        base = _root_path(body.root)

        # --- Compose-проекты: через сервисный слой ---
        if body.root == "docker":
            if not body.project:
                raise HTTPException(400, "Не указан проект")
            from core.integrator import StepError
            from services.docker.impl import compose_store
            rel = _safe_rel(_safe_rel(base, _safe_name(body.project)), body.name)
            pdir = _safe_rel(base, _safe_name(body.project))
            try:
                info = compose_store.save_project_file(
                    pdir.name, rel.relative_to(pdir).as_posix(),
                    body.content.encode("utf-8"),
                )
            except StepError as e:
                detail = getattr(e, "detail", "") or str(e)
                title = getattr(e, "title", "") or "Ошибка"
                raise HTTPException(400, f"{title}: {detail}")
            return {"ok": True, "file": info}

        # --- scripts: прямая запись с сохранением прав ---
        fp = _resolve_target(body.root, body.name)
        if not fp.is_file():
            raise HTTPException(404, "Файл не найден")
        text = body.content.replace("\r\n", "\n").replace("\r", "\n")
        if not text.endswith("\n"):
            text += "\n"
        mode = fp.stat().st_mode
        tmp = fp.with_suffix(fp.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, fp)
        os.chmod(fp, mode)   # .sh остаётся исполняемым
        return {"ok": True, "file": {"name": fp.name, "size": len(text.encode())}}
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.delete("/api/files")
async def api_files_delete(root: str, name: str, project: str = Query("")):
    try:
        base = _root_path(root)

        # Compose-файлы удаляем через сервисный слой: он не даст снести
        # основной compose-файл (без него проект перестанет быть проектом).
        if root == "docker":
            if not project:
                raise HTTPException(400, "Не указан проект")
            from core.integrator import StepError
            from services.docker.impl import compose_store
            pdir = _safe_rel(base, _safe_name(project))
            rel = _safe_rel(pdir, name)
            try:
                removed = compose_store.delete_project_file(
                    pdir.name, rel.relative_to(pdir).as_posix()
                )
            except StepError as e:
                detail = getattr(e, "detail", "") or str(e)
                title = getattr(e, "title", "") or "Ошибка"
                raise HTTPException(400, f"{title}: {detail}")
            return {"ok": True, "removed": removed}

        safe = _safe_name(name)
        fp = (base / safe).resolve()
        if not str(fp).startswith(str(base)) or not fp.is_file():
            raise HTTPException(404, "Файл не найден")
        fp.unlink()
        # удалить .pub пару если есть
        if root == "keys":
            pub = (base / (safe + ".pub")).resolve()
            if str(pub).startswith(str(base)) and pub.is_file():
                pub.unlink(missing_ok=True)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.post("/api/files/upload")
async def api_files_upload(root: str = Query("scripts"), file: UploadFile = File(...)):
    try:
        base = _root_path(root)
        fname = _safe_name(file.filename or "file")
        data = await file.read()
        if len(data) > 5 * 1024 * 1024:
            raise HTTPException(400, "Макс 5 МБ")
        (base / fname).write_bytes(data)
        if fname.endswith(".sh"):
            os.chmod(base / fname, 0o755)
        return {"ok": True, "name": fname}
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


class ScriptCreateBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)


# Имя скрипта: только в корне scripts/, без вложенных каталогов.
SCRIPT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@router.post("/api/files/create")
async def api_files_create(body: ScriptCreateBody):
    """Создать пустой скрипт в scripts/ и вернуть заготовку для редактора.

    Только корень scripts/ — вложенные пути и traversal отклоняются. Файл сразу
    получает 0755, как и загруженные .sh: иначе созданный скрипт нельзя будет
    выполнить.
    """
    try:
        name = (body.name or "").strip()
        if "/" in name or "\\" in name:
            raise HTTPException(400, "Вложенные каталоги не поддерживаются")
        if not SCRIPT_NAME_RE.match(name):
            raise HTTPException(
                400,
                "Имя: латинские буквы, цифры, точка, дефис, подчёркивание "
                "(например backup.sh)",
            )
        if not name.endswith(".sh"):
            name += ".sh"
        # ещё раз через _safe_name: страховка от «.» и «..»
        name = _safe_name(name)

        base = _root_path("scripts")
        dest = (base / name).resolve()
        if dest.parent != base:
            raise HTTPException(400, "Путь вне каталога scripts")
        if dest.exists():
            raise HTTPException(400, f"Файл «{name}» уже существует")

        template = "#!/bin/bash\n\n"
        dest.write_text(template, encoding="utf-8", newline="\n")
        os.chmod(dest, 0o755)
        return {"ok": True, "name": name, "content": template}
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


class KeyCreateBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)


@router.post("/api/keys/create")
async def api_keys_create(body: KeyCreateBody):
    """Создать SSH-ключ (ed25519). Использует core, если есть, иначе ssh-keygen."""
    try:
        name = re.sub(r"[^\w.\-]", "_", body.name.strip())[:64]
        if not name:
            raise HTTPException(400, "Пустое имя")
        keys = Path("keys")
        keys.mkdir(parents=True, exist_ok=True)
        dest = keys / name
        if dest.exists():
            raise HTTPException(400, "Ключ уже существует")

        # попытка через core
        created = False
        for mod_name, fn_name in (
            ("core.auth", "generate_key"),
            ("core.auth", "create_key"),
            ("core.keys", "generate_key"),
            ("core.keys", "create_ssh_key"),
        ):
            try:
                import importlib
                mod = importlib.import_module(mod_name)
                fn = getattr(mod, fn_name, None)
                if callable(fn):
                    fn(name)
                    created = True
                    break
            except Exception:
                continue

        if not created:
            subprocess.run(
                [
                    "ssh-keygen", "-t", "ed25519", "-f", str(dest),
                    "-N", "", "-C", f"bot4vps-{name}",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            os.chmod(dest, 0o600)

        return {"ok": True, "name": name}
    except HTTPException:
        raise
    except subprocess.CalledProcessError as e:
        return err(RuntimeError(e.stderr or str(e)))
    except Exception as e:
        return err(e)


@router.get("/api/keys/view")
async def api_keys_view(name: str):
    """Просмотр содержимого приватного ключа (только keys/)."""
    try:
        base = _root_path("keys")
        safe = _safe_name(name)
        if safe.endswith(".pub"):
            raise HTTPException(400, "pub не показываем")
        fp = (base / safe).resolve()
        if not str(fp).startswith(str(base)) or not fp.is_file():
            raise HTTPException(404, "Ключ не найден")
        content = fp.read_text(encoding="utf-8", errors="replace")
        pub = base / (safe + ".pub")
        pub_content = pub.read_text(encoding="utf-8", errors="replace") if pub.is_file() else None
        return {
            "name": safe,
            "content": content,
            "public": pub_content,
            "size": fp.stat().st_size,
        }
    except HTTPException:
        raise
    except Exception as e:
        return err(e)
