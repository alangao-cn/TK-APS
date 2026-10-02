"""发起采集（参数与 Jinja 版同一套校验与链路）。"""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..web import jobs, pipeline

router = APIRouter()


@router.get("/scrape/defaults")
async def scrape_defaults(request: Request):
    """采集表单的预填默认值（config.yaml 的 selection 段，改配置后表单跟着变）。"""
    sel = request.app.state.cfg.selection
    return {
        "period": getattr(sel, "period", "weekly"),
        "region": getattr(sel, "region", "BR"),
        "categories": list(getattr(sel, "categories", [])),
        "max_pages": int(getattr(sel, "max_pages", 5)),
        "min_profit_cny": float(getattr(sel, "min_profit_cny", 2.0)),
        "creators_min": int(getattr(sel, "creators_min", 30)),
        "creators_max": int(getattr(sel, "creators_max", 2000)),
        "min_stock": int(getattr(sel, "min_stock", 1)),
    }


class ScrapeParams(BaseModel):
    period: str = "weekly"
    region: str = "BR"
    categories: list[str]
    max_pages: int
    min_profit_cny: float = 2.0
    creators_min: int = 30
    creators_max: int = 70
    min_stock: int = 1


@router.post("/scrape")
async def start_scrape(request: Request, p: ScrapeParams):
    if jobs.is_running("scrape"):
        return {"ok": False, "error": "已有采集任务在跑"}
    categories = [c.strip() for c in p.categories if c and c.strip()]
    if not categories:
        return {"ok": False, "error": "至少选择一个类目"}
    if not 1 <= p.max_pages <= 50:
        return {"ok": False, "error": "翻页数需在 1–50 之间"}
    if p.creators_min > p.creators_max:
        return {"ok": False, "error": "达人下限不能大于上限"}
    if p.period not in ("daily", "weekly", "monthly"):
        return {"ok": False, "error": "不支持的榜单周期"}

    params = {
        "period": p.period, "region": (p.region or "BR").strip().upper() or "BR",
        "categories": categories, "max_pages": p.max_pages,
        "min_profit_cny": p.min_profit_cny, "creators_min": p.creators_min,
        "creators_max": p.creators_max, "min_stock": p.min_stock,
    }
    jobs.start_job("scrape", "选品采集（FastMoss）",
                   lambda job: pipeline.run_scrape(request, job, params), key="scrape")
    return {"ok": True, "job_started": True}
