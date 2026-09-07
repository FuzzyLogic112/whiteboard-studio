"""本地标注器：分词打分挑关键词 + 触发词选简笔画。

不需要任何外部服务，也是大模型标注器失败时的兜底。
"""

from __future__ import annotations

from typing import List, Sequence

from .. import keywords, sketch
from .base import SceneAnnotation


class LocalAnnotator:
    name = "local"

    def annotate(self, sentences: Sequence[str]) -> List[SceneAnnotation]:
        sentence_list = list(sentences)
        words = keywords.extract_keywords(sentence_list)
        concepts = sketch.pick_concepts(words, sentence_list)
        return [SceneAnnotation(keyword=k, concept=c) for k, c in zip(words, concepts)]
