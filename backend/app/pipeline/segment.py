"""中文分词。

用的是最大概率分词（和 jieba 的核心算法同一个思路）：先按词典把句子铺成
一张有向无环图，每条边是一个候选词，边权是这个词的对数词频；再从右往左做
一次动态规划，取总概率最大的那条路径。未登录的单字给一个最低词频兜底。

为什么不直接依赖 jieba：它的 setup.py 在新版 pip 下构建失败（本项目搭建时
就撞上了）。但它的词典是 MIT 的，可以单独拿来用——`data/zh_words.txt.gz`
就是从 jieba 的 dict.txt 裁出来的，去掉了人名地名和低频词，6.4 万条、369KB。
算法本身四十行，自己写比拖一个装不上的依赖划算。

词性标注直接来自词典，没有做基于上下文的消歧：一个词有多个词性时取词典里
记的那个。对「挑一个能画在白板上的词」这个用途，够用。
"""

from __future__ import annotations

import gzip
import math
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, NamedTuple, Tuple

DICT_PATH = Path(__file__).parent / "data" / "zh_words.txt.gz"

# 未登录单字的兜底词频。比词典里最低频的词还低，保证「有词典条目就优先成词」。
UNKNOWN_FREQ = 1


class Word(NamedTuple):
    text: str
    pos: str


class _Lexicon(NamedTuple):
    freq: Dict[str, int]
    pos: Dict[str, str]
    log_total: float
    max_word_len: int


@lru_cache(maxsize=1)
def _lexicon() -> _Lexicon:
    """加载词典。约 6.4 万条，解压 + 建表约 100ms，只做一次。"""
    freq: Dict[str, int] = {}
    pos: Dict[str, str] = {}
    if not DICT_PATH.exists():
        raise FileNotFoundError(
            f"词典缺失：{DICT_PATH}。它随仓库一起分发，请检查工作副本是否完整。"
        )
    with gzip.open(DICT_PATH, "rt", encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            if len(parts) != 3:
                continue
            word, count, tag = parts
            freq[word] = int(count)
            pos[word] = tag
    total = sum(freq.values())
    return _Lexicon(
        freq=freq,
        pos=pos,
        log_total=math.log(total),
        max_word_len=max(len(w) for w in freq),
    )


def _log_prob(word: str, lex: _Lexicon) -> float:
    return math.log(lex.freq.get(word, UNKNOWN_FREQ)) - lex.log_total


def _cut_block(block: str, lex: _Lexicon) -> List[str]:
    """对一段连续的汉字做最大概率切分。"""
    n = len(block)
    # route[i] = (从 i 到结尾的最大对数概率, 第一个词的结束位置)
    route: List[Tuple[float, int]] = [(0.0, 0)] * (n + 1)
    for i in range(n - 1, -1, -1):
        best = (-math.inf, i + 1)
        limit = min(n, i + lex.max_word_len)
        for j in range(i + 1, limit + 1):
            candidate = block[i:j]
            # 单字总是允许成词（兜底），多字必须在词典里
            if j - i > 1 and candidate not in lex.freq:
                continue
            score = _log_prob(candidate, lex) + route[j][0]
            if score > best[0]:
                best = (score, j)
        route[i] = best

    words: List[str] = []
    i = 0
    while i < n:
        j = route[i][1]
        words.append(block[i:j])
        i = j
    return words


def segment(text: str) -> List[Word]:
    """把一段文本切成带词性的词。非汉字（标点、数字、字母）按连续块单独成词。"""
    lex = _lexicon()
    out: List[Word] = []
    block = ""

    def flush() -> None:
        nonlocal block
        if block:
            out.extend(Word(w, lex.pos.get(w, "x")) for w in _cut_block(block, lex))
            block = ""

    for ch in text:
        if "一" <= ch <= "鿿":
            block += ch
        else:
            flush()
            if not ch.isspace():
                out.append(Word(ch, "w"))  # w = 标点/符号
    flush()
    return out


def words_of(text: str) -> List[str]:
    """只要切分结果，不要词性。"""
    return [w.text for w in segment(text)]
