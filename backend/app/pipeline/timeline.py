"""把文稿装配成一份完整的渲染计划。

这是流水线的装配线：分镜 -> 关键词 -> 简笔画 -> 配音 -> 时间轴，
产物是一个 RenderPlan，直接作为 props 交给 Remotion。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from ..config import Settings
from ..models import RenderPlan, Scene, SceneOverride
from . import script, sketch
from .annotate import annotate_scenes
from .tts import get_provider

ProgressFn = Callable[[float, str], None]


def build_plan(
    job_id: str,
    text: str,
    template: str,
    settings: Settings,
    job_dir: Path,
    on_progress: Optional[ProgressFn] = None,
    overrides: Optional[Sequence[SceneOverride]] = None,
    on_warning: Optional[Callable[[str], None]] = None,
) -> RenderPlan:
    def progress(value: float, message: str) -> None:
        if on_progress:
            on_progress(value, message)

    progress(0.05, "正在切分文稿")
    sentences = script.split_script(text)
    if not sentences:
        raise ValueError("文稿为空，没有可用的内容")

    progress(0.15, f"已切出 {len(sentences)} 个分镜，正在提取关键词")
    # 关键词和简笔画一起定：看懂这句话在讲什么，本来就是同一个判断
    annotations = annotate_scenes(sentences, settings, on_warning=on_warning)
    keyword_list = [a.keyword for a in annotations]
    concept_list = [a.concept for a in annotations]

    # 人工修正压在自动结果之上。关键词改了也不重算概念——用户既然指定了图，
    # 就该用他指定的那个；只改了关键词的话，自动概念多半仍然合适。
    by_index = {o.index: o for o in (overrides or [])}
    for index, override in by_index.items():
        if index >= len(sentences):
            continue  # 文稿改短了，越界的修正直接忽略
        if override.keyword:
            keyword_list[index] = override.keyword
        if override.concept:
            concept_list[index] = override.concept

    provider = get_provider(settings)
    audio_dir = job_dir / "audio"

    scenes: List[Scene] = []
    for index, (sentence, keyword, picked) in enumerate(
        zip(sentences, keyword_list, concept_list)
    ):
        progress(
            0.15 + 0.55 * index / len(sentences),
            f"第 {index + 1}/{len(sentences)} 镜：{keyword}",
        )

        result = provider.synthesize(sentence, audio_dir / f"scene_{index:03d}.wav")
        concept, strokes = sketch.strokes_for(keyword, sentence, concept=picked)
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
