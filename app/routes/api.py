"""页面轮询用的 JSON 接口（目前只有任务列表）。"""

from fastapi import APIRouter, Request

from ..web import jobs

router = APIRouter()


@router.get("/api/jobs")
async def jobs_api(request: Request):
    return {
        "running": jobs.running_total(),
        "jobs": [j.to_dict() for j in jobs.recent(12)],
    }
