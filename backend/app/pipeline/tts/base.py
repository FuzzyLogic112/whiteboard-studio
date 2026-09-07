"""语音合成 provider 的统一接口。

只要求两件事：把文本变成音频文件（可以没有），以及给出这段话的时长。
时长是整条流水线的时间基准——分镜多长、笔迹画多快，全看它。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

# 中文口播的经验语速。用于没有真实音频时估算时长。
CHARS_PER_SECOND = 4.5
MIN_SCENE_SECONDS = 1.8
TAIL_PADDING_SECONDS = 0.45


@dataclass
class TTSResult:
    duration: float
    audio_path: Optional[Path] = None


def estimate_duration(text: str) -> float:
    """按字数估算一句中文口播的时长。"""
    spoken = len([c for c in text if not c.isspace()])
    return max(MIN_SCENE_SECONDS, spoken / CHARS_PER_SECOND + TAIL_PADDING_SECONDS)


class TTSProvider(Protocol):
    name: str

    def synthesize(self, text: str, out_path: Path) -> TTSResult:
        ...
