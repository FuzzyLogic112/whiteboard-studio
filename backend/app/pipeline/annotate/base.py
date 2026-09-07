"""分镜标注：给每一镜定关键词和简笔画。

抽出这一层是因为「挑词」和「选图」本质是同一个判断——看懂这句话在讲什么。
本地启发式把它拆成了两步（分词打分 + 触发词匹配），大模型则一次就能做完，
而且能在语义上从概念表里选，不依赖触发词命中。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Protocol, Sequence


class AnnotationError(RuntimeError):
    """标注失败。"""


@dataclass
class SceneAnnotation:
    keyword: str
    concept: str


class Annotator(Protocol):
    name: str

    def annotate(self, sentences: Sequence[str]) -> List[SceneAnnotation]:
        ...
