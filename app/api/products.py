"""商品：详情（脚本/视频一条龙）、单件生成脚本、确认开关。"""

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import models
from ..web import jobs, pipeline
from .batches import _product_view

router = APIRouter()


def _get(s: Session, row_id: int) -> models.Product:
    p = s.get(models.Product, row_id)
    if not p:
        raise HTTPException(404, f"商品行 {row_id} 不存在")
    return p


def _batch_ts(request, batch_id: int) -> str:
    with Session(request.app.state.engine) as s:
        b = s.get(models.Batch, batch_id)
        return b.ts if b else ""


@router.get("/products/{row_id}")
async def product_detail(request: Request, row_id: int):
    with Session(request.app.state.engine) as s:
        return _product_view(s, _get(s, row_id), with_detail=True)


class ConfirmBody(BaseModel):
    confirmed: bool


@router.patch("/products/{row_id}/confirmed")
async def set_confirmed(request: Request, row_id: int, body: ConfirmBody):
    engine = request.app.state.engine
    with Session(engine) as s:
        p = _get(s, row_id)
        p.confirmed = body.confirmed
        p.confirmed_at = datetime.now().isoformat(timespec="seconds") if body.confirmed else ""
        p.updated_at = datetime.now().isoformat(timespec="seconds")
        s.add(p)
        s.commit()
        pid, batch_id = p.product_id, p.batch_id
    _dual_write_confirm(request, pid, body.confirmed, batch_id)
    return {"ok": True, "product_id": pid, "confirmed": body.confirmed}


def _dual_write_confirm(request, product_id: str, confirmed: bool, batch_id: int) -> None:
    """单个商品的确认状态合并回批次文件和 latest 副本（CLI 兼容）。"""
    cfg = request.app.state.cfg
    root = Path(cfg.root) / cfg.storage.data_dir / "selection"
    ts = _batch_ts(request, batch_id)
    targets = [root / "selected_latest.json"]
    if ts:
        targets.append(root / ts / "selected.json")
    for path in targets:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        changed = False
        for item in data.get("products", []):
            if str(item.get("product_id")) == product_id and bool(item.get("confirmed")) != confirmed:
                item["confirmed"] = confirmed
                changed = True
        if changed:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@router.post("/products/{row_id}/gen-script")
async def gen_script(request: Request, row_id: int):
    engine = request.app.state.engine
    with Session(engine) as s:
        p = _get(s, row_id)
        pid, title, batch_id = p.product_id, p.title, p.batch_id
    cfg = request.app.state.cfg
    sel = (Path(cfg.root) / cfg.storage.data_dir / "selection" /
           _batch_ts(request, batch_id) / "selected.json")
    from_path = str(sel) if sel.exists() else None
    jobs.start_job("gen-scripts", f"生成脚本：{title[:30]}（{pid}）",
                   lambda job: pipeline.run_gen_scripts(request, job, pid, from_path),
                   key=f"gen-scripts:{pid}")
    return {"ok": True, "job_started": True}
