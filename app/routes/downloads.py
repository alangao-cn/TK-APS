"""媒体与下载：商品图、视频在线播放、单个下载、勾选打包 ZIP。"""

import json
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse

from ..web import store

router = APIRouter()


def _safe_child(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if not str(path).startswith(str(root.resolve())):
        raise HTTPException(400, "非法路径")
    return path


@router.get("/media/images/{name}")
async def media_image(request: Request, name: str):
    cfg = request.app.state.cfg
    path = _safe_child(cfg.root / cfg.storage.data_dir / "images", name)
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path)


@router.get("/media/videos/{pid}/{name}")
async def media_video(request: Request, pid: str, name: str):
    cfg = request.app.state.cfg
    path = _safe_child(cfg.root / cfg.storage.data_dir / "videos" / pid, name)
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="video/mp4")


def _load_record(cfg, pid: str, version: int) -> dict:
    f = cfg.root / cfg.storage.data_dir / "videos" / pid / f"video_v{version}.json"
    if not f.exists():
        raise HTTPException(404, f"找不到 {f.name}")
    rec = json.loads(f.read_text(encoding="utf-8"))
    src = Path(rec["file"]) if rec.get("file") else None
    if not src or not src.exists():
        raise HTTPException(404, "视频文件不存在（可能生成失败或被清理）")
    return rec


@router.get("/download/video/{pid}/{version}")
async def download_video(request: Request, pid: str, version: int):
    cfg = request.app.state.cfg
    rec = _load_record(cfg, pid, version)
    return FileResponse(rec["file"], media_type="video/mp4",
                        filename=store.video_download_name(rec))


@router.post("/videos/zip")
async def download_zip(request: Request, checked: list[str] = Form(default=[])):
    cfg = request.app.state.cfg
    picked = []
    for item in checked:
        try:
            pid, ver = item.rsplit(":", 1)
            picked.append((pid, int(ver)))
        except ValueError:
            continue
    if not picked:
        raise HTTPException(400, "没有勾选任何视频")
    if len(picked) > 100:
        raise HTTPException(400, "一次最多打包 100 个")

    # 打进临时文件再返回（视频单个约 5MB，量级可控，不搞流式 ZIP）
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp.close()
    included = 0
    with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_STORED) as zf:  # mp4 已压缩，STORED 即可
        for pid, ver in picked:
            try:
                rec = _load_record(cfg, pid, ver)
            except HTTPException:
                continue
            zf.write(rec["file"], arcname=store.video_download_name(rec))
            included += 1
    if not included:
        raise HTTPException(404, "勾选的视频文件都不存在")
    name = f"tkaps_videos_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
    return FileResponse(tmp.name, media_type="application/zip", filename=name)
