
from __future__ import annotations
import os
import re
from pathlib import Path
from fastapi import APIRouter, File, HTTPException, UploadFile
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
            out.append({
                "name": name,
                "size": info.get("size"),
                "lines": info.get("lines"),
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
        safe = re.sub(r"[^\w.\-]", "_", Path(fname).name)[:128]
        dest = Path("scripts")
        dest.mkdir(parents=True, exist_ok=True)
        (dest / safe).write_bytes(data)
        os.chmod(dest / safe, 0o755)
        return {"ok": True, "name": safe}
    except HTTPException:
        raise
    except Exception as e:
        return err(e)
