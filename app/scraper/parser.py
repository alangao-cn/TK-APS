"""字段映射：raw JSON → 统一的商品结构。FastMoss 的字段名以实测为准，
这里的候选键命中不了时会把原始条目写进 parse_report，改 CANDIDATES 后重跑 export 即可，不用重新爬。"""

import re
from pathlib import Path

# FastMoss popRank 实测字段（2026-09-27 probe）：product_id / title / real_price("R$ 34,99") /
# commission_rate("10%") / author_count(关联达人) / total_author_count / sold_count / sale_amount /
# cover(主图) / all_category_name(类目路径) / shop_info.name / detail_url(TikTok 商品页)
CANDIDATES = {
    "product_id": ["product_id", "goods_id", "item_id", "id"],
    "title": ["title", "goods_name", "name"],
    "price": ["real_price", "price", "sale_price", "min_price", "priceMin"],
    "price_max": ["price_max", "max_price"],
    "currency": ["currency", "price_unit"],
    "commission_rate": ["commission_rate", "commission", "ratio"],
    "creators": ["author_count", "related_author_num", "creators", "author_num"],
    "creators_total": ["total_author_count", "total_author_num", "total_creators"],
    "sales": ["sold_count", "sales", "sales_count", "sell_count"],
    "revenue": ["sale_amount", "sales_amount", "gmv", "revenue"],
    "category": ["all_category_name", "category_name", "category_name_en", "category"],
    "image": ["cover", "image", "img", "main_image", "image_url"],
    "shop": ["shop_name", "seller_name", "store_name"],
    "detail_url": ["detail_url", "tiktok_url"],
}

_MISSING = object()
# FastMoss 对“没有这个数据”的显示占位（无佣金、会员看不到等）
_PLACEHOLDERS = {"-", "—", "N/A", "null", "None"}


def _pick(item: dict, keys: list[str]):
    for key in keys:
        value = item.get(key, _MISSING)
        if value is _MISSING:
            continue
        if value in (None, "", []):
            continue
        if isinstance(value, str) and value.strip() in _PLACEHOLDERS:
            continue
        return value, key
    return None, None


def find_items(body) -> list[dict]:
    def walk(obj, depth=0):
        if depth > 5 or obj is None or not isinstance(obj, (dict, list)):
            return []
        if isinstance(obj, list) and obj and isinstance(obj[0], dict):
            return obj
        if isinstance(obj, dict):
            for key in ("list", "rank_list", "items", "rows", "data"):
                if key in obj:
                    found = walk(obj[key], depth + 1)
                    if found:
                        return found
            for value in obj.values():
                found = walk(value, depth + 1)
                if found:
                    return found
        return []

    return walk(body)


def normalize_rate(value) -> float | None:
    """佣金率归一成小数：'10%' → 0.10；10 → 0.10；0.1 → 0.1。"""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip().replace("%", "")
        if not value:
            return None
        try:
            value = float(value)
        except ValueError:
            return None
    if value > 1:
        value = value / 100
    return value


_RANGE_SPLIT = re.compile(r"\s*[-–~]\s*")


def _parse_single_price(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d,.]", "", str(v)).replace(",", ".")
    # 出现多个点（千分位）时只留最后一个
    if s.count(".") > 1:
        head, _, tail = s.rpartition(".")
        s = head.replace(".", "") + "." + tail
    try:
        return float(s)
    except ValueError:
        return None


def normalize_price(value, value_max=None):
    """'R$ 10,99' → 10.99；区间 'R$ 36,90 - R$ 55,90' → (36.9, 55.9)。返回 (min, max)。"""
    low = high = None
    if isinstance(value, str):
        parts = [p for p in _RANGE_SPLIT.split(value) if re.search(r"\d", p)]
        if len(parts) >= 2:
            low = _parse_single_price(parts[0])
            high = _parse_single_price(parts[-1])
    if low is None:
        low = _parse_single_price(value)
        high = _parse_single_price(value_max) if value_max is not None else low
    if low is None:
        return None, None
    if high is None:
        high = low
    if high < low:
        low, high = high, low
    return low, high


def parse_item(item: dict) -> dict:
    out = {"raw": item}
    for field, keys in CANDIDATES.items():
        value, hit_key = _pick(item, keys)
        out[field] = value
        if hit_key:
            out[f"_{field}_key"] = hit_key
    if isinstance(out.get("category"), list):
        out["category"] = " > ".join(str(c) for c in out["category"])
    shop_info = item.get("shop_info")
    if isinstance(shop_info, dict) and not out.get("shop"):
        out["shop"] = shop_info.get("name")
    low, high = normalize_price(out.get("price"), out.get("price_max"))
    out["price_min"], out["price_max"] = low, high
    out["commission_rate_norm"] = normalize_rate(out.get("commission_rate"))
    return out


def parse_raw_file(path: Path) -> list[dict]:
    import json

    payload = json.loads(path.read_text(encoding="utf-8"))
    return find_items(payload.get("body", payload))


def parse_report(parsed: list[dict], raw_items: list[dict]) -> dict:
    """哪些字段没映射上，供人工核对 CANDIDATES。"""
    report = {"total": len(raw_items), "unmapped": {}}
    for field in CANDIDATES:
        missing = sum(1 for p in parsed if p.get(field) is None)
        if missing:
            report["unmapped"][field] = missing
    if raw_items:
        report["first_raw_item"] = raw_items[0]
    return report
