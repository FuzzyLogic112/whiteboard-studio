"""API 与流水线共用的数据结构。"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    PENDING = "pending"
    SPLITTING = "splitting"      # 文稿分镜
    SYNTHESIZING = "synthesizing"  # 语音合成
    SKETCHING = "sketching"      # 生成手绘笔迹
    RENDERING = "rendering"      # Remotion 渲染
    DONE = "done"
    FAILED = "failed"


class Stroke(BaseModel):
    """一条会被"画出来"的笔迹。d 是 100x100 viewBox 内的 SVG path。"""

    d: str
    width: float = 2.6
    # 该笔迹在本镜头内开始绘制的相对进度（0~1）与占用的相对时长
    start: float = 0.0
    span: float = 0.3


class Scene(BaseModel):
    index: int
    text: str
    keyword: str
    concept: str
    strokes: List[Stroke] = Field(default_factory=list)
    duration_seconds: float = 2.0
    duration_frames: int = 60
    audio_file: Optional[str] = None  # 相对任务目录的路径


class RenderPlan(BaseModel):
    """交给 Remotion 的完整 props。"""

    job_id: str
    width: int
    height: int
    fps: int
    total_frames: int
    template: str
    scenes: List[Scene]


class CreateJobRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000, description="中文文稿")
    template: str = Field(default="minimal", description="视觉模板")


class JobView(BaseModel):
    id: str
    status: JobStatus
    progress: float = 0.0
    message: str = ""
    created_at: float
    updated_at: float
    error: Optional[str] = None
    scene_count: int = 0
    duration_seconds: float = 0.0
    has_video: bool = False
