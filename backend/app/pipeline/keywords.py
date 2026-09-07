"""关键词提取：从一句话里挑出最适合写在白板上的那个词。

先分词（见 segment.py），再按「词性 × 字数 × 全文词频」给每个词打分。

相邻的词会尝试合并成一个候选：「架构」+「设计」→「架构设计」，
「三件」+「事」→「三件事」。中文里这类复合词很多，而词典收不全，
不合并的话白板上就只剩半个概念。

词性只用来加权，不用来做硬过滤——词典里的标注有噪声（比如「进步」被标成
副词 d），一刀切会误杀。真正的虚词靠「词性权重低 + 字数少」自然沉底。
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Dict, List, Sequence, Tuple

from .segment import Word, segment

# 词性权重。名词最适合画，动名词次之，纯虚词沉底。
POS_WEIGHT: Dict[str, float] = {
    "n": 1.0, "nz": 1.0, "ng": 0.9, "nl": 0.95,      # 名词
    "vn": 0.98, "an": 0.95,                           # 动名词 / 形名词
    "i": 0.9, "l": 0.88, "j": 0.85,                   # 成语 / 习用语 / 简称
    "s": 0.8, "nrfg": 0.7,
    "v": 0.75, "vd": 0.6, "vg": 0.6,                  # 动词
    "a": 0.6, "ad": 0.5, "ag": 0.5, "b": 0.6,         # 形容词 / 区别词
    "d": 0.5,                                          # 副词：词典有噪声，压低而不是丢掉
    "m": 0.25, "mq": 0.25, "q": 0.2, "t": 0.3, "f": 0.3,
}
# 明确的功能词，直接排除
DROP_POS = frozenset({
    "r", "p", "c", "u", "uj", "ul", "uz", "ug", "ud", "uv", "df",
    "w", "y", "e", "o", "h", "k", "x", "xc", "zg", "z",
})
DEFAULT_POS_WEIGHT = 0.55

# 字数权重：2~4 字最适合写在白板上，单字太单薄
LEN_WEIGHT: Dict[int, float] = {1: 0.30, 2: 1.0, 3: 1.12, 4: 1.20}

# 词性对但没有信息量的词
BLACKLIST = frozenset({
    "东西", "时候", "方面", "样子", "地方", "一些", "什么", "怎么", "这样",
    "那样", "起来", "出来", "下来", "上去", "而已", "之类", "等等", "一样",
    "本身", "以及", "各种", "整个", "部分", "一点", "很多", "许多",
    # 词性对但没有画面感的轻动词
    "需要", "进行", "具有", "表示", "成为", "属于", "存在", "作为",
})

MAX_KEYWORD_LEN = 4
MERGE_BONUS = 1.06
# 跨分镜反复出现的词更可能是主题词。系数不宜太大——否则一个高频动词会盖过
# 每一镜自己的名词，整条片子的关键词就全变成同一个了。
DOC_FREQ_WEIGHT = 0.5

# 合并的约束：中文复合词的中心语在右边，所以右侧必须是名词性的，
# 左侧只能是修饰成分。少了这条约束就会拼出「需要手写」「现在模型」这种东西。
MERGE_HEAD_POS = ("n", "vn", "an")                      # 可以当中心语
MERGE_MODIFIER_POS = ("n", "vn", "an", "a", "b", "j", "s")  # 可以当修饰语
MERGE_QUANTIFIER_POS = ("m", "mq", "q")                 # 数量短语


def _weight(pos: str) -> float:
    return POS_WEIGHT.get(pos, DEFAULT_POS_WEIGHT)


def _candidates(words: Sequence[Word]) -> List[Tuple[str, float]]:
    """单个词 + 相邻词合并，返回 (候选词, 词性权重)。"""
    out: List[Tuple[str, float]] = []

    for word in words:
        if word.pos in DROP_POS or word.text in BLACKLIST:
            continue
        out.append((word.text, _weight(word.pos)))

    for left, right in zip(words, words[1:]):
        if left.pos in DROP_POS or right.pos in DROP_POS:
            continue
        # 组成部分被拉黑，合并结果同样没有信息量（「很多」+「人」）
        if left.text in BLACKLIST or right.text in BLACKLIST:
            continue
        merged = left.text + right.text
        if len(merged) > MAX_KEYWORD_LEN or merged in BLACKLIST:
            continue
        if not right.pos.startswith(MERGE_HEAD_POS):
            continue  # 右边不是名词性的，拼出来不是一个概念

        modifier = left.pos.startswith(MERGE_MODIFIER_POS) and len(left.text) >= 2
        # 数量短语 + 名词是中文里极常见的搭配：「三件事」「一行代码」
        quantified = left.pos in MERGE_QUANTIFIER_POS
        if not (modifier or quantified):
            continue

        weight = max(_weight(left.pos), _weight(right.pos)) * MERGE_BONUS
        out.append((merged, weight))

    return out


def extract_keywords(sentences: List[str]) -> List[str]:
    """批量提取，并尽量避免相邻镜头重复同一个关键词。"""
    per_sentence = [_candidates(segment(s)) for s in sentences]

    # 主题性信号用「文档频率」——出现在多少个分镜里，而不是总共出现多少次。
    # 一句话里重复三遍的词不代表它是主题，跨分镜反复出现才是。
    #
    # 注意合并出来的候选也要统计进去：只统计分词结果的话，「三次会议」这类
    # 合并词的频率永远是 0，会被单个词的频率加成系统性压过去。
    doc_freq = Counter(
        text for candidates in per_sentence for text in {t for t, _ in candidates}
    )

    result: List[str] = []
    for sentence, candidates in zip(sentences, per_sentence):
        scored: List[Tuple[float, str]] = []
        for text, pos_weight in candidates:
            score = pos_weight * LEN_WEIGHT.get(len(text), 0.5)
            score *= 1.0 + DOC_FREQ_WEIGHT * math.log(doc_freq[text] + 1)
            scored.append((score, text))
        scored.sort(reverse=True)

        chosen = ""
        for _, text in scored:
            if not result or text != result[-1]:
                chosen = text
                break
        result.append(chosen or sentence.strip()[:MAX_KEYWORD_LEN] or "要点")
    return result


def extract_keyword(sentence: str) -> str:
    """单句版本，供调试与外部调用。"""
    return extract_keywords([sentence])[0]
