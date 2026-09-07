"""不生成音频，只估算时长。

默认 provider：不需要任何模型、API key 或网络，装完依赖就能出片。
适合先把画面和节奏调对，再接真正的声音克隆。
"""

from __future__ import annotations

from pathlib import Path

from .base import TTSResult, estimate_duration


class SilentProvider:
    name = "silent"

    def synthesize(self, text: str, out_path: Path) -> TTSResult:
        return TTSResult(duration=estimate_duration(text), audio_path=None)
