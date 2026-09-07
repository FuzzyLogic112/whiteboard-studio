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
    # 一句具体可画的视觉隐喻，交给生图模型。本地标注器给不出，留空。
    #
    # 直接把关键词丢给生图模型是不行的：口播稿里的关键词大多是抽象的，
    # 「天赋」「修改」没有视觉形态，模型要么瞎画，要么干脆把这两个字写出来
    # ——实测 cogview-4 对「天赋」画出了手写英文单词，对「修改」画出了人脸。
    # 把抽象概念翻译成具体物件，本来就是插画师干的事，正好交给语言模型。
    image_prompt: str = ""


class Annotator(Protocol):
    name: str

    def annotate(self, sentences: Sequence[str]) -> List[SceneAnnotation]:
        ...
