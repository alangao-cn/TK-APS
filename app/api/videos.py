"""视频：全局库、在线播放、下载、ZIP 打包。"""

import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import models
from .batches import _video_view

router = APIRouter()


def _get(s: Session, video_id: int) -> models.Video:
    row = s.get(models.Video, video_id)
    if not row:
        raise HTTPException(404, f"视频 {video_id} 不存在")
    return row


@router.get("/videos")
async def list_videos(request: Request, batch_id: int | None = None,
                      status: str | None = None, q: str | None = None):
    with Session(request.app.state.engine) as s:
        stmt = select(models.Video).order_by(models.Video.created_at.desc(),
                                             models.Video.version.desc())
        rows = s.exec(stmt).all()
        info = {p.product_id: (p.title, p.batch_id, p.tiktok_url, p.fastmoss_url, p.id)
                for p in s.exec(select(models.Product)).all()}
        out = []
        for r in rows:
            view = _video_view(r)
            title, bid, tk_url, fm_url, row_id = info.get(
                r.product_id, (r.product_id, 0, "", "", None))
            view["product_title"] = title
            view["batch_id"] = bid
            view["product_row_id"] = row_id
            view["tiktok_url"] = tk_url
            view["fastmoss_url"] = fm_url
            if batch_id and bid != batch_id:
                continue
            if status and r.status != status:
                continue
            if q and q.lower() not in title.lower() and q not in r.product_id:
                continue
            out.append(view)
        return {"videos": out}


@router.get("/videos/{video_id}/file")
async def video_file(request: Request, video_id: int):
    with Session(request.app.state.engine) as s:
        row = _get(s, video_id)
    if not row.local_path or not Path(row.local_path).exists():
        raise HTTPException(404, "视频文件不存在（生成失败或被清理）")
    return FileResponse(row.local_path, media_type="video/mp4")


def _download_name(row: models.Video) -> str:
    date = (row.finished_at or row.created_at or "")[:10].replace("-", "")
    return f"{date or 'video'}_{row.product_id}_v{row.version}.mp4"


@router.get("/videos/{video_id}/download")
async def video_download(request: Request, video_id: int):
    with Session(request.app.state.engine) as s:
        row = _get(s, video_id)
    if not row.local_path or not Path(row.local_path).exists():
        raise HTTPException(404, "视频文件不存在（生成失败或被清理）")
    return FileResponse(row.local_path, media_type="video/mp4",
                        filename=_download_name(row))


class ZipBody(BaseModel):
    ids: list[int]


@router.post("/videos/zip")
async def videos_zip(request: Request, body: ZipBody):
    if not body.ids:
        raise HTTPException(400, "没有勾选视频")
    if len(body.ids) > 100:
        raise HTTPException(400, "一次最多打包 100 个")
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp.close()
    included = 0
    with Session(request.app.state.engine) as s:
        with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_STORED) as zf:  # mp4 已压缩
            for vid in body.ids:
                row = s.get(models.Video, vid)
                if not row or not row.local_path or not Path(row.local_path).exists():
                    continue
                zf.write(row.local_path, arcname=_download_name(row))
                included += 1
    if not included:
        raise HTTPException(404, "勾选的视频文件都不存在")
    name = f"tkaps_videos_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
    return FileResponse(tmp.name, media_type="application/zip", filename=name)
