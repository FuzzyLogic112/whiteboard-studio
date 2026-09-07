"""调用 Remotion 把渲染计划渲成 MP4。

这里是唯一和 Remotion 耦合的地方。要换成 FFmpeg/Canvas 方案（比如为了
规避 Remotion 的商业授权），只需要另写一个同签名的 `render_video`。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Callable, Optional

from .config import Settings
from .models import RenderPlan

logger = logging.getLogger(__name__)

COMPOSITION_ID = "Whiteboard"
RENDER_TIMEOUT_SECONDS = 60 * 30


class RenderError(RuntimeError):
    pass


def render_video(
    plan: RenderPlan,
    job_dir: Path,
    settings: Settings,
    on_log: Optional[Callable[[str], None]] = None,
) -> Path:
    props_path = job_dir / "plan.json"
    props_path.write_text(
        plan.model_dump_json(indent=2, exclude_none=False), encoding="utf-8"
    )
    out_path = job_dir / "output.mp4"

    if not (settings.renderer_dir / "node_modules").exists():
        raise RenderError(
            f"渲染器依赖未安装。请先执行： cd {settings.renderer_dir} && npm install"
        )

    cmd = [
        "npx", "remotion", "render", COMPOSITION_ID, str(out_path),
        f"--props={props_path}",
        f"--concurrency={settings.render_concurrency}",
        # 音频和图片都按 job 目录取相对路径，交给 Remotion 的 staticFile 解析
        f"--public-dir={job_dir}",
        "--log=info",
    ]
    if settings.browser_executable:
        cmd.append(f"--browser-executable={settings.browser_executable}")

    logger.info("渲染命令：%s", " ".join(cmd))
    process = subprocess.Popen(
        cmd,
        cwd=settings.renderer_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ, "CI": "1"},  # 关掉进度条动画，日志才好逐行读
    )

    tail: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        line = line.rstrip()
        if not line:
            continue
        tail.append(line)
        del tail[:-40]
        if on_log:
            on_log(line)

    try:
        code = process.wait(timeout=RENDER_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        raise RenderError("渲染超时") from exc

    if code != 0:
        raise RenderError("Remotion 渲染失败：\n" + "\n".join(tail[-20:]))
    if not out_path.exists():
        raise RenderError("Remotion 退出码为 0，但没有产出文件")
    return out_path
