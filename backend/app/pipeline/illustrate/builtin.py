"""内置简笔画：32 个概念 + 关键词哈希涂鸦兜底。零依赖。"""

from __future__ import annotations

from typing import List

from ..sketch import paths_for_concept


class BuiltinIllustrator:
    name = "builtin"

    def paths_for(self, keyword: str, sentence: str, concept: str) -> List[str]:
        return paths_for_concept(concept, keyword)
