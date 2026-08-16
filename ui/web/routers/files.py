
from __future__ import annotations
import os
import re
import subprocess
from pathlib import Path
from core.integrator import StepError
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
    ".txt", ".md", ".toml", ".xml", ".svg", ".properties", ".service",
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
async def api_files(
    root: str = Query("scripts"),
    project: str = Query(""),
    directory: str = Query(""),
):
    """Список файлов; Docker отдаёт проекты либо один текущий каталог."""
    try:
        base = _root_path(root)

        if root == "docker":
            from services.docker.impl import compose_store
            if not project:
                return {
                    "root": root,
                    "path": str(base),
                    "level": "projects",
                    "items": compose_store.list_library_projects(),
                }

            stack_name = compose_store.validate_stack_name(project)
            rel_dir = ""
            if directory:
                rel_dir = compose_store.safe_relative_path(directory).as_posix()
            items = compose_store.list_project_directory(stack_name, rel_dir)
            for item in items:
                path = Path(item["path"])
                item["editable"] = (
                    not item["is_dir"]
                    and _is_texty(path)
                    and int(item.get("size") or 0) <= MAX_EDIT_SIZE
                )
            return {
                "root": root,
                "path": str(compose_store.stack_dir(stack_name)),
                "level": "files",
                "project": stack_name,
                "directory": rel_dir,
                "items": items,
            }

        # scripts / keys: прежний плоский список.
        items = []
        for f in sorted(base.iterdir(), key=lambda x: (not x.is_file(), x.name.lower())):
            if f.name.startswith("."):
                continue
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
    except StepError as e:
        detail = getattr(e, "detail", "") or str(e)
        title = getattr(e, "title", "") or "Ошибка"
        raise HTTPException(400, f"{title}: {detail}")
    except Exception as e:
        return err(e)


def _resolve_target(root: str, name: str, project: str = "") -> Path:
    """Путь к файлу с учётом двухуровневой модели docker-root."""
    base = _root_path(root)
    if root == "docker":
        if not project:
            raise HTTPException(400, "Не указан проект")
        from services.docker.impl import compose_store
        try:
            stack_name = compose_store.validate_stack_name(project)
        except StepError as e:
            detail = getattr(e, "detail", "") or str(e)
            title = getattr(e, "title", "") or "Ошибка"
            raise HTTPException(400, f"{title}: {detail}")
        pdir = _safe_rel(base, stack_name)
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
            try:
                stack_name = compose_store.validate_stack_name(body.project)
            except StepError as e:
                detail = getattr(e, "detail", "") or str(e)
                title = getattr(e, "title", "") or "Ошибка"
                raise HTTPException(400, f"{title}: {detail}")
            pdir = _safe_rel(base, stack_name)
            rel = _safe_rel(pdir, body.name)
            try:
                info = compose_store.save_project_file(
                    stack_name, rel.relative_to(pdir).as_posix(),
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

        # Объекты Compose-библиотеки удаляем через слой хранилища: он сам
        # проверяет путь/симлинки и защищает фактический основной Compose-файл.
        if root == "docker":
            if not project:
                raise HTTPException(400, "Не указан проект")
            from core.integrator import StepError
            from services.docker.impl import compose_store
            try:
                stack_name = compose_store.validate_stack_name(project)
                removed = compose_store.delete_project_entry(stack_name, name)
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


class DockerProjectBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=63)


class DockerObjectBody(BaseModel):
    project: str = Field(..., min_length=1, max_length=63)
    directory: str = ""
    name: str = Field(..., min_length=1, max_length=255)
    kind: str = ""


def _docker_object_path(directory: str, name: str) -> str:
    """Собрать путь из текущей папки и одного имени без basename-сокращений."""
    raw_name = str(name or "").strip()
    if not raw_name or raw_name in (".", "..") or "/" in raw_name or "\\" in raw_name:
        raise HTTPException(400, "Имя должно быть одним файлом или папкой")
    from services.docker.impl import compose_store
    raw = f"{directory.rstrip('/')}/{raw_name}" if directory else raw_name
    try:
        return compose_store.safe_relative_path(raw).as_posix()
    except StepError as e:
        raise HTTPException(400, f"{getattr(e, 'title', 'Ошибка')}: {getattr(e, 'detail', str(e))}")


def _docker_step_error(e: StepError) -> HTTPException:
    return HTTPException(
        400,
        f"{getattr(e, 'title', '') or 'Ошибка'}: {getattr(e, 'detail', '') or str(e)}",
    )


@router.post("/api/files/docker/projects")
async def api_docker_project_create(body: DockerProjectBody):
    """Создать пустой проект только в существующей локальной библиотеке."""
    from services.docker.impl import compose_store
    try:
        return {"ok": True, "project": compose_store.create_empty_project(body.name)}
    except FileExistsError as e:
        raise HTTPException(409, str(e))
    except StepError as e:
        raise _docker_step_error(e)


@router.post("/api/files/docker/projects/upload")
async def api_docker_project_upload(
    file: UploadFile = File(...),
    name: str = Query(""),
):
    """Безопасно импортировать новый ZIP-проект без merge/overwrite."""
    from services.docker.impl import compose_store
    filename = file.filename or "project.zip"
    if Path(filename).suffix.lower() != ".zip":
        raise HTTPException(400, "Поддерживаются только ZIP-архивы")
    data = await file.read()
    if len(data) > compose_store.MAX_PROJECT_TOTAL_SIZE:
        raise HTTPException(400, "ZIP-архив слишком большой")
    try:
        chosen = (
            compose_store.validate_stack_name(name)
            if str(name or "").strip()
            else compose_store.suggest_zip_stack_name(data, filename)
        )
        project = compose_store.import_zip_new(data, filename, chosen)
        return {"ok": True, "project": project}
    except FileExistsError as e:
        raise HTTPException(409, {"message": str(e), "name": chosen})
    except StepError as e:
        raise _docker_step_error(e)


@router.post("/api/files/docker/directories")
async def api_docker_directory_create(body: DockerObjectBody):
    from services.docker.impl import compose_store
    rel = _docker_object_path(body.directory, body.name)
    try:
        info = compose_store.create_project_directory(body.project, rel)
        return {"ok": True, "directory": info}
    except FileExistsError as e:
        raise HTTPException(409, str(e))
    except StepError as e:
        raise _docker_step_error(e)


@router.post("/api/files/docker/files")
async def api_docker_file_create(body: DockerObjectBody):
    """Создать пустой YAML/ENV и не заменять существующий объект."""
    from services.docker.impl import compose_store
    kind = str(body.kind or "").strip().lower()
    name = str(body.name or "").strip()
    suffix = Path(name).suffix.lower()
    if kind == "yaml":
        if not suffix:
            name += ".yml"
        elif suffix not in (".yml", ".yaml"):
            raise HTTPException(400, "Для YAML используйте расширение .yml или .yaml")
    elif kind == "env":
        if name != ".env" and suffix != ".env":
            if suffix:
                raise HTTPException(400, "Для ENV используйте имя .env или расширение .env")
            name += ".env"
    else:
        raise HTTPException(400, "Тип файла: yaml или env")
    rel = _docker_object_path(body.directory, name)
    try:
        info = compose_store.create_project_file(body.project, rel, b"")
        return {"ok": True, "file": info}
    except FileExistsError as e:
        raise HTTPException(409, str(e))
    except StepError as e:
        raise _docker_step_error(e)


@router.post("/api/files/docker/upload")
async def api_docker_file_upload(
    project: str = Query(...),
    directory: str = Query(""),
    file: UploadFile = File(...),
):
    """Загрузить один новый файл в текущую папку проекта без overwrite."""
    from services.docker.impl import compose_store
    raw_name = file.filename or ""
    rel = _docker_object_path(directory, raw_name)
    data = await file.read()
    try:
        info = compose_store.create_project_file(project, rel, data)
        return {"ok": True, "file": info}
    except FileExistsError as e:
        raise HTTPException(409, str(e))
    except (UnicodeDecodeError, StepError) as e:
        if isinstance(e, StepError):
            raise _docker_step_error(e)
        raise HTTPException(400, "Compose-файл должен быть в кодировке UTF-8")


@router.post("/api/files/upload")
async def api_files_upload(root: str = Query("scripts"), file: UploadFile = File(...)):
    try:
        if root == "docker":
            raise HTTPException(400, "Для Docker используйте загрузку внутри проекта")
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
