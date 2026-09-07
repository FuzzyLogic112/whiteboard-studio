"""TTS provider 注册表。"""

from __future__ import annotations

from ...config import Settings
from .base import TTSProvider, TTSResult, estimate_duration
from .indextts import IndexTTSProvider
from .silent import SilentProvider

__all__ = ["TTSProvider", "TTSResult", "estimate_duration", "get_provider"]


def get_provider(settings: Settings) -> TTSProvider:
    if settings.tts_provider == "indextts":
        return IndexTTSProvider(settings.indextts_endpoint, settings.indextts_reference)
    return SilentProvider()
