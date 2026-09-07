"""运行时配置。全部通过环境变量覆盖，没有配置文件也能跑。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # 工作目录：任务产物（音频、渲染计划、成片）都放在这里，不出本机
    workspace: Path
    # Remotion 渲染
    renderer_dir: Path
    browser_executable: str
    render_concurrency: int
    # 语音合成
    tts_provider: str
    indextts_endpoint: str
    indextts_reference: str
    # 视频规格
    width: int
    height: int
    fps: int

    @property
    def jobs_dir(self) -> Path:
        return self.workspace / "jobs"


def load_settings() -> Settings:
    repo_root = Path(__file__).resolve().parents[2]
    workspace = Path(_env("WBS_WORKSPACE", ".workspace"))
    if not workspace.is_absolute():
        workspace = repo_root / workspace
    return Settings(
        workspace=workspace,
        renderer_dir=repo_root / "renderer",
        browser_executable=_env("WBS_BROWSER_EXECUTABLE"),
        render_concurrency=_env_int("WBS_RENDER_CONCURRENCY", 1),
        tts_provider=_env("WBS_TTS_PROVIDER", "silent") or "silent",
        indextts_endpoint=_env("WBS_INDEXTTS_ENDPOINT", "http://127.0.0.1:7860"),
        indextts_reference=_env("WBS_INDEXTTS_REFERENCE"),
        width=_env_int("WBS_WIDTH", 1920),
        height=_env_int("WBS_HEIGHT", 1080),
        fps=_env_int("WBS_FPS", 30),
    )


settings = load_settings()
