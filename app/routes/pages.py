"""只读页面：总览 / 选品 / 脚本 / 视频 / 设置。"""

from fastapi import APIRouter, Request

from ..web import jobs as jobs_mod, store
from . import render

router = APIRouter()


def _script_summary(cfg) -> dict:
    idx = store.scripts_index(cfg)
    ok = sum(1 for v in idx.values() if v["latest_ok"])
    return {"index": idx, "ok": ok, "total": len(idx)}


def _video_summary(cfg) -> dict:
    idx = store.videos_index(cfg)
    files = sum(1 for recs in idx.values() for r in recs if r.get("file_exists"))
    failed = sum(1 for recs in idx.values() for r in recs if r.get("status") not in ("succeeded",))
    return {"index": idx, "files": files, "failed": failed}


@router.get("/")
async def index(request: Request):
    cfg = request.app.state.cfg
    batches = store.list_batches(cfg)
    latest = batches[0] if batches else None
    scripts = _script_summary(cfg)
    videos = _video_summary(cfg)
    return render(request, "index.html", {
        "nav": "home", "autoreload": True,
        "latest_batch": latest,
        "batches": batches,
        "script_ok": scripts["ok"],
        "video_files": videos["files"],
        "video_failed": videos["failed"],
        "jobs": jobs_mod.recent(12),
        "llm_model": cfg.llm.model,
        "video_model": cfg.video.model,
        "sel": cfg.selection,
    })


@router.get("/products")
async def products(request: Request, batch: str | None = None):
    cfg = request.app.state.cfg
    batches = store.list_batches(cfg)
    selection = store.load_batch(cfg, batch)
    scripts = store.scripts_index(cfg)
    vids = store.videos_index(cfg)
    rows = store.product_meta(cfg, selection, scripts, vids)
    current = batch or "latest"
    return render(request, "products.html", {
        "nav": "products", "autoreload": True,
        "rows": rows, "batches": batches, "current_batch": current,
        "generated_at": selection.get("generated_at", ""),
        "missing": selection.get("_missing", ""),
        "confirmed_count": sum(1 for r in rows if r.get("confirmed")),
    })


@router.get("/scripts")
async def scripts(request: Request):
    cfg = request.app.state.cfg
    idx = store.scripts_index(cfg)
    selection = store.load_batch(cfg, None)
    vids = store.videos_index(cfg)

    cards = []
    for pid, info in sorted(idx.items()):
        title = next((p.get("title", "") for p in selection.get("products", [])
                      if str(p.get("product_id")) == pid), pid)
        cards.append({
            "pid": pid, "title": title,
            "versions": info["versions"], "latest_ok": info["latest_ok"],
            "video_count": sum(1 for r in vids.get(pid, []) if r.get("file_exists")),
        })
    cards.sort(key=lambda c: c["versions"][0].get("created_at", ""), reverse=True)

    # 有脚本的商品不重复列；已确认但还没脚本的商品给一个入口
    with_script = set(idx)
    pending = [
        {"pid": str(p["product_id"]), "title": p.get("title", "")}
        for p in selection.get("products", [])
        if p.get("confirmed") and str(p["product_id"]) not in with_script
    ]
    return render(request, "scripts.html", {
        "nav": "scripts", "autoreload": True,
        "cards": cards, "pending": pending,
        "llm_model": cfg.llm.model,
    })


@router.get("/videos")
async def videos(request: Request):
    cfg = request.app.state.cfg
    idx = store.videos_index(cfg)
    selection = store.load_batch(cfg, None)
    titles = {str(p.get("product_id")): p.get("title", "") for p in selection.get("products", [])}

    cards = []
    for pid, records in sorted(idx.items()):
        cards.append({"pid": pid, "title": titles.get(pid, pid), "records": records})
    cards.sort(key=lambda c: c["records"][0].get("created_at", ""), reverse=True)
    return render(request, "videos.html", {
        "nav": "videos", "autoreload": True,
        "cards": cards,
        "video_model": cfg.video.model,
    })


@router.get("/settings")
async def settings(request: Request):
    cfg = request.app.state.cfg
    config_text = (cfg.root / "config.yaml").read_text(encoding="utf-8")
    env_items = [
        ("ZENMUX_API_KEY", "已配置" if __import__("os").environ.get("ZENMUX_API_KEY") else "未配置"),
        ("FASTMOSS_PHONE", "已配置" if __import__("os").environ.get("FASTMOSS_PHONE") else "未配置"),
        ("WEB_USERNAME", __import__("os").environ.get("WEB_USERNAME", "admin")),
        ("HTTPS_PROXY", __import__("os").environ.get("HTTPS_PROXY") or "（空）"),
    ]
    return render(request, "settings.html", {
        "nav": "settings",
        "config_text": config_text,
        "env_items": env_items,
    })
