"""语音合成 provider 的统一接口。

只要求两件事：把文本变成音频文件（可以没有），以及给出这段话的时长。
时长是整条流水线的时间基准——分镜多长、笔迹画多快、字幕停多久，全看它。
"""

from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

# 中文口播的经验语速。用于没有真实音频时估算时长。
CHARS_PER_SECOND = 4.5
MIN_SCENE_SECONDS = 1.8
TAIL_PADDING_SECONDS = 0.45


class TTSError(RuntimeError):
    """合成失败。默认会让整个任务失败，而不是悄悄出一条没声音的片子。"""


@dataclass
class TTSResult:
    duration: float
    audio_path: Optional[Path] = None


def estimate_duration(text: str) -> float:
    """按字数估算一句中文口播的时长。"""
    spoken = len([c for c in text if not c.isspace()])
    return max(MIN_SCENE_SECONDS, spoken / CHARS_PER_SECOND + TAIL_PADDING_SECONDS)


def wav_duration(path: Path) -> float:
    """读 wav 头拿真实时长。

    只支持 wav 是有意的：时长是整条流水线的时间基准，必须精确。mp3 的时长
    要解码才知道，所以 HTTP provider 固定要求服务端返回 wav。
    """
    try:
        with wave.open(str(path), "rb") as wav:
            rate = wav.getframerate()
            if rate <= 0:
                raise TTSError(f"音频采样率非法：{path}")
            return wav.getnframes() / float(rate)
    except wave.Error as exc:
        raise TTSError(f"返回的音频不是合法 wav：{path}（{exc}）") from exc
    except OSError as exc:
        raise TTSError(f"读取音频失败：{path}（{exc}）") from exc


class TTSProvider(Protocol):
    name: str

    def synthesize(self, text: str, out_path: Path) -> TTSResult:
        ...
