"""文稿分镜：把一段中文文稿切成适合逐个画面呈现的短句。

规则很朴素，但对中文口播稿足够稳：先按句末标点断句，过长的句子再按逗号
切成小块，过短的碎片并回上一镜。之所以不直接按字数硬切，是因为字幕断在
句子中间会明显影响观感。
"""

from __future__ import annotations

import re
from typing import List

# 句末标点：在这里断开一定是安全的
SENTENCE_END = "。！？!?；;…"
# 句中停顿：只在句子过长时才在这里断开
CLAUSE_BREAK = "，,、：:"

MAX_CHARS = 20  # 单镜头字数上限，超过就再切（字幕一行放得下的量）
MIN_CHARS = 6   # 单镜头字数下限，不足就并回上一镜


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 折叠空白，但保留换行（换行是作者显式的分段意图）
    text = re.sub(r"[ \t　]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _split_sentences(paragraph: str) -> List[str]:
    out: List[str] = []
    buf = ""
    for ch in paragraph:
        buf += ch
        if ch in SENTENCE_END:
            out.append(buf.strip())
            buf = ""
    if buf.strip():
        out.append(buf.strip())
    return [s for s in out if s]


def _split_long(sentence: str) -> List[str]:
    """把过长的句子按句中停顿切成不超过 MAX_CHARS 的小块。"""
    if len(sentence) <= MAX_CHARS:
        return [sentence]

    parts: List[str] = []
    buf = ""
    for ch in sentence:
        buf += ch
        if ch in CLAUSE_BREAK and len(buf) >= MIN_CHARS:
            parts.append(buf)
            buf = ""
    if buf:
        parts.append(buf)

    # 逗号切完仍然过长（比如一句话里根本没有逗号），只能硬切
    chunks: List[str] = []
    for part in parts:
        while len(part) > MAX_CHARS:
            chunks.append(part[:MAX_CHARS])
            part = part[MAX_CHARS:]
        if part:
            chunks.append(part)
    return chunks


def _merge_short(chunks: List[str]) -> List[str]:
    merged: List[str] = []
    for chunk in chunks:
        if merged and len(chunk) < MIN_CHARS and len(merged[-1]) + len(chunk) <= MAX_CHARS + MIN_CHARS:
            merged[-1] += chunk
        else:
            merged.append(chunk)
    # 首块过短时并入后一块，避免开场一闪而过
    if len(merged) > 1 and len(merged[0]) < MIN_CHARS:
        merged[1] = merged[0] + merged[1]
        merged.pop(0)
    return merged


def split_script(text: str) -> List[str]:
    """文稿 -> 分镜文本列表。

    按段落逐段处理：换行是作者显式的分段意图，短句可以并回上一镜，但不能
    跨段合并——那会把两个不相干的意思塞进同一个画面。
    """
    normalized = _normalize(text)
    if not normalized:
        return []

    scenes: List[str] = []
    for paragraph in normalized.split("\n"):
        if not paragraph.strip():
            continue
        chunks: List[str] = []
        for sentence in _split_sentences(paragraph):
            chunks.extend(_split_long(sentence))
        scenes.extend(c.strip() for c in _merge_short(chunks) if c.strip())
    return scenes
