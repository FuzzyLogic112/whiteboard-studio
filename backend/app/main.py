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
from .pipeline import script, sketch
from .pipeline.annotate import ANNOTATORS, annotate_scenes
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
        "annotator": settings.annotator,
        "annotators": list(ANNOTATORS),
        "tts_provider": settings.tts_provider,
        "tts_providers": list(PROVIDERS),
        "tts_ready": tts_error is None,
        "tts_error": tts_error,
        "fps": settings.fps,
        "resolution": f"{settings.width}x{settings.height}",
        "renderer_ready": (settings.renderer_dir / "node_modules").exists(),
    }


@app.get("/api/concepts")
def concepts() -> dict:
    """可选的简笔画概念，带笔迹供前端画缩略图。"""
    return {"concepts": sketch.concept_catalog()}


@app.post("/api/preview")
def preview(req: CreateJobRequest) -> dict:
    """不渲染，只看分镜结果。改文稿时用它反复试，比等一次渲染快得多。

    返回的 script_digest 要原样带回 /api/jobs：逐镜修正是按下标定位的，
    文稿一改下标就可能错位。
    """
    sentences = script.split_script(req.text)
    if not sentences:
        raise HTTPException(status_code=400, detail="文稿为空")

    # 必须和渲染用同一个标注器，否则界面上看到的分镜和成片对不上
    annotations = annotate_scenes(sentences, settings)
    overrides = {o.index: o for o in req.overrides}

    scenes = []
    for i, (text, annotation) in enumerate(zip(sentences, annotations)):
        keyword, concept = annotation.keyword, annotation.concept
        override = overrides.get(i)
        scenes.append({
            "index": i,
            "text": text,
            "keyword": override.keyword if override and override.keyword else keyword,
            "concept": override.concept if override and override.concept else concept,
            "auto_keyword": keyword,
            "auto_concept": concept,
        })
    return {"scenes": scenes, "script_digest": script.script_digest(sentences)}


@app.post("/api/jobs", response_model=JobView, status_code=201)
def create_job(req: CreateJobRequest) -> JobView:
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="文稿为空")

    sentences = script.split_script(req.text)
    if not sentences:
        raise HTTPException(status_code=400, detail="文稿为空")

    # 带了指纹就核对：文稿改过之后，旧的逐镜修正会错位落到别的分镜上。
    # 与其渲出一条张冠李戴的片子，不如让客户端重新预览一次。
    if req.script_digest and req.script_digest != script.script_digest(sentences):
        raise HTTPException(
            status_code=409,
            detail="文稿已改动，分镜与之前的修正对不上了，请重新预览后再渲染",
        )

    allowed = set(sketch.known_concepts())
    for override in req.overrides:
        if override.index >= len(sentences):
            raise HTTPException(
                status_code=400,
                detail=f"第 {override.index + 1} 镜不存在（当前共 {len(sentences)} 镜）",
            )
        if override.concept and override.concept not in allowed:
            raise HTTPException(
                status_code=400, detail=f"未知的简笔画概念：{override.concept}"
            )

    return _store().create(req.text, req.template, req.overrides).view()


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
