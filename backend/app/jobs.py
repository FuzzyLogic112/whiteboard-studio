"""任务管理：排队、执行、进度上报、落盘。

每个任务在 `.workspace/jobs/<id>/` 下有自己的目录，状态写进 state.json。
进程重启后仍能读回历史任务和已经渲好的成片——白板动画渲一次要好几分钟，
重启就丢是不能接受的。
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional

from .config import Settings
from .models import JobStatus, JobView, RenderPlan
from .pipeline.timeline import build_plan
from .render import render_video

logger = logging.getLogger(__name__)

MAX_LOG_LINES = 200


class Job:
    def __init__(self, job_id: str, text: str, template: str, job_dir: Path):
        self.id = job_id
        self.text = text
        self.template = template
        self.dir = job_dir
        self.status = JobStatus.PENDING
        self.progress = 0.0
        self.message = "排队中"
        self.error: Optional[str] = None
        self.plan: Optional[RenderPlan] = None
        self.log: List[str] = []
        self.created_at = time.time()
        self.updated_at = self.created_at

    # -- 状态 ---------------------------------------------------------------

    def update(self, *, status: Optional[JobStatus] = None,
               progress: Optional[float] = None, message: Optional[str] = None) -> None:
        if status is not None:
            self.status = status
        if progress is not None:
            self.progress = max(0.0, min(1.0, progress))
        if message is not None:
            self.message = message
        self.updated_at = time.time()
        self.persist()

    def append_log(self, line: str) -> None:
        self.log.append(line)
        del self.log[:-MAX_LOG_LINES]

    @property
    def video_path(self) -> Path:
        return self.dir / "output.mp4"

    def view(self) -> JobView:
        return JobView(
            id=self.id,
            status=self.status,
            progress=round(self.progress, 3),
            message=self.message,
            created_at=self.created_at,
            updated_at=self.updated_at,
            error=self.error,
            scene_count=len(self.plan.scenes) if self.plan else 0,
            duration_seconds=(
                round(self.plan.total_frames / self.plan.fps, 2) if self.plan else 0.0
            ),
            has_video=self.video_path.exists(),
        )

    # -- 落盘 ---------------------------------------------------------------

    def persist(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "id": self.id,
            "text": self.text,
            "template": self.template,
            "status": self.status.value,
            "progress": self.progress,
            "message": self.message,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        (self.dir / "state.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def restore(cls, job_dir: Path) -> Optional["Job"]:
        state_file = job_dir / "state.json"
        if not state_file.exists():
            return None
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

        job = cls(data["id"], data.get("text", ""), data.get("template", "minimal"), job_dir)
        job.progress = data.get("progress", 0.0)
        job.message = data.get("message", "")
        job.error = data.get("error")
        job.created_at = data.get("created_at", time.time())
        job.updated_at = data.get("updated_at", job.created_at)

        status = JobStatus(data.get("status", JobStatus.PENDING.value))
        # 进程重启时没跑完的任务不会自动续跑，标成失败比一直显示「渲染中」诚实
        if status not in (JobStatus.DONE, JobStatus.FAILED):
            status = JobStatus.FAILED
            job.error = "服务重启，任务已中断"
        job.status = status

        plan_file = job_dir / "plan.json"
        if plan_file.exists():
            try:
                job.plan = RenderPlan.model_validate_json(plan_file.read_text(encoding="utf-8"))
            except ValueError:
                pass
        return job


class JobStore:
    def __init__(self, settings: Settings, max_workers: int = 1):
        self.settings = settings
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()
        # 渲染吃满 CPU，串行执行；要并行改这里，同时注意 Remotion 的并发度
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="wbs-job")
        self._load_existing()

    def _load_existing(self) -> None:
        jobs_dir = self.settings.jobs_dir
        if not jobs_dir.exists():
            return
        for job_dir in jobs_dir.iterdir():
            if not job_dir.is_dir():
                continue
            job = Job.restore(job_dir)
            if job:
                self._jobs[job.id] = job
        logger.info("恢复了 %d 个历史任务", len(self._jobs))

    def create(self, text: str, template: str) -> Job:
        job_id = uuid.uuid4().hex[:12]
        job = Job(job_id, text, template, self.settings.jobs_dir / job_id)
        job.persist()
        with self._lock:
            self._jobs[job_id] = job
        self._pool.submit(self._run, job)
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> List[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    # -- 执行 ---------------------------------------------------------------

    def _run(self, job: Job) -> None:
        try:
            job.update(status=JobStatus.SPLITTING, progress=0.02, message="开始处理")

            def on_progress(value: float, message: str) -> None:
                status = JobStatus.SYNTHESIZING if value > 0.15 else JobStatus.SPLITTING
                job.update(status=status, progress=value, message=message)

            job.plan = build_plan(
                job.id, job.text, job.template, self.settings, job.dir, on_progress
            )

            job.update(status=JobStatus.SKETCHING, progress=0.75, message="笔迹生成完成")
            job.update(status=JobStatus.RENDERING, progress=0.78, message="正在渲染视频")

            def on_log(line: str) -> None:
                job.append_log(line)
                percent = _parse_render_percent(line)
                if percent is not None:
                    job.update(progress=0.78 + 0.21 * percent,
                               message=f"渲染中 {int(percent * 100)}%")

            render_video(job.plan, job.dir, self.settings, on_log)
            job.update(status=JobStatus.DONE, progress=1.0, message="完成")

        except Exception as exc:  # noqa: BLE001 - 任何失败都要变成可见的任务状态
            logger.exception("任务 %s 失败", job.id)
            job.error = f"{type(exc).__name__}: {exc}"
            job.append_log(traceback.format_exc())
            job.update(status=JobStatus.FAILED, message="失败")


# Remotion 的进度行长这样：`Rendered 353/503, time remaining: 26s`
# 注意分母后面紧跟着逗号，按空格切再转 float 会炸，所以直接用正则取两个数。
_PROGRESS_RE = re.compile(r"(?:Rendered|Encoded)\s+(\d+)\s*/\s*(\d+)")


def _parse_render_percent(line: str) -> Optional[float]:
    """从 Remotion 的日志里抠出进度。"""
    match = _PROGRESS_RE.search(line)
    if not match:
        return None
    done, total = int(match.group(1)), int(match.group(2))
    if total <= 0:
        return None
    return max(0.0, min(1.0, done / total))
