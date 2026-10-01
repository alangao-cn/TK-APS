"""后台任务的编排层：把 CLI 的三个步骤包成带日志的网页任务。

- 选品采集跑在子进程里（`python cli.py scrape`，日志落 data/logs/，页面看尾部），
  避免有头 Playwright 和 FastAPI 的事件循环互相干扰
- 脚本/视频生成直接在服务进程的 asyncio 任务里跑（服务层本来就是 async）
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

from . import jobs


def _cfg(app_state):
    return app_state.cfg


async def run_scrape(request, job) -> None:
    cfg = _cfg(request.app.state)
    if jobs.running_of_type("scrape"):
        raise RuntimeError("已有一个采集任务在跑，等它结束再发起新的")
    log_dir = cfg.root / cfg.storage.data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"scrape_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    job.log_line(f"启动子进程：cli.py scrape（日志 {log_path.name}）")
    job.log_line("浏览器窗口会弹出，如需登录 FastMoss 请在窗口里操作")

    with log_path.open("w", encoding="utf-8") as fp:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(cfg.root / "cli.py"), "scrape",
            stdout=fp, stderr=asyncio.subprocess.STDOUT, cwd=str(cfg.root),
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
    job.log_line("采集 + 导出完成，去「选品」页查看结果")


def _tail(path: Path, n: int) -> list[str]:
    try:
        lines = [l.rstrip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        return lines[-n:]
    except Exception:
        return []


async def run_gen_scripts(request, job, product_id: str | None) -> None:
    from app.llm import service as llm_service

    cfg = _cfg(request.app.state)
    selection = llm_service.load_selection(cfg, None)
    products = llm_service.pick_products(selection, product_id, all_flag=False)
    if not products:
        raise RuntimeError("没有可处理的商品：请先在「选品」页勾选确认（或单个商品重试）")
    label = products[0].get("title", "")[:30] if len(products) == 1 else ""
    job.log_line(f"待生成 {len(products)} 个商品（模型 {cfg.llm.model}）{('：' + label) if label else ''}")

    saved = await llm_service.generate_for_products(cfg, products)
    failed = len(products) - len(saved)
    job.log_line(f"完成：成功 {len(saved)} 份" + (f"，失败 {failed} 份（见 data/scripts/）" if failed else ""))


async def run_gen_video(request, job, product_id: str, script_version: int | None = None,
                        image_index: int | None = None) -> None:
    from app.video import service as video_service

    cfg = _cfg(request.app.state)
    for j in jobs.running_of_type("gen-videos"):
        if product_id in j.title:
            raise RuntimeError(f"商品 {product_id} 已有视频任务在跑")
    job.log_line(f"商品 {product_id}（模型 {cfg.video.model}，{cfg.video.api} 接口）"
                 + (f"，指定脚本 v{script_version}" if script_version else "")
                 + (f"，指定第 {image_index} 张图" if image_index is not None else ""))
    out = await video_service.generate_for_script(cfg, product_id, script_version, image_index)
    if not out:
        raise RuntimeError("视频生成未成功（详见任务日志 / data/videos/ 里的 video_v*.json）")
    job.log_line(f"完成 → {out}")
