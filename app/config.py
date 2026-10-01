"""读取 .env 与 config.yaml。当前阶段只需要 selection 和 storage 两段配置。"""

import os
from pathlib import Path
from types import SimpleNamespace

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _ns(d: dict) -> SimpleNamespace:
    return SimpleNamespace(
        **{k: _ns(v) if isinstance(v, dict) else v for k, v in d.items()}
    )


class Config:
    def __init__(self) -> None:
        _load_env()
        raw = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
        self.selection = _ns(raw["selection"])
        self.storage = _ns(raw["storage"])
        self.llm = _ns(raw["llm"])
        self.video = _ns(raw["video"])
        self.root = ROOT


def load_config() -> Config:
    return Config()


def apply_selection_overrides(cfg: Config, overrides: dict) -> list[str]:
    """把一次性的选品参数覆盖到已加载的配置上（网页发起采集时用，不写回 config.yaml）。

    只允许 selection 段的白名单字段，返回实际应用的关键字列表。
    """
    allowed = {"period", "region", "categories", "max_pages",
               "min_profit_cny", "creators_min", "creators_max", "min_stock"}
    applied = []
    for k, v in overrides.items():
        if k in allowed and v is not None:
            setattr(cfg.selection, k, v)
            applied.append(k)
    return applied
