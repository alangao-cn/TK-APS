"""脚本：编辑（双写文件）、生成视频。"""

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session

from .. import models, sync
from ..web import jobs, pipeline, store

router = APIRouter()


def _get(s: Session, script_id: int) -> models.Script:
    row = s.get(models.Script, script_id)
    if not row:
        raise HTTPException(404, f"脚本 {script_id} 不存在")
    return row


class PromptBody(BaseModel):
    video_prompt: str


@router.put("/scripts/{script_id}")
async def edit_script(request: Request, script_id: int, body: PromptBody):
    prompt = body.video_prompt.strip()
    if not prompt:
        raise HTTPException(400, "提示词为空")
    cfg = request.app.state.cfg
    engine = request.app.state.engine
    with Session(engine) as s:
        row = _get(s, script_id)
        if row.status != "ok":
            raise HTTPException(400, "该版本解析失败，没有可编辑的提示词")
        pid, version = row.product_id, row.version
        # 双写文件（script_v{N}.json + script_latest.md），保持 CLI/留底一致
        store.save_script_edit(cfg, pid, version, prompt)
        row.video_prompt = prompt
        row.edited = True
        row.updated_at = datetime.now().isoformat(timespec="seconds")
        s.add(row)
        s.commit()
    return {"ok": True, "product_id": pid, "version": version}


class GenVideoBody(BaseModel):
    model: str | None = None
    resolution: str | None = None


@router.get("/video/options")
async def video_options(request: Request):
    """生成视频弹窗的选项：模型目录（含各自时长范围/分辨率）+ 默认值。"""
    cfg = request.app.state.cfg
    return {
        "models": getattr(cfg.video, "models", None) or [],
        "default_model": cfg.video.model,
        "default_resolution": cfg.video.resolution,
        "default_duration": int(cfg.video.duration),   # 脚本没给 <seconds> 时的回退秒数
    }


@router.post("/scripts/{script_id}/gen-video")
async def gen_video(request: Request, script_id: int, body: GenVideoBody):
    cfg = request.app.state.cfg
    catalog = {m["name"]: m for m in (getattr(cfg.video, "models", None) or [])
               if isinstance(m, dict) and m.get("name")}
    if body.model and body.model not in catalog:
        raise HTTPException(400, f"未知模型 {body.model}")
    if body.resolution and body.model and body.resolution not in catalog[body.model].get("resolutions", []):
        raise HTTPException(400, f"模型 {body.model} 不支持分辨率 {body.resolution}")
    with Session(request.app.state.engine) as s:
        row = _get(s, script_id)
        if row.status != "ok":
            raise HTTPException(400, "该版本解析失败，不能用它生成视频")
        pid, version = row.product_id, row.version
    if jobs.is_running(f"gen-videos:{pid}"):
        raise HTTPException(409, f"商品 {pid} 已有视频任务在跑，等它结束再试")
    jobs.start_job(
        "gen-videos",
        f"生成视频：商品 {pid}（脚本 v{version}，{body.model or cfg.video.model}）",
        lambda job: pipeline.run_gen_video(request, job, pid, version, None,
                                           body.model, body.resolution),
        key=f"gen-videos:{pid}")
    return {"ok": True, "job_started": True}
