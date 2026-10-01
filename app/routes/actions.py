"""动作类接口：勾选确认 / 发起任务 / 保存脚本 / 保存配置。全部 POST 完成后跳回。"""

import yaml
from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from ..config import load_config
from ..web import jobs, pipeline, store
from . import back

router = APIRouter()


def _redirect_fail(e: Exception) -> RedirectResponse:
    from urllib.parse import quote
    return RedirectResponse(f"/?err={quote(str(e)[:180])}", status_code=303)


@router.post("/products/confirm")
async def products_confirm(request: Request, batch: str = Form("latest"),
                           confirm: list[str] = Form(default=[])):
    try:
        path = store.save_confirmed(request.app.state.cfg, batch, confirm)
        n = len(confirm)
        return back(request, msg=f"已保存勾选：{n} 个商品确认（{path.split('/')[-2] if '/' in path else path}）")
    except Exception as e:  # noqa: BLE001
        return back(request, err=f"保存失败：{e}")


@router.post("/jobs/scrape")
async def start_scrape(request: Request,
                       period: str = Form("weekly"),
                       region: str = Form("BR"),
                       categories: list[str] = Form(default=[]),
                       max_pages: int = Form(...),
                       min_profit_cny: float = Form(...),
                       creators_min: int = Form(...),
                       creators_max: int = Form(...),
                       min_stock: int = Form(...)):
    if jobs.is_running("scrape"):
        return back(request, err="已有采集任务在跑")
    categories = [c.strip() for c in categories if c and c.strip()]
    if not categories:
        return back(request, err="至少勾选一个类目")
    if max_pages < 1 or max_pages > 50:
        return back(request, err="翻页数需在 1–50 之间")
    if creators_min > creators_max:
        return back(request, err="达人下限不能大于上限")
    if period not in ("daily", "weekly", "monthly"):
        return back(request, err="不支持的榜单周期")

    params = {
        "period": period, "region": region.strip().upper() or "BR",
        "categories": categories, "max_pages": max_pages,
        "min_profit_cny": min_profit_cny, "creators_min": creators_min,
        "creators_max": creators_max, "min_stock": min_stock,
    }
    jobs.start_job("scrape", "选品采集（FastMoss）",
                   lambda job: pipeline.run_scrape(request, job, params), key="scrape")
    return back(request, msg="采集任务已启动，浏览器窗口会弹出（如需登录 FastMoss 在窗口里操作）")


@router.post("/jobs/gen-scripts")
async def start_gen_scripts(request: Request, product: str | None = Form(None),
                            all_confirmed: bool = Form(False)):
    if not product and not all_confirmed:
        return back(request, err="缺少商品参数")
    if all_confirmed:
        title = "批量生成脚本（已确认商品）"
    else:
        title = f"生成脚本：商品 {product}"
    jobs.start_job("gen-scripts", title,
                   lambda job: pipeline.run_gen_scripts(request, job, product))
    return back(request, msg="脚本生成任务已启动（调 LLM，注意 token 消耗）")


@router.post("/jobs/gen-videos")
async def start_gen_video(request: Request, product: str = Form(...),
                          script_version: int | None = Form(None),
                          image: int | None = Form(None)):
    if jobs.is_running(f"gen-videos:{product}"):
        return back(request, err=f"商品 {product} 已有视频任务在跑，等它结束再试")
    jobs.start_job("gen-videos", f"生成视频：商品 {product}",
                   lambda job: pipeline.run_gen_video(request, job, product, script_version, image),
                   key=f"gen-videos:{product}")
    extra = f"，脚本 v{script_version}" if script_version else ""
    return back(request, msg=f"视频任务已启动（按条收费{extra}，约 3–5 分钟出片）")


@router.post("/scripts/save")
async def scripts_save(request: Request, product: str = Form(...),
                       version: int = Form(...), prompt: str = Form(...)):
    prompt = prompt.strip()
    if not prompt:
        return back(request, err="提示词内容为空，未保存")
    try:
        store.save_script_edit(request.app.state.cfg, product, version, prompt)
        return back(request, msg=f"已保存商品 {product} 脚本 v{version} 的修改（生成视频时用修改后内容）")
    except Exception as e:  # noqa: BLE001
        return back(request, err=f"保存失败：{e}")


@router.post("/settings/save")
async def settings_save(request: Request, config_text: str = Form(...)):
    try:
        parsed = yaml.safe_load(config_text)
        if not isinstance(parsed, dict):
            raise ValueError("YAML 顶层应该是键值结构")
        (request.app.state.cfg.root / "config.yaml").write_text(config_text, encoding="utf-8")
        request.app.state.cfg = load_config()
        return back(request, msg="配置已保存并重新加载（新任务立即生效）")
    except Exception as e:  # noqa: BLE001
        return back(request, err=f"配置未保存：{e}")


@router.post("/settings/reload")
async def settings_reload(request: Request):
    try:
        request.app.state.cfg = load_config()
        return back(request, msg="配置已重新加载")
    except Exception as e:  # noqa: BLE001
        return back(request, err=f"重载失败：{e}")
