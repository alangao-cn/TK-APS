"""内存任务注册表：选品采集 / 生成脚本 / 生成视频 都以后台任务方式跑，页面轮询进度。

任务只活在服务进程里（重启即丢，产出物都在文件系统里不受影响）；
保留最近 100 条记录供页面回看。
"""

import asyncio
import itertools
import json
import time
from dataclasses import dataclass, field
from datetime import datetime

MAX_LOG_LINES = 300
KEEP_JOBS = 100

_ids = itertools.count(1)
JOBS: dict[int, "Job"] = {}
_lock = asyncio.Lock()
_db_engine = None  # 由 init_db 注入；CLI/测试场景可以为 None（纯内存）


def init_db(engine) -> None:
    """服务启动时调用：接上数据库，历史任务载入内存，中断的任务打标记。"""
    global _db_engine
    _db_engine = engine
    from sqlmodel import Session, select

    from .. import models
    with Session(engine) as s:
        for rec in s.exec(select(models.JobRecord).where(
                models.JobRecord.status == "running")).all():
            rec.status = "interrupted"
            rec.error = rec.error or "服务重启，任务中断"
            rec.finished_at = datetime.now().isoformat(timespec="seconds")
            s.add(rec)
        s.commit()
        for rec in s.exec(select(models.JobRecord).order_by(   # noqa: E712
                models.JobRecord.id.desc())).all()[:KEEP_JOBS]:
            job = Job(id=rec.job_ref, type=rec.type, title=rec.title,
                      status=rec.status, key=rec.key or None,
                      log=json.loads(rec.log_json or "[]"),
                      created_at=rec.created_at, finished_at=rec.finished_at,
                      error=rec.error)
            JOBS.setdefault(job.id, job)


def _persist(job: "Job") -> None:
    if not _db_engine:
        return
    try:
        from sqlmodel import Session, select

        from .. import models
        with Session(_db_engine) as s:
            rec = s.exec(select(models.JobRecord).where(
                models.JobRecord.job_ref == job.id)).first()
            if not rec:
                rec = models.JobRecord(job_ref=job.id)
            rec.type, rec.title, rec.key = job.type, job.title, job.key or ""
            rec.status, rec.error = job.status, job.error
            rec.log_json = json.dumps(job.log[-MAX_LOG_LINES:], ensure_ascii=False)
            if job.finished_at:
                rec.finished_at = job.finished_at
            s.add(rec)
            s.commit()
    except Exception:
        pass  # 任务本身不能因为记录失败而失败


def _sync_after_job() -> None:
    """任务结束后把文件工件同步进 DB（新脚本/视频/批次出现在页面上的入口）。"""
    if not _db_engine:
        return
    try:
        from .. import sync as sync_mod
        from ..config import load_config
        sync_mod.sync_all(load_config(), _db_engine)
    except Exception:
        pass


@dataclass
class Job:
    id: int
    type: str                 # scrape / gen-scripts / gen-videos
    title: str
    status: str = "running"   # running / succeeded / failed
    key: str | None = None    # 防重复用的业务键（如 "scrape"、"gen-videos:{商品ID}"）
    log: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    finished_at: str | None = None
    error: str = ""

    def log_line(self, msg: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log.append(f"[{stamp}] {msg}")
        if len(self.log) > MAX_LOG_LINES:
            del self.log[: len(self.log) - MAX_LOG_LINES]

    def to_dict(self) -> dict:
        return {
            "id": self.id, "type": self.type, "title": self.title,
            "status": self.status, "created_at": self.created_at,
            "finished_at": self.finished_at, "error": self.error,
            "log": self.log[-8:],
        }


async def _run(job: Job, coro_fn) -> None:
    try:
        await coro_fn(job)
        job.status = "succeeded"
    except Exception as e:  # noqa: BLE001 - 后台任务兜底，任何异常都记录不崩服务
        job.status = "failed"
        job.error = str(e)
        job.log_line(f"任务失败：{e}")
    finally:
        job.finished_at = datetime.now().isoformat(timespec="seconds")
        async with _lock:
            _trim()
        _persist(job)
        _sync_after_job()


def _trim() -> None:
    if len(JOBS) > KEEP_JOBS:
        for jid in sorted(JOBS)[: len(JOBS) - KEEP_JOBS]:
            if JOBS[jid].status == "running":
                continue
            JOBS.pop(jid, None)


def start_job(type_: str, title: str, coro_fn, key: str | None = None) -> Job:
    job = Job(id=next(_ids), type=type_, title=title, key=key)
    JOBS[job.id] = job
    job.log_line("任务创建")
    _persist(job)
    asyncio.get_running_loop().create_task(_run(job, coro_fn))
    return job


def is_running(key: str) -> bool:
    return any(j.status == "running" and j.key == key for j in JOBS.values())


def running_of_type(type_: str) -> list[Job]:
    return [j for j in JOBS.values() if j.type == type_ and j.status == "running"]


def running_total() -> int:
    return sum(1 for j in JOBS.values() if j.status == "running")


def recent(limit: int = 30) -> list[Job]:
    return sorted(JOBS.values(), key=lambda j: j.id, reverse=True)[:limit]


def elapsed_seconds(job: Job) -> int:
    start = datetime.fromisoformat(job.created_at).timestamp()
    end = datetime.fromisoformat(job.finished_at).timestamp() if job.finished_at else time.time()
    return int(end - start)
