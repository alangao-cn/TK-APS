"""网页的数据访问层：读/写 CLI 三个步骤产出的文件（selected.json、script_v*.json、video_v*.json）。

保持和 CLI 完全同一份文件存储，网页只是多了一层读写入口；
页面需要的聚合信息（某商品有没有脚本/视频）也在这里算好。
"""

import json
import shutil
from datetime import datetime
from pathlib import Path


# ---------- 选品批次 ----------

def selection_root(cfg) -> Path:
    return cfg.root / cfg.storage.data_dir / "selection"


def list_batches(cfg) -> list[dict]:
    """data/selection/ 下的历史批次，新→旧。latest 副本对应最新一个批次。"""
    root = selection_root(cfg)
    batches = []
    for d in sorted([p for p in root.iterdir() if p.is_dir()], reverse=True):
        jf = d / "selected.json"
        if not jf.exists():
            continue
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:
            continue
        products = data.get("products") or []
        batches.append({
            "ts": d.name,
            "generated_at": data.get("generated_at", ""),
            "count": len(products),
            "confirmed_count": sum(1 for p in products if p.get("confirmed")),
            "confirmed_all": bool(data.get("confirmed")),
            "is_latest": not batches,  # 第一个（最新）批次
        })
    return batches


def batch_path(cfg, batch: str | None) -> Path:
    root = selection_root(cfg)
    if not batch or batch == "latest":
        return root / "selected_latest.json"
    return root / batch / "selected.json"


def load_batch(cfg, batch: str | None) -> dict:
    path = batch_path(cfg, batch)
    if not path.exists():
        return {"products": [], "generated_at": "", "confirmed": False, "_missing": str(path)}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("products", [])
    return data


def save_confirmed(cfg, batch: str | None, confirmed_ids: list[str]) -> str:
    """写入勾选结果；改的是最新批次时同步刷新 selected_latest.json。"""
    root = selection_root(cfg)
    path = root / "selected_latest.json" if not batch or batch == "latest" else root / batch / "selected.json"
    if not path.exists():
        raise FileNotFoundError(f"找不到 {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    for p in data.get("products", []):
        p["confirmed"] = str(p["product_id"]) in confirmed_ids
    data["confirmed"] = bool(confirmed_ids) and all(
        p.get("confirmed") for p in data.get("products", []))
    data["confirmed_updated_at"] = datetime.now().isoformat(timespec="seconds")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # 改的是带时间戳的批次文件时，若是最新批次则同步 latest 副本（gen-scripts 默认读它）
    if path.parent != root and path.parent.name == max(
            (d.name for d in root.iterdir() if d.is_dir()), default=""):
        shutil.copyfile(path, root / "selected_latest.json")
    return str(path)


# ---------- 脚本 / 视频 索引 ----------

def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def scripts_index(cfg) -> dict[str, dict]:
    """{商品ID: {versions: [record…], latest_ok: record|None}}，versions 新→旧。"""
    root = cfg.root / cfg.storage.data_dir / "scripts"
    out: dict[str, dict] = {}
    if not root.exists():
        return out
    for d in root.iterdir():
        if not d.is_dir():
            continue
        versions = []
        for f in d.glob("script_v*.json"):
            rec = _read_json(f)
            if rec:
                versions.append(rec)
        versions.sort(key=lambda r: int(r.get("version", 0)), reverse=True)
        out[d.name] = {
            "versions": versions,
            "latest_ok": next((r for r in versions if r.get("status") == "ok"), None),
        }
    return out


def videos_index(cfg) -> dict[str, list[dict]]:
    """{商品ID: [record…]}，record 附带 file_exists/大小，versions 新→旧。"""
    root = cfg.root / cfg.storage.data_dir / "videos"
    out: dict[str, list[dict]] = {}
    if not root.exists():
        return out
    for d in root.iterdir():
        if not d.is_dir():
            continue
        records = []
        for f in d.glob("video_v*.json"):
            rec = _read_json(f)
            if not rec:
                continue
            mp4 = Path(rec["file"]) if rec.get("file") and rec.get("status") == "succeeded" else None
            rec["file_exists"] = bool(mp4 and mp4.exists())
            if rec["file_exists"]:
                rec["file_name"] = mp4.name
                rec["size_mb"] = round(mp4.stat().st_size / 1024 / 1024, 2)
            records.append(rec)
        records.sort(key=lambda r: int(r.get("version", 0)), reverse=True)
        if records:
            out[d.name] = records
    return out


def save_script_edit(cfg, pid: str, version: int, prompt: str) -> Path:
    """网页上人工修改脚本：更新 script_v{N}.json 的 video_prompt 并刷新 script_latest.md。"""
    from datetime import datetime

    from app.llm import parser as llm_parser
    from app.llm.service import _write_latest_md

    script_dir = cfg.root / cfg.storage.data_dir / "scripts" / pid
    path = script_dir / f"script_v{version}.json"
    if not path.exists():
        raise FileNotFoundError(f"找不到 {path}")
    rec = json.loads(path.read_text(encoding="utf-8"))
    rec["video_prompt"] = prompt
    rec["edited"] = True
    rec["edited_at"] = datetime.now().isoformat(timespec="seconds")
    if rec.get("status") == "ok":
        rec["hook"] = llm_parser.extract_hook(prompt)
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")

    if rec.get("status") == "ok":
        product = next(
            (p for p in load_batch(cfg, None).get("products", [])
             if str(p.get("product_id")) == pid),
            {"product_id": pid, "title": pid, "profit_cny": "?", "creators": "?"})
        _write_latest_md(product, rec, script_dir / "script_latest.md")
    return path


def video_download_name(rec: dict) -> str:
    """{日期}_{商品ID}_v{版本}.mp4（PLAN 6 节的命名规则）。"""
    date = (rec.get("finished_at") or rec.get("created_at") or "")[:10].replace("-", "")
    return f"{date or 'video'}_{rec['product_id']}_v{rec.get('version', 0)}.mp4"


def product_meta(cfg, selection: dict, scripts: dict[str, dict], videos: dict[str, list[dict]]) -> list[dict]:
    """把选品商品和它的脚本/视频状态拼成页面行。"""
    rows = []
    for p in selection.get("products", []):
        pid = str(p["product_id"])
        s = scripts.get(pid)
        v = videos.get(pid)
        rows.append({
            **p,
            "pid": pid,
            "has_script": bool(s and s["latest_ok"]),
            "script_version": s["latest_ok"]["version"] if s and s["latest_ok"] else None,
            "video_count": sum(1 for r in (v or []) if r.get("file_exists")),
            "video_latest": v[0] if v else None,
        })
    return rows
