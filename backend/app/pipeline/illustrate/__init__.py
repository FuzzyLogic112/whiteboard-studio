"""配图 provider 注册表。

    builtin     32 个内置简笔画 + 哈希涂鸦，零依赖
    glm_image   智谱生图 + 中心线矢量化
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional

from ...config import Settings
from .base import Illustrator, IllustrationError
from .builtin import BuiltinIllustrator
from .glm_image import GlmImageIllustrator

logger = logging.getLogger(__name__)

__all__ = [
    "Illustrator", "IllustrationError", "ILLUSTRATORS",
    "build_illustrator", "paths_for_scene",
]

ILLUSTRATORS = ("builtin", "glm_image")


def build_illustrator(settings: Settings) -> Illustrator:
    if settings.illustrator == "glm_image":
        return GlmImageIllustrator(
            endpoint=settings.image_endpoint,
            model=settings.image_model,
            size=settings.image_size,
            cache_dir=settings.workspace / "cache" / "illustrations",
            api_key=settings.image_api_key,
            watermark=settings.image_watermark,
            timeout=settings.image_timeout,
        )
    if settings.illustrator == "builtin":
        return BuiltinIllustrator()
    raise IllustrationError(
        f"未知的配图器：{settings.illustrator}（可选 {', '.join(ILLUSTRATORS)}）"
    )


def paths_for_scene(
    keyword: str,
    sentence: str,
    concept: str,
    settings: Settings,
    illustrator: Optional[Illustrator] = None,
    on_warning: Optional[Callable[[str], None]] = None,
) -> List[str]:
    """取一镜的笔迹，内置简笔画始终作为兜底。

    和标注器同一个策略：AI 配图失败只是「图没那么贴切」，片子仍然完整，
    所以自动退回内置简笔画——但原因要写进任务日志，不是悄悄降级。
    """
    if settings.illustrator == "builtin":
        return BuiltinIllustrator().paths_for(keyword, sentence, concept)

    try:
        return (illustrator or build_illustrator(settings)).paths_for(
            keyword, sentence, concept)
    except IllustrationError as exc:
        message = f"「{keyword}」配图失败，本镜改用内置简笔画：{exc}"
        logger.warning("%s", message)
        if on_warning:
            on_warning(message)
        return BuiltinIllustrator().paths_for(keyword, sentence, concept)
