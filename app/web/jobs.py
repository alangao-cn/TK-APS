"""内存任务注册表：选品采集 / 生成脚本 / 生成视频 都以后台任务方式跑，页面轮询进度。

任务只活在服务进程里（重启即丢，产出物都在文件系统里不受影响）；
保留最近 100 条记录供页面回看。
"""

import asyncio
import itertools
import time
from dataclasses import dataclass, field
from datetime import datetime

MAX_LOG_LINES = 300
KEEP_JOBS = 100

_ids = itertools.count(1)
JOBS: dict[int, "Job"] = {}
_lock = asyncio.Lock()


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
