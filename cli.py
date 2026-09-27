"""命令行入口。

用法：
  uv run cli.py login            # 首次：打开浏览器人工登录，状态保存到 browser_profile/
  uv run cli.py probe            # 轻量探测：跑 2 页并全量记录接口（确认参数/字段用）
  uv run cli.py scrape           # 正式采集：周榜 + 配置的类目 + max_pages 翻页
  uv run cli.py export           # 离线重跑解析筛选（改了 parser/config 后用，不用重爬）
                                 #   --raw-dir data/raw/xxx  指定某次采集
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.config import load_config
from app.scraper import collect, export


def _unbuffer() -> None:
    # 后台运行时 stdout 重定向到文件，行缓冲保证日志实时可见
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(line_buffering=True)


def cmd_probe(cfg) -> None:
    raw_dir = asyncio.run(collect.collect(cfg, max_pages=2, record_all=True))
    print("\n[probe] 接口参数汇总：")
    all_api = raw_dir / "all_api"
    if all_api.exists():
        for f in sorted(all_api.glob("*.json"))[:40]:
            data = json.loads(f.read_text(encoding="utf-8"))
            print(f"  {data.get('method')} {data.get('url', '')[:160]} -> {data.get('status')}")
    print(f"[probe] 全量接口记录在 {all_api}")
    print("[probe] 接下来跑: uv run cli.py export --raw-dir", raw_dir)


def main() -> None:
    _unbuffer()
    ap = argparse.ArgumentParser(description="TK_APS 选品工具")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login", help="打开浏览器人工登录")
    sub.add_parser("probe", help="轻量探测接口（2 页 + 全量记录）")
    scrape_p = sub.add_parser("scrape", help="正式采集并导出（UI 跳页模式，站点自己签名，最稳）")
    scrape_p.add_argument("--pages", type=int, default=None, help="每个类目翻几页（默认读配置 max_pages）")
    scrape_p.add_argument("--categories", type=str, default=None, help="只跑部分类目，逗号分隔")
    scrape_p.add_argument("--api", action="store_true", help="试 API 直取模式（有 fm-sig 签名头，大概率不可用）")
    export_p = sub.add_parser("export", help="离线解析筛选导出")
    export_p.add_argument("--raw-dir", type=str, default=None)
    export_p.add_argument("--no-images", action="store_true")
    args = ap.parse_args()

    cfg = load_config()
    if args.cmd == "login":
        asyncio.run(collect.login_only(cfg))
    elif args.cmd == "probe":
        cmd_probe(cfg)
    elif args.cmd == "scrape":
        if args.categories:
            cfg.selection.categories = [c.strip() for c in args.categories.split(",") if c.strip()]
        if args.api:
            raw_dir = asyncio.run(collect.collect_api(cfg))
        else:
            raw_dir = asyncio.run(collect.collect(cfg, max_pages=args.pages))
        export.export(cfg, raw_dir=raw_dir)
    elif args.cmd == "export":
        raw_dir = Path(args.raw_dir) if args.raw_dir else None
        export.export(cfg, raw_dir=raw_dir, download_images=not args.no_images)


if __name__ == "__main__":
    main()
