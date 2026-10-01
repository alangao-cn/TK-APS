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
    scrape_p.add_argument("--params-file", type=str, default=None,
                          help="JSON 参数文件，覆盖 config 的 selection 段（网页发起采集时用）")
    scrape_p.add_argument("--api", action="store_true", help="试 API 直取模式（有 fm-sig 签名头，大概率不可用）")
    gs = sub.add_parser("gen-scripts", help="第二步：为选品商品生成视频脚本（调 ZenMux，注意 token 消耗）")
    gs.add_argument("--product", type=str, default=None, help="只为指定商品ID生成（测试用，忽略确认门槛）")
    gs.add_argument("--from", dest="from_path", type=str, default=None,
                    help="指定 selected.json 路径（默认 data/selection/selected_latest.json）")
    gs.add_argument("--all", action="store_true", help="处理全部商品（忽略确认门槛，慎用）")

    gv = sub.add_parser("gen-videos", help="第三步：用脚本生成视频（按条收费，必须明确指定商品）")
    gv.add_argument("--product", type=str, default=None, help="只为指定商品ID生成（测试推荐）")
    gv.add_argument("--script-version", type=int, default=None, help="用哪一版脚本（默认最新成功版）")
    gv.add_argument("--image", type=int, default=None, help="强制用第 N 张商品图做参考图（从 0 开始）")
    gv.add_argument("--all", action="store_true", help="处理所有已有脚本的商品（慎用，费用高）")

    export_p = sub.add_parser("export", help="离线解析筛选导出（改了 parser/config 后用，不用重爬）")
    export_p.add_argument("--raw-dir", type=str, default=None)
    export_p.add_argument("--no-images", action="store_true")
    export_p.add_argument("--enrich", action="store_true", help="补抓入选商品的详情页多图（需要打开浏览器）")

    serve_p = sub.add_parser("serve", help="启动网页（总览/选品/脚本/视频/设置）")
    serve_p.add_argument("--host", default="127.0.0.1", help="默认本机访问；局域网用 0.0.0.0")
    serve_p.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    cfg = load_config()
    if args.cmd == "login":
        asyncio.run(collect.login_only(cfg))
    elif args.cmd == "probe":
        cmd_probe(cfg)
    elif args.cmd == "scrape":
        if args.params_file:
            from app.config import apply_selection_overrides

            overrides = json.loads(Path(args.params_file).read_text(encoding="utf-8"))
            applied = apply_selection_overrides(cfg, overrides)
            print(f"[采集] 参数覆盖（{args.params_file}）：{', '.join(applied) or '无'}")
        if args.categories:
            cfg.selection.categories = [c.strip() for c in args.categories.split(",") if c.strip()]
        if args.api:
            raw_dir = asyncio.run(collect.collect_api(cfg))
        else:
            raw_dir = asyncio.run(collect.collect(cfg, max_pages=args.pages))
        export.export(cfg, raw_dir=raw_dir, enrich=True)
    elif args.cmd == "export":
        raw_dir = Path(args.raw_dir) if args.raw_dir else None
        export.export(cfg, raw_dir=raw_dir, download_images=not args.no_images,
                      enrich=args.enrich)
    elif args.cmd == "gen-scripts":
        from app.llm import service as llm_service

        selection = llm_service.load_selection(cfg, args.from_path)
        products = llm_service.pick_products(selection, args.product, args.all)
        if not products:
            raise SystemExit(
                "没有待处理的商品：默认只处理 selected.json 里 confirmed=true 的商品。"
                "确认选品后把 confirmed 改为 true，或用 --product <商品ID> 测试单条。"
            )
        print(f"[脚本] 本次将处理 {len(products)} 个商品（模型 {cfg.llm.model}）")
        saved = asyncio.run(llm_service.generate_for_products(cfg, products))
        print(f"[脚本] 完成，生成 {len(saved)} 份脚本 → data/scripts/<商品ID>/")
    elif args.cmd == "gen-videos":
        from app.video import service as video_service

        if not args.product and not args.all:
            scripts = video_service.available_scripts(cfg)
            print("视频生成按条收费，请明确指定：")
            for s in scripts:
                print(f"  --product {s['product_id']}   (脚本 v{s['version']}, {s['created_at']})")
            raise SystemExit("或 --all 处理全部（慎用）")
        products = ([args.product] if args.product
                    else [s["product_id"] for s in video_service.available_scripts(cfg)])
        saved = asyncio.run(video_service.generate_for_products(cfg, products, args.script_version,
                                                                args.image))
        print(f"[视频] 完成，成功 {len(saved)}/{len(products)} → data/videos/<商品ID>/")
    elif args.cmd == "serve":
        import uvicorn

        print(f"[网页] http://{args.host}:{args.port}（登录账号/密码看 .env 的 WEB_USERNAME/WEB_PASSWORD）")
        uvicorn.run("app.main:app", host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
