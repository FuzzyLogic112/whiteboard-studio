"""通过 HTTP 调用 IndexTTS。

**上游的 index-tts 仓库本身不提供 HTTP API**，只有 Gradio webui、Python API
和 vLLM recipe。所以这个 provider 面向的是社区的 FastAPI 封装
（如 csllpr/index-tts-fastapi），它们普遍实现 OpenAI 兼容的语音接口：

    POST {endpoint}/v1/audio/speech
    Authorization: Bearer <token>
    {"model": "IndexTTS", "input": "要合成的文本",
     "voice": "参考音色名", "response_format": "wav", "speed": 1.0}
    -> audio/wav 二进制

选这个契约而不是自定义一套，是因为它是事实标准：任何 OpenAI 兼容的 TTS
服务（不止 IndexTTS）都能直接接上。

`voice` 是音色名而不是文件路径——这类封装约定把参考音频放在服务端的
`characters/` 目录下，用不带扩展名的文件名引用。参考音频始终留在跑模型的
那台机器上，不经过本进程。

固定要 wav：时长是整条流水线的时间基准，必须能精确读出来。
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from pathlib import Path

from .base import TTSError, TTSResult, wav_duration

logger = logging.getLogger(__name__)


class IndexTTSHttpProvider:
    name = "indextts_http"

    def __init__(self, endpoint: str, voice: str, api_key: str = "",
                 model: str = "IndexTTS", speed: float = 1.0, timeout: int = 180):
        if not endpoint:
            raise TTSError("indextts_http 需要配置 WBS_TTS_ENDPOINT")
        if not voice:
            raise TTSError("indextts_http 需要配置 WBS_TTS_VOICE（服务端 characters/ 下的音色名）")
        self.endpoint = endpoint.rstrip("/")
        self.voice = voice
        self.api_key = api_key
        self.model = model
        self.speed = speed
        self.timeout = timeout

    def synthesize(self, text: str, out_path: Path) -> TTSResult:
        payload = json.dumps({
            "model": self.model,
            "input": text,
            "voice": self.voice,
            "response_format": "wav",
            "speed": self.speed,
        }).encode("utf-8")

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = urllib.request.Request(
            f"{self.endpoint}/v1/audio/speech", data=payload, headers=headers, method="POST"
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                audio = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:400].decode("utf-8", "replace")
            raise TTSError(f"语音服务返回 {exc.code}：{detail}") from exc
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            raise TTSError(f"连接语音服务失败（{self.endpoint}）：{exc}") from exc

        if not audio:
            raise TTSError("语音服务返回了空响应")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(audio)
        return TTSResult(duration=wav_duration(out_path), audio_path=out_path)
