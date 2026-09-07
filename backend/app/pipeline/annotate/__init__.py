"""分镜标注器注册表。

    local  分词打分 + 触发词匹配，零依赖
    glm    智谱 GLM，一次请求标注全篇
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional, Sequence

from ...config import Settings
from .base import AnnotationError, Annotator, SceneAnnotation
from .glm import GlmAnnotator
from .local import LocalAnnotator

logger = logging.getLogger(__name__)

__all__ = [
    "AnnotationError", "Annotator", "SceneAnnotation",
    "ANNOTATORS", "build_annotator", "annotate_scenes",
]

ANNOTATORS = ("local", "glm")


def build_annotator(settings: Settings) -> Annotator:
    if settings.annotator == "glm":
        return GlmAnnotator(
            endpoint=settings.glm_endpoint,
            model=settings.glm_model,
            api_key=settings.glm_api_key,
            timeout=settings.glm_timeout,
        )
    if settings.annotator == "local":
        return LocalAnnotator()
    raise AnnotationError(
        f"未知的标注器：{settings.annotator}（可选 {', '.join(ANNOTATORS)}）"
    )


def annotate_scenes(
    sentences: Sequence[str],
    settings: Settings,
    on_warning: Optional[Callable[[str], None]] = None,
) -> List[SceneAnnotation]:
    """标注全部分镜，本地结果始终作为兜底。

    这里和 TTS 的失败策略不同——那边失败会**退回静音**，交付的是一条残缺的片子，
    所以默认直接报错。这里退回本地标注只是「关键词挑得没那么好」，片子仍然完整，
    所以自动兜底更划算。但兜底必须留痕：原因会写进任务日志，不是悄悄降级。
    """
    sentence_list = list(sentences)
    local = LocalAnnotator().annotate(sentence_list)
    if settings.annotator == "local":
        return local

    def warn(message: str) -> None:
        logger.warning("%s", message)
        if on_warning:
            on_warning(message)

    try:
        remote = build_annotator(settings).annotate(sentence_list)
    except AnnotationError as exc:
        warn(f"{settings.annotator} 标注失败，本次改用本地结果：{exc}")
        return local

    # 模型漏掉或给错的位置用本地结果补齐
    merged: List[SceneAnnotation] = []
    patched = 0
    for index, fallback in enumerate(local):
        candidate = remote[index] if index < len(remote) else SceneAnnotation("", "")
        keyword = candidate.keyword or fallback.keyword
        concept = candidate.concept or fallback.concept
        if not candidate.keyword or not candidate.concept:
            patched += 1
        merged.append(SceneAnnotation(keyword=keyword, concept=concept))

    if patched:
        warn(f"{settings.annotator} 有 {patched}/{len(local)} 镜的结果无效，已用本地结果补齐")
    return merged
