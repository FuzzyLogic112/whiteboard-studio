"""进程内 IndexTTS provider。

桩类的 `infer` 签名**逐字抄自上游源码**（indextts/infer_v2_5.py、infer_v2.py、
infer.py），所以这些用例能真正挡住参数名写错的问题，不需要下 0.8B 模型。

三个版本的签名差异恰恰是最容易踩的坑：
  infer_v2_5.IndexTTS2.infer(spk_audio_prompt, text, output_path, lang, ...)
      ↑ lang 是**必填位置参数**
  infer_v2.IndexTTS2.infer(spk_audio_prompt, text, output_path, ...)
      ↑ 根本没有 lang，也没有 duration_factor
  infer.IndexTTS.infer(audio_prompt, text, output_path, ...)
      ↑ 参考音频参数叫 audio_prompt，不是 spk_audio_prompt
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

import pytest

from app.pipeline.tts.base import TTSError
from app.pipeline.tts.indextts_local import IndexTTSLocalProvider


def _write_wav(path: str, seconds: float = 1.25, rate: int = 24000) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"".join(
            struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate)))
            for i in range(int(rate * seconds))
        ))


class _Recorder:
    def __init__(self):
        self.calls = []
        self.loads = 0


class V25Stub:
    """签名抄自 indextts/infer_v2_5.py 的 IndexTTS2。"""

    def __init__(self, cfg_path="checkpoints/config.yaml", model_dir="checkpoints",
                 use_bf16=False, device=None, use_cuda_kernel=None, use_deepspeed=False,
                 use_accel=False, use_torch_compile=False, use_qwen_emo=False):
        recorder.loads += 1

    def infer(self, spk_audio_prompt, text, output_path, lang,
              emo_audio_prompt=None, emo_alpha=1.0, emo_vector=None,
              use_emo_text=False, emo_text=None, use_random=False,
              interval_silence=200, verbose=False, max_text_tokens_per_segment=120,
              stream_return=False, more_segment_before=0, duration_factor=1.0,
              text_normalization=True):
        recorder.calls.append(dict(spk_audio_prompt=spk_audio_prompt, text=text,
                                   lang=lang, duration_factor=duration_factor))
        _write_wav(output_path)


class V2Stub:
    """签名抄自 indextts/infer_v2.py 的 IndexTTS2：没有 lang，也没有 duration_factor。"""

    def __init__(self, cfg_path="checkpoints/config.yaml", model_dir="checkpoints",
                 use_fp16=False, device=None, use_cuda_kernel=None, use_deepspeed=False,
                 use_accel=False, use_torch_compile=False, use_qwen_emo=True,
                 aux_paths=None):
        recorder.loads += 1

    def infer(self, spk_audio_prompt, text, output_path, emo_audio_prompt=None,
              emo_alpha=1.0, emo_vector=None, use_emo_text=False, emo_text=None,
              use_random=False, interval_silence=200, verbose=False,
              max_text_tokens_per_segment=120, stream_return=False,
              more_segment_before=0):
        recorder.calls.append(dict(spk_audio_prompt=spk_audio_prompt, text=text))
        _write_wav(output_path)


class V1Stub:
    """签名抄自 indextts/infer.py 的 IndexTTS：参考音频叫 audio_prompt。"""

    def __init__(self, cfg_path="checkpoints/config.yaml", model_dir="checkpoints",
                 use_fp16=True, device=None, use_cuda_kernel=None):
        recorder.loads += 1

    def infer(self, audio_prompt, text, output_path, verbose=False,
              max_text_tokens_per_segment=120):
        recorder.calls.append(dict(audio_prompt=audio_prompt, text=text))
        _write_wav(output_path)


class WrongStub:
    def __init__(self, cfg_path=None, model_dir=None):
        recorder.loads += 1

    def infer(self, some_other_name, text, output_path):
        _write_wav(output_path)


class ExplodingStub:
    def __init__(self, cfg_path=None, model_dir=None):
        recorder.loads += 1

    def infer(self, spk_audio_prompt, text, output_path, lang):
        raise RuntimeError("CUDA out of memory")


class SilentStub:
    """跑完了但没产出文件。"""

    def __init__(self, cfg_path=None, model_dir=None):
        recorder.loads += 1

    def infer(self, spk_audio_prompt, text, output_path, lang):
        return None


recorder = _Recorder()


@pytest.fixture(autouse=True)
def reset_recorder():
    global recorder
    recorder = _Recorder()
    import app.pipeline.tts.indextts_local as module
    module.recorder = recorder
    yield


@pytest.fixture
def env(tmp_path):
    checkpoints = tmp_path / "checkpoints"
    checkpoints.mkdir()
    reference = tmp_path / "ref.wav"
    _write_wav(reference, 3.0)
    return checkpoints, reference


def _provider(env, stub, monkeypatch, **kwargs) -> IndexTTSLocalProvider:
    checkpoints, reference = env
    provider = IndexTTSLocalProvider(str(checkpoints), str(reference), **kwargs)
    monkeypatch.setattr(provider, "_resolve_class",
                        staticmethod(lambda: (stub, stub.__name__)))
    return provider


# -- 三个版本的签名 ----------------------------------------------------------

def test_v25_receives_required_lang(env, tmp_path, monkeypatch):
    """v2.5 的 lang 没有默认值，不传就是 TypeError。"""
    provider = _provider(env, V25Stub, monkeypatch)
    result = provider.synthesize("你好世界", tmp_path / "out.wav")

    call = recorder.calls[0]
    assert call["lang"] == "ZH"
    assert call["spk_audio_prompt"].endswith("ref.wav")
    assert call["duration_factor"] == 1.0
    assert abs(result.duration - 1.25) < 0.01     # 时长来自真实音频


def test_v2_gets_neither_lang_nor_duration_factor(env, tmp_path, monkeypatch):
    """多传一个签名里没有的关键字同样是 TypeError。"""
    provider = _provider(env, V2Stub, monkeypatch)
    assert provider.synthesize("你好", tmp_path / "out.wav").audio_path.exists()
    assert set(recorder.calls[0]) == {"spk_audio_prompt", "text"}


def test_v1_uses_audio_prompt_instead(env, tmp_path, monkeypatch):
    provider = _provider(env, V1Stub, monkeypatch)
    provider.synthesize("你好", tmp_path / "out.wav")
    assert recorder.calls[0]["audio_prompt"].endswith("ref.wav")


def test_custom_lang_is_passed_through(env, tmp_path, monkeypatch):
    provider = _provider(env, V25Stub, monkeypatch, lang="EN")
    provider.synthesize("hello", tmp_path / "out.wav")
    assert recorder.calls[0]["lang"] == "EN"


def test_unrecognised_signature_fails_clearly(env, tmp_path, monkeypatch):
    provider = _provider(env, WrongStub, monkeypatch)
    with pytest.raises(TTSError, match="参考音频参数名"):
        provider.synthesize("你好", tmp_path / "out.wav")


# -- 生命周期与错误 ----------------------------------------------------------

def test_model_is_loaded_once_and_reused(env, tmp_path, monkeypatch):
    """加载一次 0.8B 模型要几十秒，每句重来一遍渲染时间会失控。"""
    provider = _provider(env, V25Stub, monkeypatch)
    for i in range(3):
        provider.synthesize(f"第{i}句", tmp_path / f"out{i}.wav")
    assert recorder.loads == 1
    assert len(recorder.calls) == 3


def test_inference_failure_becomes_a_tts_error(env, tmp_path, monkeypatch):
    provider = _provider(env, ExplodingStub, monkeypatch)
    with pytest.raises(TTSError, match="CUDA out of memory"):
        provider.synthesize("你好", tmp_path / "out.wav")


def test_missing_output_file_is_an_error(env, tmp_path, monkeypatch):
    provider = _provider(env, SilentStub, monkeypatch)
    with pytest.raises(TTSError, match="没有产出音频"):
        provider.synthesize("你好", tmp_path / "out.wav")


# -- 配置校验 ---------------------------------------------------------------

def test_missing_reference_audio(tmp_path):
    checkpoints = tmp_path / "checkpoints"
    checkpoints.mkdir()
    with pytest.raises(TTSError, match="参考音频不存在"):
        IndexTTSLocalProvider(str(checkpoints), str(tmp_path / "nope.wav"))


def test_missing_checkpoints_dir(env, tmp_path):
    _, reference = env
    with pytest.raises(TTSError, match="模型目录不存在"):
        IndexTTSLocalProvider(str(tmp_path / "nope"), str(reference))


def test_package_not_installed_says_so(env, monkeypatch):
    checkpoints, reference = env
    provider = IndexTTSLocalProvider(str(checkpoints), str(reference))
    with pytest.raises(TTSError, match="没有找到可用的 IndexTTS"):
        provider._load()
