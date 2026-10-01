"""数据库表（SQLModel）。

设计要点：
- 商品以 product_id 全局唯一（同一商品下次采集再出现时更新字段、挂到新批次）
- 脚本/视频挂在商品下，带版本号；文件（script_v*.json / video_v*.json）仍是工件留底，
  DB 是查询与状态的事实源（confirmed / edited 等人工状态只在 DB）
- 列表字段（图片地址等）存 JSON 字符串，SQLite 友好
"""

from typing import Optional

from sqlmodel import Field, SQLModel


def _now() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


class Batch(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ts: str = Field(unique=True, index=True)          # 目录名，如 20260927_132534
    created_at: str = ""                              # 采集时间（selected.json 的 generated_at）
    source: str = "scrape"                            # scrape / manual
    params_json: str = "{}"                           # 本次采集参数（留底）
    note: str = ""                                    # 人工备注
    status: str = "done"


class Product(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: str = Field(unique=True, index=True)  # FastMoss/TikTok 商品ID
    batch_id: int = Field(default=0, index=True)      # 最新一次入选的批次
    title: str = ""
    category: str = ""
    region: str = ""
    price_min: float = 0.0
    price_max: float = 0.0
    currency: str = "BRL"
    commission_rate: str = ""
    creators: int = 0
    creators_total: int = 0
    sales_week: int = 0
    profit_cny: float = 0.0
    rating: float = 0.0
    stock: int = 0
    review_count: int = 0
    image_urls_json: str = "[]"                       # 远程图地址列表
    images_local_json: str = "[]"                     # 本地图文件名列表（/api/media/images/<name>）
    fastmoss_url: str = ""
    tiktok_url: str = ""
    product_brief: str = ""
    confirmed: bool = False
    confirmed_at: str = ""
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)


class Script(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: str = Field(index=True)               # 商品ID（字符串，非自增行ID）
    version: int = Field(index=True)
    status: str = "ok"                                # ok / parse_failed
    model: str = ""
    video_prompt: str = ""
    hook: str = ""
    edited: bool = False
    prompt_hash: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    file_path: str = ""                               # 工件留底 script_v{N}.json
    created_at: str = ""
    updated_at: str = ""


class Video(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    product_id: str = Field(index=True)
    script_id: Optional[int] = Field(default=None, foreign_key="script.id")
    script_version: int = 0
    version: int = Field(index=True)
    status: str = ""                                  # succeeded / filtered / error / timeout
    model: str = ""
    api: str = ""
    params_json: str = "{}"
    error: str = ""
    local_path: str = ""                              # mp4 绝对路径
    size_mb: float = 0.0
    remote_url: str = ""
    file_path: str = ""                               # 工件留底 video_v{N}.json
    created_at: str = ""
    finished_at: str = ""


class JobRecord(SQLModel, table=True):
    """后台任务入库：服务重启后能看历史、中断的任务标记出来。"""

    id: Optional[int] = Field(default=None, primary_key=True)
    job_ref: int = Field(index=True)                  # 内存 Job.id
    type: str = ""
    title: str = ""
    key: str = ""
    status: str = "running"                           # running / succeeded / failed / interrupted
    error: str = ""
    log_json: str = "[]"
    created_at: str = Field(default_factory=_now)
    finished_at: str = ""
