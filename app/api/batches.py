"""批次：列表（含漏斗统计）、详情（商品行）、勾选确认、批量生成脚本。"""

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import models
from ..web import jobs, pipeline

router = APIRouter()


def _product_row(s: Session, row_id: int) -> models.Product:
    row = s.get(models.Product, row_id)
    if not row:
        raise HTTPException(404, f"商品行 {row_id} 不存在")
    return row


def _script_summary(s: Session, product_id: str) -> dict:
    rows = s.exec(select(models.Script).where(models.Script.product_id == product_id)
                  .order_by(models.Script.version.desc())).all()
    latest_ok = next((r for r in rows if r.status == "ok"), None)
    return {"versions": len(rows), "latest": latest_ok, "rows": rows}


def _video_summary(s: Session, product_id: str) -> dict:
    rows = s.exec(select(models.Video).where(models.Video.product_id == product_id)
                  .order_by(models.Video.version.desc())).all()
    ok = [r for r in rows if r.status == "succeeded" and r.local_path]
    return {"count": len(ok), "latest": rows[0] if rows else None, "rows": rows}


def _product_view(s: Session, p: models.Product, with_detail: bool = False) -> dict:
    scripts = _script_summary(s, p.product_id)
    videos = _video_summary(s, p.product_id)
    view = {
        "id": p.id, "product_id": p.product_id, "batch_id": p.batch_id,
        "title": p.title, "category": p.category, "region": p.region,
        "price_min": p.price_min, "price_max": p.price_max, "currency": p.currency,
        "commission_rate": p.commission_rate, "creators": p.creators,
        "creators_total": p.creators_total, "sales_week": p.sales_week,
        "profit_cny": p.profit_cny, "rating": p.rating, "stock": p.stock,
        "review_count": p.review_count,
        "image_files": json.loads(p.images_local_json or "[]"),
        "fastmoss_url": p.fastmoss_url, "tiktok_url": p.tiktok_url,
        "confirmed": p.confirmed, "confirmed_at": p.confirmed_at,
        "created_at": p.created_at, "updated_at": p.updated_at,
        "has_script": scripts["latest"] is not None,
        "script_version": scripts["latest"].version if scripts["latest"] else None,
        "script_count": scripts["versions"],
        "video_count": videos["count"],
        "video_latest_status": videos["latest"].status if videos["latest"] else None,
    }
    if with_detail:
        view["scripts"] = [_script_view(r) for r in scripts["rows"]]
        view["videos"] = [_video_view(r) for r in videos["rows"]]
    return view


def _script_view(r: models.Script) -> dict:
    return {
        "id": r.id, "product_id": r.product_id, "version": r.version, "status": r.status,
        "model": r.model, "video_prompt": r.video_prompt, "hook": r.hook, "edited": r.edited,
        "tokens_in": r.tokens_in, "tokens_out": r.tokens_out,
        "created_at": r.created_at, "updated_at": r.updated_at,
    }


def _video_view(r: models.Video) -> dict:
    has_file = bool(r.local_path) and Path(r.local_path).exists()
    return {
        "id": r.id, "product_id": r.product_id, "version": r.version,
        "script_version": r.script_version, "status": r.status, "model": r.model,
        "api": r.api, "error": r.error, "size_mb": r.size_mb, "has_file": has_file,
        "created_at": r.created_at, "finished_at": r.finished_at,
    }


@router.get("/batches")
async def list_batches(request: Request):
    engine = request.app.state.engine
    with Session(engine) as s:
        out = []
        for b in s.exec(select(models.Batch).order_by(models.Batch.ts.desc())).all():
            prods = s.exec(select(models.Product).where(models.Product.batch_id == b.id)).all()
            pids = [p.product_id for p in prods]
            scripts = sum(1 for pid in pids if _script_summary(s, pid)["latest"])
            videos = sum(1 for pid in pids if _video_summary(s, pid)["count"])
            out.append({
                "id": b.id, "ts": b.ts, "created_at": b.created_at, "note": b.note,
                "status": b.status,
                "counts": {
                    "products": len(prods),
                    "confirmed": sum(1 for p in prods if p.confirmed),
                    "scripts": scripts,
                    "videos": videos,
                },
            })
        return {"batches": out}


@router.get("/batches/{batch_id}")
async def batch_detail(request: Request, batch_id: int,
                       confirmed: str | None = None, has_script: str | None = None,
                       q: str | None = None):
    engine = request.app.state.engine
    with Session(engine) as s:
        b = s.get(models.Batch, batch_id)
        if not b:
            raise HTTPException(404, "批次不存在")
        prods = s.exec(select(models.Product).where(
            models.Product.batch_id == batch_id).order_by(
            models.Product.updated_at.desc())).all()
        views = [_product_view(s, p) for p in prods]
        if confirmed == "1":
            views = [v for v in views if v["confirmed"]]
        elif confirmed == "0":
            views = [v for v in views if not v["confirmed"]]
        if has_script == "1":
            views = [v for v in views if v["has_script"]]
        elif has_script == "0":
            views = [v for v in views if not v["has_script"]]
        if q:
            low = q.lower()
            views = [v for v in views if low in v["title"].lower() or q in v["product_id"]]
        return {
            "id": b.id, "ts": b.ts, "created_at": b.created_at,
            "note": b.note, "status": b.status, "products": views,
        }


class ConfirmBody(BaseModel):
    product_ids: list[int]


@router.post("/batches/{batch_id}/confirm")
async def confirm_products(request: Request, batch_id: int, body: ConfirmBody):
    cfg = request.app.state.cfg
    engine = request.app.state.engine
    with Session(engine) as s:
        b = s.get(models.Batch, batch_id)
        if not b:
            raise HTTPException(404, "批次不存在")
        ids = set(body.product_ids)
        confirmed_pids: list[str] = []
        for p in s.exec(select(models.Product).where(models.Product.batch_id == batch_id)).all():
            want = p.id in ids
            if want and not p.confirmed:
                p.confirmed_at = datetime.now().isoformat(timespec="seconds")
            p.confirmed = want
            p.updated_at = datetime.now().isoformat(timespec="seconds")
            s.add(p)
            if want:
                confirmed_pids.append(p.product_id)
        # 双写文件保持 CLI 兼容（gen-scripts 默认读 selected_latest.json）
        from ..web import store
        try:
            store.save_confirmed(cfg, b.ts, confirmed_pids)
        except FileNotFoundError:
            pass
        s.commit()
    from .. import sync as sync_mod
    sync_mod.sync_all(cfg, engine)
    return {"ok": True, "confirmed": len(confirmed_pids)}


@router.post("/batches/{batch_id}/gen-scripts")
async def batch_gen_scripts(request: Request, batch_id: int):
    with Session(request.app.state.engine) as s:
        b = s.get(models.Batch, batch_id)
        if not b:
            raise HTTPException(404, "批次不存在")
        n = sum(1 for p in s.exec(select(models.Product).where(
            models.Product.batch_id == batch_id)).all() if p.confirmed)
    if n == 0:
        raise HTTPException(400, "该批次还没有勾选确认的商品")
    from_path = str(Path(cfg_root(request)) / "selection" / b.ts / "selected.json")
    jobs.start_job("gen-scripts", f"批量生成脚本（批次 {b.ts}，{n} 件）",
                   lambda job: pipeline.run_gen_scripts(request, job, None, from_path),
                   key=f"gen-scripts:batch:{batch_id}")
    return {"ok": True, "job_started": True, "confirmed": n}


def cfg_root(request) -> Path:
    return Path(request.app.state.cfg.root) / request.app.state.cfg.storage.data_dir
