"""后台任务的编排层：把 CLI 的三个步骤包成带日志的网页任务。

- 选品采集跑在子进程里（`python cli.py scrape`，日志落 data/logs/，页面看尾部），
  避免有头 Playwright 和 FastAPI 的事件循环互相干扰
- 脚本/视频生成直接在服务进程的 asyncio 任务里跑（服务层本来就是 async）
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from . import jobs


def _cfg(app_state):
    return app_state.cfg


async def run_scrape(request, job, params: dict | None = None) -> None:
    cfg = _cfg(request.app.state)
    # 防重复：只看"别的"采集任务（任务启动后自己也在注册表里，必须排除自身）
    if any(j is not job for j in jobs.running_of_type("scrape")):
        raise RuntimeError("已有一个采集任务在跑，等它结束再发起新的")
    log_dir = cfg.root / cfg.storage.data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    argv = [sys.executable, str(cfg.root / "cli.py"), "scrape"]
    if params:
        # 参数落盘再传给子进程（--params-file），留底可查，子进程内覆盖 config 的 selection 段
        params_path = log_dir / f"scrape_{stamp}_params.json"
        params_path.write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")
        argv += ["--params-file", str(params_path)]
        job.log_line(f"参数：{_summarize_params(params)}")
    log_path = log_dir / f"scrape_{stamp}.log"
    job.log_line(f"启动子进程：cli.py scrape（日志 {log_path.name}）")
    job.log_line("浏览器窗口会弹出，如需登录 FastMoss 请在窗口里操作")

    with log_path.open("w", encoding="utf-8") as fp:
        proc = await asyncio.create_subprocess_exec(
            *argv, stdout=fp, stderr=asyncio.subprocess.STDOUT, cwd=str(cfg.root),
        )
        last_line = None
        while proc.returncode is None:
            await asyncio.sleep(5)
            lines = _tail(log_path, 1)
            if lines and lines[-1] != last_line:
                last_line = lines[-1]
                job.log_line(last_line)
        if proc.returncode != 0:
            job.log_line(f"子进程退出码 {proc.returncode}")
            raise RuntimeError(f"采集失败（退出码 {proc.returncode}），完整日志：{log_path}")

    # 筛选结果体检：跑了但筛空 = 筛选参数大概率过严（最常见：达人区间），给明确警告
    sel_files = sorted((cfg.root / cfg.storage.data_dir / "selection").glob("*/selected.json"))
    if sel_files:
        import json as _json
        sel = _json.loads(sel_files[-1].read_text(encoding="utf-8"))
        n_pass = len(sel.get("products") or [])
        if n_pass == 0:
            job.log_line("⚠ 采集完成但筛选后 0 条——筛选参数可能过严（热推榜头部商品达人普遍 400–1600，"
                         "30–70 这类区间会整批筛空）。原始数据已保留，改参数后可离线重筛，不必重爬")
    job.log_line("采集 + 导出完成，去「选品」页查看结果")


def _summarize_params(p: dict) -> str:
    parts = []
    if p.get("period"):
        parts.append({"daily": "日榜", "weekly": "周榜", "monthly": "月榜"}.get(p["period"], p["period"]))
    if p.get("region"):
        parts.append(str(p["region"]))
    if p.get("categories"):
        parts.append(f"{len(p['categories'])} 个类目")
    if p.get("max_pages"):
        parts.append(f"每类目 {p['max_pages']} 页")
    if p.get("min_profit_cny") is not None:
        parts.append(f"利润≥{p['min_profit_cny']}")
    if p.get("creators_min") is not None and p.get("creators_max") is not None:
        parts.append(f"达人 {p['creators_min']}–{p['creators_max']}")
    return " · ".join(parts)


def _tail(path: Path, n: int) -> list[str]:
    try:
        lines = [l.rstrip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        return lines[-n:]
    except Exception:
        return []


async def run_gen_scripts(request, job, product_id: str | None,
                          from_path: str | None = None) -> None:
    from app.llm import service as llm_service

    cfg = _cfg(request.app.state)
    selection = llm_service.load_selection(cfg, from_path)
    products = llm_service.pick_products(selection, product_id, all_flag=False)
    if not products:
        raise RuntimeError("没有可处理的商品：请先在「选品」页勾选确认（或单个商品重试）")
    label = products[0].get("title", "")[:30] if len(products) == 1 else ""
    job.log_line(f"待生成 {len(products)} 个商品（模型 {cfg.llm.model}）{('：' + label) if label else ''}")

    saved = await llm_service.generate_for_products(cfg, products)
    failed = len(products) - len(saved)
    job.log_line(f"完成：成功 {len(saved)} 份" + (f"，失败 {failed} 份（见 data/scripts/）" if failed else ""))


async def run_gen_video(request, job, product_id: str, script_version: int | None = None,
                        image_index: int | None = None, model: str | None = None,
                        resolution: str | None = None) -> None:
    from app.video import service as video_service

    cfg = _cfg(request.app.state)
    # 防重复：同商品的旧任务还在跑才拦（用 key 精确匹配，排除自身；不要用标题子串匹配）
    dup = [j for j in jobs.running_of_type("gen-videos")
           if j is not job and j.key == f"gen-videos:{product_id}"]
    if dup:
        raise RuntimeError(f"商品 {product_id} 已有视频任务在跑，等它结束再试")
    job.log_line(f"商品 {product_id}（模型 {model or cfg.video.model} / {resolution or cfg.video.resolution}，"
                 f"{cfg.video.api} 接口）"
                 + (f"，指定脚本 v{script_version}" if script_version else "")
                 + (f"，指定第 {image_index} 张图" if image_index is not None else ""))
    out = await video_service.generate_for_script(cfg, product_id, script_version, image_index,
                                                  model, resolution)
    if not out:
        raise RuntimeError("视频生成未成功（详见任务日志 / data/videos/ 里的 video_v*.json）")
    job.log_line(f"完成 → {out}")
