"""筛选：达人数区间 + 单件利润（售价 BRL × 佣金率 × 汇率 → 人民币）。"""

import csv
import io


def _fx_table(cfg) -> dict:
    fx = cfg.selection.fx_to_cny
    return fx.__dict__ if hasattr(fx, "__dict__") else dict(fx)


def annotate_profit(products: list[dict], cfg) -> None:
    """给所有有佣金和价格的商品算单件利润（人民币），不管是否过筛。"""
    fx_table = _fx_table(cfg)
    for p in products:
        rate = p.get("commission_rate_norm")
        price = p.get("price_min")
        currency = (p.get("currency") or "BRL").upper()
        fx = fx_table.get(currency)
        if rate is not None and price is not None and fx is not None:
            p["profit_cny"] = round(price * rate * fx, 2)


def apply_filters(products: list[dict], cfg) -> list[dict]:
    sel = cfg.selection
    creators_field = getattr(sel, "creators_source", "related")
    key = "creators" if creators_field == "related" else "creators_total"
    fx_table = _fx_table(cfg)

    kept, dropped = [], {"creators": 0, "profit": 0, "no_data": 0}
    for p in products:
        creators = p.get(key)
        rate = p.get("commission_rate_norm")
        price = p.get("price_min")
        currency = (p.get("currency") or "BRL").upper()
        fx = fx_table.get(currency)

        if rate is not None and price is not None and fx is not None:
            p["profit_cny"] = round(price * rate * fx, 2)
        if creators is None or rate is None or price is None or fx is None:
            dropped["no_data"] += 1
            p["_filter_reason"] = "无佣金率或达人数，跳过"
            continue
        p["creators_used"] = creators
        if not (sel.creators_min <= creators <= sel.creators_max):
            dropped["creators"] += 1
            p["_filter_reason"] = f"达人数 {creators} 不在 {sel.creators_min}-{sel.creators_max}"
            continue
        if p["profit_cny"] < sel.min_profit_cny:
            dropped["profit"] += 1
            p["_filter_reason"] = f"利润 {p['profit_cny']} < {sel.min_profit_cny}"
            continue
        kept.append(p)

    print(f"[筛选] 共 {len(products)} 条 → 通过 {len(kept)} 条"
          f"（剔除：达人数不符 {dropped['creators']}，利润不足 {dropped['profit']}，"
          f"无佣金/达人数跳过 {dropped['no_data']}）")
    return kept


def apply_stock_filter(products: list[dict], cfg) -> list[dict]:
    """库存门槛：库存来自详情页补抓，所以在补抓之后跑。
    补抓失败（库存未知 None）的保留，人工确认时把关（selected.md 里会显示库存）。"""
    min_stock = getattr(cfg.selection, "min_stock", 0)
    if not min_stock:
        return products
    kept, dropped, unknown = [], 0, 0
    for p in products:
        stock = p.get("stock")
        if stock is None:
            unknown += 1
            kept.append(p)
        elif stock >= min_stock:
            kept.append(p)
        else:
            dropped += 1
            p["_filter_reason"] = f"库存 {stock} < {min_stock}"
    print(f"[筛选] 库存 ≥ {min_stock}：保留 {len(kept)}"
          f"（剔除 {dropped}，库存未知保留 {unknown}）")
    return kept


def to_rows(products: list[dict], cfg) -> list[dict]:
    rows = []
    detail_tpl = cfg.selection.detail_url_template
    for p in products:
        pid = p.get("product_id") or ""
        rows.append({
            "商品ID": pid,
            "标题": (p.get("title") or "")[:80],
            "分类": p.get("category") or "",
            "售价区间": (f"{p.get('price_min')}-{p.get('price_max')}"
                        if p.get("price_max") and p.get("price_max") != p.get("price_min")
                        else p.get("price_min")),
            "币种": p.get("currency") or "BRL",
            "佣金率": p.get("commission_rate"),
            "关联达人": p.get("creators"),
            "总关联达人": p.get("creators_total"),
            "销量": p.get("sales"),
            "销售额": p.get("revenue"),
            "单件利润(元)": p.get("profit_cny"),
            "店铺": p.get("shop") or "",
            "商品图": p.get("image") or "",
            "详情页": detail_tpl.format(product_id=pid) if pid else "",
            "TikTok链接": p.get("detail_url") or "",
        })
    return rows


def write_csv(path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    # utf-8-sig：Windows 上 Excel 直接打开不乱码
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def print_summary(rows: list[dict], limit: int = 15) -> None:
    if not rows:
        print("[结果] 没有通过筛选的商品")
        return
    buf = io.StringIO()
    buf.write(f"{'商品ID':<22}{'利润':>6} {'佣金':>5} {'达人':>5}  标题\n")
    for r in sorted(rows, key=lambda x: x["单件利润(元)"] or 0, reverse=True)[:limit]:
        buf.write(f"{r['商品ID']:<22}{r['单件利润(元)']:>6} {str(r['佣金率']):>5} "
                  f"{str(r['关联达人']):>5}  {r['标题'][:32]}\n")
    print("[结果] 按利润排序前 %d 条：\n%s" % (limit, buf.getvalue()))
