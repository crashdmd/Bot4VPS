
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
}

def _root_path(root: str) -> Path:
    if root not in FILE_ROOTS:
        raise HTTPException(400, "root: scripts|keys")
    p = FILE_ROOTS[root].resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p

def _safe_name(name: str) -> str:
    name = Path(name).name
    if not name or name in (".", ".."):
        raise HTTPException(400, "Некорректное имя")
    return name


@router.get("/api/files")
async def api_files(root: str = Query("scripts")):
    try:
        base = _root_path(root)
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
            })
        return {"root": root, "path": str(base), "items": items}
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.get("/api/files/download")
async def api_files_download(root: str, name: str):
    try:
        base = _root_path(root)
        fp = (base / _safe_name(name)).resolve()
        if not str(fp).startswith(str(base)) or not fp.is_file():
            raise HTTPException(404, "Файл не найден")
        return FileResponse(fp, filename=fp.name)
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.delete("/api/files")
async def api_files_delete(root: str, name: str):
    try:
        base = _root_path(root)
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
