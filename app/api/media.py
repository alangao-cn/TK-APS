"""媒体流：商品图。"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

router = APIRouter()


@router.get("/media/images/{name}")
async def media_image(request: Request, name: str):
    cfg = request.app.state.cfg
    root = (Path(cfg.root) / cfg.storage.data_dir / "images").resolve()
    path = (root / name).resolve()
    if not str(path).startswith(str(root)) or not path.exists():
        raise HTTPException(404, "图片不存在")
    return FileResponse(path)
