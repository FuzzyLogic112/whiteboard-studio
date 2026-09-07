"""FastAPI 应用入口。

    uvicorn app.main:app --reload --port 8000   （在 backend/ 目录下执行）
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .config import settings
from .jobs import JobStore
from .models import CreateJobRequest, JobView, RenderPlan
from .pipeline import keywords, script, sketch
from .pipeline.tts import PROVIDERS, TTSError, build_provider

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

store: JobStore | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global store
    settings.jobs_dir.mkdir(parents=True, exist_ok=True)
    store = JobStore(settings)
    yield
    store.shutdown()


app = FastAPI(title="whiteboard-studio", version="0.1.0", lifespan=lifespan)

# 前端在 5173 端口独立跑，开发时需要放行
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _store() -> JobStore:
    if store is None:  # pragma: no cover - lifespan 之外不会发生
        raise HTTPException(status_code=503, detail="服务尚未就绪")
    return store


@app.get("/api/health")
def health() -> dict:
    # 顺手把 TTS 配置也验一遍：配错了地址或音色名，与其等渲染跑到一半失败，
    # 不如在界面上先亮出来
    tts_error = None
    try:
        build_provider(settings)
    except TTSError as exc:
        tts_error = str(exc)

    return {
        "ok": True,
        "tts_provider": settings.tts_provider,
        "tts_providers": list(PROVIDERS),
        "tts_ready": tts_error is None,
        "tts_error": tts_error,
        "fps": settings.fps,
        "resolution": f"{settings.width}x{settings.height}",
        "renderer_ready": (settings.renderer_dir / "node_modules").exists(),
    }


@app.post("/api/preview")
def preview(req: CreateJobRequest) -> dict:
    """不渲染，只看分镜结果。改文稿时用它反复试，比等一次渲染快得多。"""
    sentences = script.split_script(req.text)
    if not sentences:
        raise HTTPException(status_code=400, detail="文稿为空")
    kws = keywords.extract_keywords(sentences)
    return {
        "scenes": [
            {"index": i, "text": t, "keyword": k, "concept": sketch.pick_concept(k, t)}
            for i, (t, k) in enumerate(zip(sentences, kws))
        ]
    }


@app.post("/api/jobs", response_model=JobView, status_code=201)
def create_job(req: CreateJobRequest) -> JobView:
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="文稿为空")
    return _store().create(req.text, req.template).view()


@app.get("/api/jobs", response_model=list[JobView])
def list_jobs() -> list[JobView]:
    return [job.view() for job in _store().list()]


@app.get("/api/jobs/{job_id}", response_model=JobView)
def get_job(job_id: str) -> JobView:
    job = _store().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job.view()


@app.get("/api/jobs/{job_id}/plan", response_model=RenderPlan)
def get_plan(job_id: str) -> RenderPlan:
    job = _store().get(job_id)
    if job is None or job.plan is None:
        raise HTTPException(status_code=404, detail="渲染计划尚未生成")
    return job.plan


@app.get("/api/jobs/{job_id}/log")
def get_log(job_id: str) -> dict:
    job = _store().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"lines": job.log}


@app.get("/api/jobs/{job_id}/video")
def get_video(job_id: str) -> FileResponse:
    job = _store().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not job.video_path.exists():
        raise HTTPException(status_code=409, detail="视频尚未渲染完成")
    return FileResponse(job.video_path, media_type="video/mp4", filename=f"{job_id}.mp4")
