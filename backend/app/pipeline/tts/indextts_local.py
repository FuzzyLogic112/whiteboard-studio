"""在本进程里直接调用 IndexTTS 的 Python API。

这是上游 index-tts 官方支持的用法，没有 HTTP 那一层：

    from indextts.infer_v2_5 import IndexTTS2
    tts = IndexTTS2(cfg_path="checkpoints/config.yaml", model_dir="checkpoints")
    tts.infer(spk_audio_prompt="ref.wav", text="...", output_path="out.wav")

模型 0.8B，加载一次几十秒，所以实例是懒加载 + 全流程复用的——每句话重新
加载一遍模型会让渲染时间失控。

`infer` 的签名在 v2 / v2.5 之间有出入（比如 `lang`、`emo_alpha` 不一定存在），
所以可选参数会先用 inspect 过滤掉当前版本不认识的，而不是硬传一串关键字。
"""

from __future__ import annotations

import importlib
import inspect
import logging
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from .base import TTSError, TTSResult, wav_duration

logger = logging.getLogger(__name__)

# 新版本在前。不同发行版把类放在不同模块里，逐个试。
_CANDIDATES = (
    ("indextts.infer_v2_5", "IndexTTS2"),
    ("indextts.infer_v2", "IndexTTS2"),
    ("indextts.infer", "IndexTTS"),
)


class IndexTTSLocalProvider:
    name = "indextts_local"

    def __init__(self, checkpoints: str, reference_audio: str,
                 lang: str = "", speed: float = 1.0):
        if not checkpoints:
            raise TTSError("indextts_local 需要配置 WBS_INDEXTTS_CHECKPOINTS（模型目录）")
        if not reference_audio:
            raise TTSError("indextts_local 需要配置 WBS_INDEXTTS_REFERENCE（参考音频）")

        self.checkpoints = Path(checkpoints)
        self.reference_audio = Path(reference_audio)
        self.lang = lang
        self.speed = speed
        self._model: Any = None
        self._lock = threading.Lock()

        if not self.reference_audio.exists():
            raise TTSError(f"参考音频不存在：{self.reference_audio}")
        if not self.checkpoints.is_dir():
            raise TTSError(f"模型目录不存在：{self.checkpoints}")

    # -- 模型加载 -----------------------------------------------------------

    def _load(self) -> Any:
        """懒加载并缓存模型实例。加载一次几十秒，绝不能每句话来一遍。"""
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model

            cls, module_name = self._resolve_class()
            config = self.checkpoints / "config.yaml"
            logger.info("正在加载 IndexTTS（%s，模型目录 %s），首次加载需要几十秒",
                        module_name, self.checkpoints)
            try:
                self._model = cls(cfg_path=str(config), model_dir=str(self.checkpoints))
            except Exception as exc:  # noqa: BLE001 - 上游会抛各种底层异常
                raise TTSError(f"加载 IndexTTS 模型失败：{type(exc).__name__}: {exc}") from exc
            return self._model

    @staticmethod
    def _resolve_class() -> tuple[Any, str]:
        errors = []
        for module_name, class_name in _CANDIDATES:
            try:
                module = importlib.import_module(module_name)
            except ImportError as exc:
                errors.append(f"{module_name}: {exc}")
                continue
            cls = getattr(module, class_name, None)
            if cls is not None:
                return cls, f"{module_name}.{class_name}"
            errors.append(f"{module_name}: 没有 {class_name}")
        raise TTSError(
            "没有找到可用的 IndexTTS Python 包。请先按上游说明安装 index-tts 并下载模型。\n"
            + "\n".join(errors)
        )

    # -- 合成 ---------------------------------------------------------------

    def synthesize(self, text: str, out_path: Path) -> TTSResult:
        model = self._load()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        kwargs: Dict[str, Any] = {
            "spk_audio_prompt": str(self.reference_audio),
            "text": text,
            "output_path": str(out_path),
        }
        # 版本之间可选参数不一致，只传当前 infer 真正接受的
        optional = {"lang": self.lang or None, "duration_factor": self.speed}
        kwargs.update(_supported(model.infer, optional))

        try:
            model.infer(**kwargs)
        except Exception as exc:  # noqa: BLE001 - 推理会抛各种底层异常
            raise TTSError(f"IndexTTS 合成失败：{type(exc).__name__}: {exc}") from exc

        if not out_path.exists():
            raise TTSError(f"IndexTTS 没有产出音频文件：{out_path}")
        return TTSResult(duration=wav_duration(out_path), audio_path=out_path)


def _supported(func: Any, candidates: Dict[str, Optional[Any]]) -> Dict[str, Any]:
    """挑出 func 签名里真正存在、且值不为 None 的关键字参数。"""
    try:
        names = set(inspect.signature(func).parameters)
    except (TypeError, ValueError):
        return {}
    return {k: v for k, v in candidates.items() if v is not None and k in names}
