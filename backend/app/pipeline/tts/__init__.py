"""TTS provider 注册表。

    silent          不出音频，只按字数估时长（默认，零依赖）
    indextts_http   调用 OpenAI 兼容的语音服务（社区的 IndexTTS FastAPI 封装）
    indextts_local  在本进程里直接调用 IndexTTS 的 Python API
"""

from __future__ import annotations

import logging
from pathlib import Path

from ...config import Settings
from .base import TTSError, TTSProvider, TTSResult, estimate_duration, wav_duration
from .indextts_http import IndexTTSHttpProvider
from .indextts_local import IndexTTSLocalProvider
from .silent import SilentProvider

logger = logging.getLogger(__name__)

__all__ = [
    "TTSError", "TTSProvider", "TTSResult",
    "estimate_duration", "wav_duration", "get_provider", "PROVIDERS",
]

PROVIDERS = ("silent", "indextts_http", "indextts_local")


class SilentFallback:
    """包一层：合成失败时退回估算时长，让任务继续跑完。

    默认**不**启用。配错了地址或音色名却悄悄出一条没声音的片子，比直接失败
    更难排查——用户往往要等渲染完、点开播放才发现。需要「宁可没声音也别中断
    长任务」的场景，设 WBS_TTS_FALLBACK_SILENT=1 显式打开。
    """

    def __init__(self, inner: TTSProvider):
        self.inner = inner
        self.name = f"{inner.name}+fallback"

    def synthesize(self, text: str, out_path: Path) -> TTSResult:
        try:
            return self.inner.synthesize(text, out_path)
        except TTSError as exc:
            logger.warning("语音合成失败，本镜退回静音：%s", exc)
            return TTSResult(duration=estimate_duration(text), audio_path=None)


def build_provider(settings: Settings) -> TTSProvider:
    """按配置造一个 provider。配置有问题会抛 TTSError。"""
    choice = settings.tts_provider

    if choice == "indextts_http":
        provider: TTSProvider = IndexTTSHttpProvider(
            endpoint=settings.tts_endpoint,
            voice=settings.tts_voice,
            api_key=settings.tts_api_key,
            model=settings.tts_model,
            speed=settings.tts_speed,
            timeout=settings.tts_timeout,
        )
    elif choice == "indextts_local":
        provider = IndexTTSLocalProvider(
            checkpoints=settings.indextts_checkpoints,
            reference_audio=settings.indextts_reference,
            lang=settings.indextts_lang,
            speed=settings.tts_speed,
        )
    elif choice == "silent":
        return SilentProvider()
    else:
        raise TTSError(f"未知的 TTS provider：{choice}（可选 {', '.join(PROVIDERS)}）")

    return SilentFallback(provider) if settings.tts_fallback_silent else provider


def get_provider(settings: Settings) -> TTSProvider:
    return build_provider(settings)
