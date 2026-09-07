"""IndexTTS 声音克隆 provider。

对接本地部署的 IndexTTS FastAPI 服务。参考音频只在本机与本机之间传递，
不会上传到任何第三方。

约定的接口（和 IndexTTS 的 FastAPI 示例一致）：

    POST {endpoint}/tts
    {"text": "...", "reference_audio": "/abs/path/to/ref.wav"}
    -> audio/wav 二进制

服务端接口不同时，改这个文件里的 `_request` 即可，上层无感知。
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
import wave
from pathlib import Path

from .base import TTSResult, estimate_duration

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 180


class IndexTTSProvider:
    name = "indextts"

    def __init__(self, endpoint: str, reference_audio: str):
        self.endpoint = endpoint.rstrip("/")
        self.reference_audio = reference_audio

    def synthesize(self, text: str, out_path: Path) -> TTSResult:
        try:
            audio = self._request(text)
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            # 合成失败不该让整条流水线崩掉：退回估算时长，成片仍然出得来，
            # 只是没有声音。日志里说清楚原因即可。
            logger.warning("IndexTTS 合成失败，回退为静音时长估算：%s", exc)
            return TTSResult(duration=estimate_duration(text), audio_path=None)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(audio)
        return TTSResult(duration=_wav_duration(out_path, fallback=estimate_duration(text)),
                         audio_path=out_path)

    def _request(self, text: str) -> bytes:
        payload = json.dumps(
            {"text": text, "reference_audio": self.reference_audio}
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{self.endpoint}/tts",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return resp.read()


def _wav_duration(path: Path, fallback: float) -> float:
    try:
        with wave.open(str(path), "rb") as wav:
            return wav.getnframes() / float(wav.getframerate())
    except (wave.Error, OSError, ZeroDivisionError):
        return fallback
