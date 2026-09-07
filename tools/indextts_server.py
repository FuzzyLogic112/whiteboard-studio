"""把 IndexTTS 跑成一个 OpenAI 兼容的语音服务。

上游的 index-tts **不提供 HTTP API**（只有 Gradio webui、Python API 和 vLLM
recipe），所以这里带一个参考实现。它暴露的接口正是 `indextts_http` provider
所约定的那一套：

    POST /v1/audio/speech
    Authorization: Bearer <token>        （设了 WBS_SERVER_TOKEN 才校验）
    {"model": "IndexTTS", "input": "要合成的文本", "voice": "narrator",
     "response_format": "wav", "speed": 1.0}
    -> audio/wav

**这个文件要跑在 index-tts 的虚拟环境里**，不是 whiteboard-studio 的环境：

    cd /path/to/index-tts
    uv pip install fastapi uvicorn
    export WBS_SERVER_CHECKPOINTS=./checkpoints
    export WBS_SERVER_VOICES=./characters          # 放参考音频的目录
    uv run python /path/to/whiteboard-studio/tools/indextts_server.py

它是自包含的，**故意不 import whiteboard-studio 的任何代码**——两边在不同的
虚拟环境里，共享代码只会把 torch 的依赖拖进来。代价是版本适配逻辑和
`app/pipeline/tts/indextts_local.py` 有一份重复，改动时两边都要看一眼。
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

logger = logging.getLogger("indextts-server")

# 和 app/pipeline/tts/indextts_local.py 保持一致：不同版本的 infer 签名不一样
_CANDIDATES = (
    ("indextts.infer_v2_5", "IndexTTS2"),
    ("indextts.infer_v2", "IndexTTS2"),
    ("indextts.infer", "IndexTTS"),
)
_PROMPT_ARG_NAMES = ("spk_audio_prompt", "audio_prompt")
DEFAULT_LANG = "ZH"

# 合成一句话可能要几十秒，模型只加载一次；请求串行处理，避免显存被挤爆
Synthesize = Callable[[str, str, float, Path], None]


class SpeechRequest(BaseModel):
    """OpenAI 的 /v1/audio/speech 请求体，只取用得上的字段。"""

    input: str = Field(min_length=1)
    voice: str = Field(min_length=1)
    model: str = "IndexTTS"
    response_format: str = "wav"
    speed: float = 1.0


def create_app(synthesize: Synthesize, voices_dir: Path,
               token: str = "") -> FastAPI:
    """把合成函数包成 HTTP 服务。

    合成函数是注入进来的，这样不装 IndexTTS 也能测接口契约本身。
    """
    app = FastAPI(title="indextts-server", version="1.0.0")

    def authorize(authorization: Optional[str] = Header(default=None)) -> None:
        if not token:
            return
        if authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="无效的 Authorization 头")

    @app.get("/health")
    def health() -> dict:
        voices = sorted(p.stem for p in voices_dir.glob("*.wav")) if voices_dir.is_dir() else []
        return {"ok": True, "voices": voices, "voices_dir": str(voices_dir)}

    @app.post("/v1/audio/speech", dependencies=[Depends(authorize)])
    def speech(req: SpeechRequest) -> Response:
        # 只出 wav：调用方要按音频算每个分镜的时长，wav 读个文件头就知道，
        # mp3 得解码。不做转码，免得悄悄引入误差。
        if req.response_format != "wav":
            raise HTTPException(
                status_code=400,
                detail=f"只支持 response_format=wav，收到 {req.response_format}")

        reference = voices_dir / f"{req.voice}.wav"
        if not reference.exists():
            available = sorted(p.stem for p in voices_dir.glob("*.wav"))
            raise HTTPException(
                status_code=404,
                detail=f"音色 {req.voice} 不存在。{voices_dir} 下现有：{available}")

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "speech.wav"
            try:
                synthesize(req.input, str(reference), req.speed, out_path)
            except Exception as exc:  # noqa: BLE001 - 推理会抛各种底层异常
                logger.exception("合成失败")
                raise HTTPException(
                    status_code=500,
                    detail=f"合成失败：{type(exc).__name__}: {exc}") from exc
            if not out_path.exists():
                raise HTTPException(status_code=500, detail="模型没有产出音频文件")
            return Response(content=out_path.read_bytes(), media_type="audio/wav")

    return app


# ---------------------------------------------------------------------------
# 真实模型
# ---------------------------------------------------------------------------

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
    raise SystemExit(
        "没有找到可用的 IndexTTS。这个脚本要在 index-tts 的虚拟环境里跑，"
        "例如 `cd index-tts && uv run python .../indextts_server.py`。\n"
        + "\n".join(errors))


def build_synthesize(checkpoints: Path, lang: str) -> Synthesize:
    """加载模型，返回一个合成函数。

    版本适配和 indextts_local 一样：参考音频的参数名在 spk_audio_prompt /
    audio_prompt 里挑签名认识的；lang 只要签名里有就必须传（v2.5 里它没有
    默认值）；speed 映射到 duration_factor，老版本没有就不传。
    """
    cls, name = _resolve_class()
    config = checkpoints / "config.yaml"
    logger.info("正在加载 %s（模型目录 %s），首次加载需要几十秒", name, checkpoints)
    model = cls(cfg_path=str(config), model_dir=str(checkpoints))

    accepted = set(inspect.signature(model.infer).parameters)
    prompt_arg = next((n for n in _PROMPT_ARG_NAMES if n in accepted), None)
    if prompt_arg is None:
        raise SystemExit(
            f"无法识别 {name}.infer 的参考音频参数名，签名里既没有 "
            f"spk_audio_prompt 也没有 audio_prompt：{sorted(accepted)}")
    logger.info("参考音频参数=%s，lang=%s，duration_factor=%s",
                prompt_arg, "lang" in accepted, "duration_factor" in accepted)

    def synthesize(text: str, reference: str, speed: float, out_path: Path) -> None:
        kwargs: dict[str, Any] = {
            prompt_arg: reference,
            "text": text,
            "output_path": str(out_path),
        }
        if "lang" in accepted:
            kwargs["lang"] = lang
        if "duration_factor" in accepted:
            kwargs["duration_factor"] = speed
        model.infer(**kwargs)

    return synthesize


def main() -> None:
    parser = argparse.ArgumentParser(description="把 IndexTTS 跑成 OpenAI 兼容的语音服务")
    parser.add_argument("--host", default=os.environ.get("WBS_SERVER_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("WBS_SERVER_PORT", "8100")))
    parser.add_argument("--checkpoints", type=Path,
                        default=Path(os.environ.get("WBS_SERVER_CHECKPOINTS", "checkpoints")))
    parser.add_argument("--voices", type=Path,
                        default=Path(os.environ.get("WBS_SERVER_VOICES", "characters")),
                        help="参考音频目录，文件名（不含扩展名）就是音色名")
    parser.add_argument("--lang", default=os.environ.get("WBS_SERVER_LANG", DEFAULT_LANG),
                        help="ZH / EN / ZHEN / JA / ES")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if not args.checkpoints.is_dir():
        raise SystemExit(f"模型目录不存在：{args.checkpoints}")
    if not args.voices.is_dir():
        raise SystemExit(
            f"参考音频目录不存在：{args.voices}。"
            "建一个目录，把 5~10 秒的干净人声放进去，文件名就是音色名。")

    import uvicorn

    app = create_app(
        build_synthesize(args.checkpoints, args.lang),
        args.voices,
        os.environ.get("WBS_SERVER_TOKEN", ""),
    )
    # 串行处理：合成很吃显存，并发进来容易 OOM
    uvicorn.run(app, host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()
