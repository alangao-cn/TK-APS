"""任务进度（前端轮询）。"""

from fastapi import APIRouter

from ..web import jobs

router = APIRouter()


@router.get("/jobs")
async def jobs_api():
    return {
        "running": jobs.running_total(),
        "jobs": [j.to_dict() for j in jobs.recent(15)],
    }
