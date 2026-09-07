"""TTS provider 的行为约束。

HTTP provider 对着一个真的起在本地的 mock 服务器测——它实现的是和社区
IndexTTS 封装同一套 OpenAI 兼容契约，所以这些用例能挡住契约写错的问题，
不需要真的把 0.8B 模型跑起来。
"""

from __future__ import annotations

import dataclasses
import json
import math
import struct
import threading
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from app.config import load_settings
from app.pipeline.tts import SilentFallback, build_provider
from app.pipeline.tts.base import MIN_SCENE_SECONDS, TTSError, estimate_duration
from app.pipeline.tts.indextts_http import IndexTTSHttpProvider

TONE_SECONDS = 1.5
SAMPLE_RATE = 24000


def _sine_wav(path: Path, seconds: float = TONE_SECONDS) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(b"".join(
            struct.pack("<h", int(9000 * math.sin(2 * math.pi * 440 * i / SAMPLE_RATE)))
            for i in range(int(SAMPLE_RATE * seconds))
        ))


class _Handler(BaseHTTPRequestHandler):
    """最小的 OpenAI 兼容语音服务。behaviour 由 server.mode 决定。"""

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler 的约定
        mode = self.server.mode
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.server.last_request = json.loads(body)
        self.server.last_auth = self.headers.get("Authorization")

        if self.path != "/v1/audio/speech":
            self.send_error(404, "unknown path")
            return
        if mode == "http_error":
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"detail":"bad token"}')
            return
        if mode == "empty":
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if mode == "not_wav":
            payload = b"ID3 this is an mp3, not a wav"
        else:
            tmp = Path(self.server.tmpdir) / "tone.wav"
            _sine_wav(tmp)
            payload = tmp.read_bytes()

        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # 测试输出别被访问日志淹没
        pass


@pytest.fixture
def server(tmp_path):
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    httpd.mode = "ok"
    httpd.tmpdir = str(tmp_path)
    httpd.last_request = None
    httpd.last_auth = None
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def _provider(server, **kwargs) -> IndexTTSHttpProvider:
    host, port = server.server_address
    defaults = dict(endpoint=f"http://{host}:{port}", voice="narrator", api_key="secret")
    return IndexTTSHttpProvider(**{**defaults, **kwargs})


# -- HTTP provider ----------------------------------------------------------

def test_duration_comes_from_the_returned_wav(server, tmp_path):
    result = _provider(server).synthesize("测试文本", tmp_path / "out.wav")
    assert result.audio_path == tmp_path / "out.wav"
    assert result.audio_path.exists()
    # 时长必须来自音频本身，不能退回字数估算
    assert abs(result.duration - TONE_SECONDS) < 0.01
    assert result.duration != estimate_duration("测试文本")


def test_sends_openai_compatible_payload(server, tmp_path):
    _provider(server).synthesize("你好世界", tmp_path / "out.wav")
    assert server.last_request == {
        "model": "IndexTTS",
        "input": "你好世界",
        "voice": "narrator",
        "response_format": "wav",   # 固定 wav，否则读不出精确时长
        "speed": 1.0,
    }
    assert server.last_auth == "Bearer secret"


def test_api_key_is_optional(server, tmp_path):
    _provider(server, api_key="").synthesize("你好", tmp_path / "out.wav")
    assert server.last_auth is None


def test_http_error_surfaces_status_and_body(server, tmp_path):
    server.mode = "http_error"
    with pytest.raises(TTSError, match="401"):
        _provider(server).synthesize("你好", tmp_path / "out.wav")


def test_empty_response_is_an_error(server, tmp_path):
    server.mode = "empty"
    with pytest.raises(TTSError, match="空响应"):
        _provider(server).synthesize("你好", tmp_path / "out.wav")


def test_non_wav_response_is_an_error(server, tmp_path):
    server.mode = "not_wav"
    with pytest.raises(TTSError, match="wav"):
        _provider(server).synthesize("你好", tmp_path / "out.wav")


def test_unreachable_endpoint_is_an_error(tmp_path):
    provider = IndexTTSHttpProvider(endpoint="http://127.0.0.1:1", voice="narrator")
    with pytest.raises(TTSError, match="连接语音服务失败"):
        provider.synthesize("你好", tmp_path / "out.wav")


@pytest.mark.parametrize("missing", ["endpoint", "voice"])
def test_missing_required_config_fails_fast(missing):
    kwargs = {"endpoint": "http://localhost:8100", "voice": "narrator", missing: ""}
    with pytest.raises(TTSError, match="WBS_TTS_"):
        IndexTTSHttpProvider(**kwargs)


# -- 失败策略 ---------------------------------------------------------------

def test_failure_is_loud_by_default(server, tmp_path):
    """配错了不该悄悄出一条没声音的片子。"""
    server.mode = "http_error"
    with pytest.raises(TTSError):
        _provider(server).synthesize("你好", tmp_path / "out.wav")


def test_fallback_wrapper_degrades_to_estimated_duration(server, tmp_path):
    server.mode = "http_error"
    wrapped = SilentFallback(_provider(server))
    result = wrapped.synthesize("你好", tmp_path / "out.wav")
    assert result.audio_path is None
    assert result.duration == estimate_duration("你好")
    assert result.duration == MIN_SCENE_SECONDS


# -- 注册表 -----------------------------------------------------------------

def _settings(**overrides):
    return dataclasses.replace(load_settings(), **overrides)


def test_default_provider_is_silent():
    assert build_provider(_settings(tts_provider="silent")).name == "silent"


def test_unknown_provider_name_is_rejected():
    with pytest.raises(TTSError, match="未知的 TTS provider"):
        build_provider(_settings(tts_provider="whisper"))


def test_http_provider_is_built_from_settings():
    provider = build_provider(_settings(
        tts_provider="indextts_http", tts_endpoint="http://x:1", tts_voice="v"))
    assert provider.name == "indextts_http"


def test_fallback_flag_wraps_the_provider():
    provider = build_provider(_settings(
        tts_provider="indextts_http", tts_endpoint="http://x:1", tts_voice="v",
        tts_fallback_silent=True))
    assert provider.name == "indextts_http+fallback"


def test_local_provider_reports_missing_reference_audio():
    with pytest.raises(TTSError, match="WBS_INDEXTTS_REFERENCE"):
        build_provider(_settings(tts_provider="indextts_local", indextts_reference=""))
