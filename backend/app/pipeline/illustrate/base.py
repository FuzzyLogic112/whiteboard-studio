"""配图 provider 的统一接口：给一镜画出一组笔迹。

产物是 100x100 viewBox 里的 SVG path 列表，时间片由 `sketch.allocate_strokes`
统一分配——不管笔迹是内置简笔画还是 AI 生图矢量化来的，绘制节奏都一致。
"""

from __future__ import annotations

from typing import List, Protocol


class IllustrationError(RuntimeError):
    """配图失败。"""


class Illustrator(Protocol):
    name: str

    def paths_for(self, keyword: str, sentence: str, concept: str) -> List[str]:
        ...
