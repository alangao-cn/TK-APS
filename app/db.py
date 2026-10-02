"""SQLite 数据库：引擎、建表。

默认是 data/db.sqlite 一个文件（零安装零进程）；.env 里配 DATABASE_URL 可换成
PostgreSQL 等外部库（以后多人使用/迁云时再换，代码不用改）。
"""

import os
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine


def database_url(cfg) -> str:
    override = os.environ.get("DATABASE_URL")
    if override:
        return override
    path = Path(cfg.root) / cfg.storage.data_dir / "db.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


def make_engine(cfg):
    url = database_url(cfg)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, echo=False, connect_args=connect_args)
    SQLModel.metadata.create_all(engine)
    _ensure_columns(engine)
    return engine


def _ensure_columns(engine) -> None:
    """SQLite 轻量迁移：create_all 不会改已存在的表，新列在这里补（幂等）。"""
    from sqlalchemy import text

    additions = {"script": [("duration", "INTEGER DEFAULT 0")]}
    with engine.begin() as conn:
        for table, cols in additions.items():
            try:
                existing = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}
            except Exception:
                continue
            for col, ddl in cols:
                if col not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))


def session_factory(engine):
    return Session(engine)
