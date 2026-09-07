"""关键词提取。

刻意不依赖 jieba 之类的分词器：中文分词库体积大、安装经常出问题，而这里
只需要从一句话里挑出一个「画得出来」的词。

做法分三步：
1. 把虚词和标点当作切分点，得到候选实词片段；
2. 片段过长时再枚举其中 2~4 字的窗口（中文名词中心语通常靠后）；
3. 按「字数 × 全文词频 × 是否在别处独立成段」打分，取最高的。

第 3 步的「独立成段」是个便宜但有效的信号：如果「写作」在文稿别处正好被
虚词夹成一个完整片段，那它多半真的是个词，而不是切错的碎片。

想换成真正的分词或大模型抽取，替换 `extract_keywords` 即可，签名保持不变。
"""

from __future__ import annotations

import math
import re
from typing import Dict, Iterable, List, Set

# 虚词 / 高频功能词。按长度倒序匹配，避免「因为」被拆成「因」+「为」。
STOPWORDS = [
    "接下来", "也就是说", "换句话说", "举个例子", "换言之",
    "我们", "你们", "他们", "她们", "它们", "咱们", "自己",
    "因为", "所以", "但是", "然后", "如果", "虽然", "并且", "而且",
    "这个", "那个", "这些", "那些", "什么", "怎么", "为什么", "怎样",
    "可以", "能够", "需要", "应该", "必须", "已经", "正在", "还是",
    "一个", "一种", "一样", "一直", "非常", "特别", "其实", "真的",
    "首先", "其次", "最后", "同时", "此外", "另外", "总之", "比如",
    "以为", "认为", "觉得", "知道", "只要", "只有", "无论", "不管",
    "的", "了", "是", "在", "和", "与", "或", "就", "都", "而", "及",
    "上", "下", "不", "也", "到", "会", "把", "被", "让", "使", "给",
    "却", "还", "又", "再", "最", "更", "太", "只", "才", "过", "着",
    "呢", "吧", "啊", "吗", "呀", "等", "之", "其", "对", "于", "从",
    "有", "这", "那", "我", "你", "他", "她", "它", "很", "要", "说",
    "谁", "每", "各", "些", "来", "去", "将", "得", "地", "所",
    "仍然", "现在", "过去", "今天", "明天", "未来", "一些", "许多",
    # 注意：「能」不列为虚词，否则「人工智能」「性能」会被从中切断
]
_STOP_PATTERN = re.compile("|".join(sorted(STOPWORDS, key=len, reverse=True)))
# 非内容字符：标点、数字、空白
_NOISE = re.compile(r"[\s，。、！？；：·…—\-「」『』（）()《》〈〉“”‘’\"'0-9０-９%％]+")

# 字数权重：2~4 字最适合写在白板上，1 字太单薄，5 字以上写不下
_LEN_WEIGHT: Dict[int, float] = {1: 0.5, 2: 1.9, 3: 2.6, 4: 3.0}

# 几乎不会出现在词首/词尾的字。切窗口时难免切出「能进步」「设计的」这类
# 半截短语，用一个固定折扣把它们压下去，让干净的「进步」「设计」胜出。
_BAD_HEAD = set("能来去被让使把给向更才就又再也很都还并即则")
_BAD_TAIL = set("的地得和与或而及是在了把被让使")
_EDGE_PENALTY = 0.55


def _fragments(text: str) -> List[str]:
    """按虚词与标点切开，得到候选实词片段。"""
    out: List[str] = []
    for piece in _NOISE.split(text):
        for frag in _STOP_PATTERN.split(piece):
            frag = frag.strip()
            if frag:
                out.append(frag)
    return out


def _windows(fragment: str) -> Iterable[str]:
    """片段本身 + 其中 2~4 字的滑动窗口。"""
    n = len(fragment)
    yield fragment
    if n <= 2:
        return
    for size in (4, 3, 2):
        if size >= n:
            continue
        for start in range(n - size + 1):
            yield fragment[start:start + size]


def _score(candidate: str, corpus: str, word_like: Set[str], position: float) -> float:
    # 切在词中间的半截短语（「能进步」「设计的」）不算真词，也拿不到独立成段加成
    bad_edge = len(candidate) > 1 and (candidate[0] in _BAD_HEAD or candidate[-1] in _BAD_TAIL)

    score = _LEN_WEIGHT.get(len(candidate), 1.0)
    # 全文重复出现的词更可能是主题词
    score *= 1.0 + 0.35 * math.log(corpus.count(candidate) + 1)
    # 在别处独立成段 => 大概率是个真词
    if candidate in word_like and not bad_edge:
        score *= 1.6
    # 同分时偏向靠后的窗口：中文短语的中心语通常在尾部
    score *= 1.0 + 0.08 * position
    if bad_edge:
        score *= _EDGE_PENALTY
    return score


def extract_keywords(sentences: List[str]) -> List[str]:
    """批量提取，并尽量避免相邻镜头重复同一个关键词。"""
    corpus = "".join(sentences)
    word_like = {f for f in _fragments(corpus) if 2 <= len(f) <= 4}

    result: List[str] = []
    for sentence in sentences:
        scored: List[tuple[float, str]] = []
        for fragment in _fragments(sentence):
            n = len(fragment)
            for cand in dict.fromkeys(_windows(fragment)):  # 去重且保持顺序
                position = fragment.rfind(cand) / max(1, n - len(cand)) if n > len(cand) else 1.0
                scored.append((_score(cand, corpus, word_like, position), cand))
        scored.sort(reverse=True)

        chosen = ""
        for _, cand in scored:
            if not result or cand != result[-1]:
                chosen = cand
                break
        result.append(chosen or sentence.strip()[:4] or "要点")
    return result


def extract_keyword(sentence: str) -> str:
    """单句版本，供调试与外部调用。"""
    return extract_keywords([sentence])[0]
