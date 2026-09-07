"""把文稿装配成一份完整的渲染计划。

这是流水线的装配线：分镜 -> 关键词 -> 简笔画 -> 配音 -> 时间轴，
产物是一个 RenderPlan，直接作为 props 交给 Remotion。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, List, Optional

from ..config import Settings
from ..models import RenderPlan, Scene
from . import keywords, script, sketch
from .tts import get_provider

ProgressFn = Callable[[float, str], None]


def build_plan(
    job_id: str,
    text: str,
    template: str,
    settings: Settings,
    job_dir: Path,
    on_progress: Optional[ProgressFn] = None,
) -> RenderPlan:
    def progress(value: float, message: str) -> None:
        if on_progress:
            on_progress(value, message)

    progress(0.05, "正在切分文稿")
    sentences = script.split_script(text)
    if not sentences:
        raise ValueError("文稿为空，没有可用的内容")

    progress(0.15, f"已切出 {len(sentences)} 个分镜，正在提取关键词")
    keyword_list = keywords.extract_keywords(sentences)

    provider = get_provider(settings)
    audio_dir = job_dir / "audio"

    scenes: List[Scene] = []
    for index, (sentence, keyword) in enumerate(zip(sentences, keyword_list)):
        progress(
            0.15 + 0.55 * index / len(sentences),
            f"第 {index + 1}/{len(sentences)} 镜：{keyword}",
        )

        result = provider.synthesize(sentence, audio_dir / f"scene_{index:03d}.wav")
        concept, strokes = sketch.strokes_for(keyword, sentence)
        frames = max(1, int(math.ceil(result.duration * settings.fps)))

        scenes.append(
            Scene(
                index=index,
                text=sentence,
                keyword=keyword,
                concept=concept,
                strokes=strokes,
                duration_seconds=round(frames / settings.fps, 3),
                duration_frames=frames,
                audio_file=(
                    result.audio_path.relative_to(job_dir).as_posix()
                    if result.audio_path
                    else None
                ),
            )
        )

    progress(0.72, "时间轴装配完成")
    return RenderPlan(
        job_id=job_id,
        width=settings.width,
        height=settings.height,
        fps=settings.fps,
        total_frames=sum(scene.duration_frames for scene in scenes),
        template=template,
        scenes=scenes,
    )
