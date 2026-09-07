"""tools/indextts_server.py —— 随仓库分发的 IndexTTS HTTP 参考实现。

这里的重点是**客户端和服务端的契约对得上**：用真实的 `IndexTTSHttpProvider`
去打真实起在本地的服务，中间只把模型换成桩。上游不提供 HTTP API，这套接口是
本项目自己定的，两边各写各的最容易悄悄走偏。

服务端跑在 index-tts 的虚拟环境里，测试环境没有 indextts 包——所以
`create_app` 接受注入的合成函数，不碰模型。
"""

from __future__ import annotations

import math
import socket
import struct
import sys
import threading
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path

import pytest
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.indextts_server import create_app  # noqa: E402

from app.pipeline.tts.base import TTSError  # noqa: E402
from app.pipeline.tts.indextts_http import IndexTTSHttpProvider  # noqa: E402

TONE_SECONDS = 1.4


def _write_wav(path: Path, seconds: float = TONE_SECONDS, rate: int = 24000) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"".join(
            struct.pack("<h", int(9000 * math.sin(2 * math.pi * 440 * i / rate)))
            for i in range(int(rate * seconds))
        ))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Stub:
    """替代真实模型，记录被调用时收到了什么。"""

    def __init__(self):
        self.calls = []
        self.fail = False

    def __call__(self, text, reference, speed, out_path):
        self.calls.append({"text": text, "reference": reference, "speed": speed})
        if self.fail:
            raise RuntimeError("CUDA out of memory")
        _write_wav(out_path)


@pytest.fixture
def service(tmp_path):
    voices = tmp_path / "characters"
    voices.mkdir()
    _write_wav(voices / "narrator.wav", 3.0)

    stub = _Stub()
    port = _free_port()
    app = create_app(stub, voices, token="secret")
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    endpoint = f"http://127.0.0.1:{port}"
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{endpoint}/health", timeout=1).read()
            break
        except (urllib.error.URLError, OSError):
            time.sleep(0.05)
    else:
        pytest.fail("服务没起来")

    yield endpoint, stub, voices
    server.should_exit = True
    thread.join(timeout=10)


def _client(endpoint: str, **kwargs) -> IndexTTSHttpProvider:
    defaults = dict(endpoint=endpoint, voice="narrator", api_key="secret")
    return IndexTTSHttpProvider(**{**defaults, **kwargs})


# -- 客户端 ↔ 服务端 --------------------------------------------------------

def test_round_trip(service, tmp_path):
    """真实客户端打真实服务，音频和时长都要对。"""
    endpoint, stub, _ = service
    result = _client(endpoint).synthesize("很多人以为写作是天赋。", tmp_path / "out.wav")

    assert result.audio_path.exists()
    assert abs(result.duration - TONE_SECONDS) < 0.01
    assert stub.calls[0]["text"] == "很多人以为写作是天赋。"
    assert stub.calls[0]["reference"].endswith("narrator.wav")


def test_speed_reaches_the_model(service, tmp_path):
    endpoint, stub, _ = service
    _client(endpoint, speed=1.25).synthesize("你好", tmp_path / "out.wav")
    assert stub.calls[0]["speed"] == 1.25


def test_token_is_enforced(service, tmp_path):
    endpoint, _, _ = service
    with pytest.raises(TTSError, match="401"):
        _client(endpoint, api_key="wrong").synthesize("你好", tmp_path / "out.wav")


def test_unknown_voice_reports_what_is_available(service, tmp_path):
    endpoint, _, _ = service
    with pytest.raises(TTSError, match="404"):
        _client(endpoint, voice="nobody").synthesize("你好", tmp_path / "out.wav")


def test_model_failure_surfaces_as_500(service, tmp_path):
    endpoint, stub, _ = service
    stub.fail = True
    with pytest.raises(TTSError, match="500"):
        _client(endpoint).synthesize("你好", tmp_path / "out.wav")


# -- 服务端自身 -------------------------------------------------------------

def test_health_lists_the_voices(service):
    endpoint, _, _ = service
    import json
    body = json.loads(urllib.request.urlopen(f"{endpoint}/health", timeout=5).read())
    assert body["ok"] is True
    assert body["voices"] == ["narrator"]


def test_non_wav_format_is_refused(service):
    """时长要从音频里精确读出来，所以不做转码。"""
    endpoint, _, _ = service
    import json
    request = urllib.request.Request(
        f"{endpoint}/v1/audio/speech",
        data=json.dumps({"input": "你好", "voice": "narrator",
                         "response_format": "mp3"}).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer secret"},
        method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(request, timeout=5)
    assert exc.value.code == 400


def test_open_service_without_token(tmp_path):
    """没设 token 就不校验，方便本机直接用。"""
    voices = tmp_path / "characters"
    voices.mkdir()
    _write_wav(voices / "v.wav")
    app = create_app(_Stub(), voices, token="")
    from fastapi.testclient import TestClient
    with TestClient(app) as client:
        response = client.post("/v1/audio/speech",
                               json={"input": "你好", "voice": "v"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
