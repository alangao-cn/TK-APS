"""文件 → 数据库的同步（幂等，可反复跑）。

文件是工件留底（爬虫/CLI/任务产出），DB 是查询与人工状态（confirmed / edited）的事实源。
规则：
- 商品按 product_id 全局唯一：再次入选时更新字段、挂到新批次；confirmed 只升不降
  （文件里 confirmed=true 会置真——兼容 CLI 手改；DB 已确认的不会被文件改回去）
- 脚本按 (product_id, version) 唯一：DB 侧 edited=true 的版本以 DB 为准（网页编辑过）
- 视频按 (product_id, version) 唯一：以文件为准（状态由任务落盘）
"""

import json
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from . import models
from .db import make_engine


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def sync_all(cfg, engine=None) -> dict:
    engine = engine or make_engine(cfg)
    with Session(engine) as s:
        batches = _sync_batches(cfg, s)
        scripts = _sync_scripts(cfg, s)
        videos = _sync_videos(cfg, s)
        s.commit()
    return {"batches": batches, "scripts": scripts, "videos": videos}


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _sync_batches(cfg, s: Session) -> int:
    root = Path(cfg.root) / cfg.storage.data_dir / "selection"
    if not root.exists():
        return 0
    n = 0
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        data = _read_json(d / "selected.json")
        if not data:
            continue
        products = data.get("products") or []
        # 筛选后 0 条的批次不进库（避免空卡片污染工作台）；已存在的空批次行一并清掉。
        # 采集"跑了但筛空"的事实由任务日志承载（pipeline 里有明确警告）。
        existing = s.exec(select(models.Batch).where(models.Batch.ts == d.name)).first()
        if not products:
            if existing:
                s.delete(existing)
                s.commit()
            continue
        batch = existing
        if not batch:
            batch = models.Batch(ts=d.name, created_at=data.get("generated_at", ""))
            s.add(batch)
            s.flush()
        else:
            batch.created_at = data.get("generated_at", "") or batch.created_at

        for p in data.get("products", []):
            pid = str(p.get("product_id") or "")
            if not pid:
                continue
            row = s.exec(select(models.Product).where(models.Product.product_id == pid)).first()
            file_confirmed = bool(p.get("confirmed"))
            if not row:
                row = models.Product(product_id=pid, batch_id=batch.id,
                                     created_at=data.get("generated_at") or _now())
            locals_map = [Path(x).name for x in (p.get("images_local") or [])]
            row.batch_id = batch.id
            row.title = p.get("title", "") or row.title
            row.category = p.get("category", "") or ""
            row.region = p.get("region", cfg.selection.region)
            row.price_min = float(p.get("price_min") or 0)
            row.price_max = float(p.get("price_max") or 0)
            row.currency = p.get("currency", "BRL") or "BRL"
            row.commission_rate = p.get("commission_rate", "") or ""
            row.creators = int(p.get("creators") or 0)
            row.creators_total = int(p.get("creators_total") or 0)
            row.sales_week = int(p.get("sales_week") or 0)
            row.profit_cny = float(p.get("profit_cny") or 0)
            row.rating = float(p.get("rating") or 0)
            row.stock = int(p.get("stock") or 0)
            row.review_count = int(p.get("review_count") or 0)
            row.image_urls_json = json.dumps(p.get("image_urls") or [], ensure_ascii=False)
            row.images_local_json = json.dumps(locals_map, ensure_ascii=False)
            row.fastmoss_url = p.get("fastmoss_url", "") or ""
            row.tiktok_url = p.get("tiktok_url", "") or ""
            row.product_brief = p.get("product_brief", "") or ""
            if file_confirmed and not row.confirmed:
                row.confirmed = True
                row.confirmed_at = _now()
            row.updated_at = _now()
            s.add(row)
        n += 1
    return n


def _sync_scripts(cfg, s: Session) -> int:
    root = Path(cfg.root) / cfg.storage.data_dir / "scripts"
    if not root.exists():
        return 0
    n = 0
    for d in root.iterdir():
        if not d.is_dir():
            continue
        for f in d.glob("script_v*.json"):
            rec = _read_json(f)
            if not rec:
                continue
            pid, ver = d.name, int(rec.get("version") or 0)
            row = s.exec(select(models.Script).where(
                models.Script.product_id == pid, models.Script.version == ver)).first()
            usage = rec.get("usage") or {}
            if not row:
                row = models.Script(product_id=pid, version=ver, file_path=str(f))
                row.video_prompt = rec.get("video_prompt", "")
                row.hook = rec.get("hook", "") or ""
                row.edited = bool(rec.get("edited"))
            elif not row.edited:  # 网页编辑过的版本以 DB 为准
                row.video_prompt = rec.get("video_prompt", "") or row.video_prompt
                row.hook = rec.get("hook", "") or row.hook
                row.edited = bool(rec.get("edited"))
            row.status = rec.get("status", "ok") or "ok"
            row.model = rec.get("model", "") or ""
            row.duration = int(rec.get("duration") or 0)
            row.prompt_hash = rec.get("prompt_hash", "") or ""
            row.tokens_in = int(usage.get("input_tokens") or 0)
            row.tokens_out = int(usage.get("output_tokens") or 0)
            row.file_path = str(f)
            row.created_at = rec.get("created_at", "") or row.created_at
            row.updated_at = _now()
            s.add(row)
            n += 1
    return n


def _sync_videos(cfg, s: Session) -> int:
    root = Path(cfg.root) / cfg.storage.data_dir / "videos"
    if not root.exists():
        return 0
    n = 0
    for d in root.iterdir():
        if not d.is_dir():
            continue
        for f in d.glob("video_v*.json"):
            rec = _read_json(f)
            if not rec:
                continue
            pid, ver = d.name, int(rec.get("version") or 0)
            row = s.exec(select(models.Video).where(
                models.Video.product_id == pid, models.Video.version == ver)).first()
            if not row:
                row = models.Video(product_id=pid, version=ver)
            script_ver = int(rec.get("script_version") or 0)
            script = s.exec(select(models.Script).where(
                models.Script.product_id == pid, models.Script.version == script_ver)).first()
            row.script_id = script.id if script else None
            row.script_version = script_ver
            row.status = rec.get("status", "") or ""
            row.model = rec.get("model", "") or ""
            row.api = rec.get("api", "") or ""
            row.params_json = json.dumps(rec.get("params") or {}, ensure_ascii=False)
            row.error = rec.get("error", "") or ""
            row.remote_url = rec.get("remote_url", "") or ""
            row.local_path = rec.get("file", "") or ""
            row.size_mb = float(rec.get("file_size_mb") or 0)
            row.file_path = str(f)
            row.created_at = rec.get("created_at", "") or row.created_at
            row.finished_at = rec.get("finished_at", "") or ""
            s.add(row)
            n += 1
    return n
