
from __future__ import annotations
import io
import os
import re
import zipfile
from datetime import datetime
from pathlib import Path
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from ..deps import err

router = APIRouter(tags=["scripts"])


def _script_meta(content: str) -> dict:
    meta = {"description": "", "author": "", "version": ""}
    for line in content.splitlines()[:60]:
        s = line.strip()
        if s.startswith("# BOT_INFO "):
            meta["description"] = s[11:].strip()
        elif s.startswith("# BOT_DESC "):
            meta["description"] = s[11:].strip()
        elif s.startswith("# BOT_AUTHOR "):
            meta["author"] = s[13:].strip()
        elif s.startswith("# BOT_VERSION "):
            meta["version"] = s[14:].strip()
    return meta


@router.get("/api/scripts")
async def api_scripts():
    try:
        from core.script_utils import load_scripts, get_script_info, get_script_params, read_script
        out = []
        for name in load_scripts():
            info = get_script_info(name) or {}
            params = get_script_params(name)
            content = read_script(name) or ""
            meta = _script_meta(content)
            mtime = (Path("scripts") / name).stat().st_mtime
            out.append({
                "name": name,
                "size": info.get("size"),
                "lines": info.get("lines"),
                "mtime": int(mtime),
                "modified": datetime.fromtimestamp(mtime).astimezone().isoformat(timespec="minutes"),
                "description": meta["description"],
                "author": meta["author"],
                "version": meta["version"],
                "params": [
                    {
                        "name": p["name"],
                        "type": p["type"],
                        "label": p.get("label"),
                        "condition": p.get("condition"),
                        "options": [
                            {"value": o["value"], "label": o.get("label", o["value"])}
                            for o in p.get("options", [])
                        ],
                    }
                    for p in params
                ],
            })
        return {"scripts": out, "cwd": os.getcwd()}
    except Exception as e:
        return err(e)


class ScriptDownloadBody(BaseModel):
    names: list[str]


class ScriptUploadCheckBody(BaseModel):
    names: list[str]


def _safe_script_name(filename: str) -> str:
    return re.sub(r"[^\w.\-]", "_", Path(filename).name)[:128]


@router.post("/api/scripts/upload-check")
async def api_scripts_upload_check(body: ScriptUploadCheckBody):
    """Проверить всю выбранную пачку до загрузки и вернуть канонические имена."""
    if not body.names:
        raise HTTPException(400, "Не выбраны файлы")
    if len(body.names) > 200:
        raise HTTPException(400, "Слишком много скриптов")

    scripts_dir = Path("scripts")
    existing = {path.name for path in scripts_dir.iterdir()} if scripts_dir.exists() else set()
    reserved = set(existing)
    result = []
    for original in body.names:
        safe = _safe_script_name(original)
        if not safe.lower().endswith(".sh"):
            result.append({"original": original, "name": safe, "exists": False, "error": "Нужен .sh"})
            continue
        duplicate = safe in reserved
        result.append({"original": original, "name": safe, "exists": duplicate, "error": None})
        reserved.add(safe)
    return {"files": result}


def _scripts_archive_response(selected_names: list[str]) -> Response:
    """Собрать ZIP только из явно выбранных файлов библиотеки scripts/."""
    names = list(dict.fromkeys(selected_names or []))
    if len(names) < 2:
        raise HTTPException(400, "Для ZIP выберите минимум два скрипта")
    if len(names) > 200:
        raise HTTPException(400, "Слишком много скриптов")

    base = Path("scripts").resolve()
    files: list[tuple[str, Path]] = []
    for name in names:
        if Path(name).name != name or not name.endswith(".sh"):
            raise HTTPException(400, f"Некорректное имя: {name}")
        path = (base / name).resolve()
        if path.parent != base or not path.is_file():
            raise HTTPException(404, f"Скрипт не найден: {name}")
        files.append((name, path))

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, path in files:
            zf.write(path, arcname=name)
    return Response(
        content=archive.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="scripts.zip"'},
    )


@router.get("/api/scripts-archive.zip")
async def api_scripts_download_get(names: list[str] = Query(...)):
    """GET-вариант скачивания, совместимый с прокси без POST для файлов."""
    return _scripts_archive_response(names)


@router.post("/api/scripts/download")
async def api_scripts_download(body: ScriptDownloadBody):
    """Совместимый POST-вариант для старых клиентов."""
    return _scripts_archive_response(body.names)


@router.get("/api/scripts/{name}")
async def api_script_content(name: str):
    try:
        from core.script_utils import read_script, get_script_info, get_script_params
        # защита от path traversal
        safe = Path(name).name
        if safe != name or not name.endswith(".sh"):
            raise HTTPException(400, "Некорректное имя")
        content = read_script(safe)
        if content is None:
            raise HTTPException(404, "Скрипт не найден")
        info = get_script_info(safe) or {}
        meta = _script_meta(content)
        return {
            "name": safe,
            "content": content,
            "lines": info.get("lines"),
            "size": info.get("size"),
            **meta,
            "params": get_script_params(safe),
        }
    except HTTPException:
        raise
    except Exception as e:
        return err(e)


@router.post("/api/upload/script")
async def api_upload_script(file: UploadFile = File(...)):
    try:
        fname = file.filename or "upload.sh"
        if not fname.lower().endswith(".sh"):
            raise HTTPException(400, "Нужен .sh")
        data = await file.read()
        if len(data) > 1024 * 1024:
            raise HTTPException(400, "Слишком большой")
        safe = _safe_script_name(fname)
        dest = Path("scripts")
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / safe
        try:
            with target.open("xb") as output:
                output.write(data)
        except FileExistsError:
            raise HTTPException(409, f"Скрипт «{safe}» уже существует")
        os.chmod(target, 0o755)
        return {"ok": True, "name": safe}
    except HTTPException:
        raise
    except Exception as e:
        return err(e)
