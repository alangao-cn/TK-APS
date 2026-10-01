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
    return engine


def session_factory(engine):
    return Session(engine)
