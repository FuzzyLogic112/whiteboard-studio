"""配图 provider。

生图那条路对着 mock 服务测：真实接口按张收费、耗时几十秒，而这里要验的是
请求契约、缓存、以及失败时的兜底。
"""

from __future__ import annotations

import dataclasses
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from app.config import load_settings
from app.pipeline.illustrate import build_illustrator, paths_for_scene
from app.pipeline.illustrate.base import IllustrationError
from app.pipeline.illustrate.builtin import BuiltinIllustrator
from app.pipeline.illustrate.glm_image import GlmImageIllustrator
from app.pipeline.sketch import GLYPHS


def _line_art() -> bytes:
    image = Image.new("L", (400, 400), 255)
    ImageDraw.Draw(image).ellipse([80, 80, 320, 320], outline=0, width=6)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.server.requests.append(json.loads(body))

        # 前 fail_first 次返回可重试的错误，用来验证退避重试
        if self.server.fail_first > 0:
            self.server.fail_first -= 1
            self.send_response(429)
            self.end_headers()
            self.wfile.write(b'{"error":{"code":"1302","message":"rate limited"}}')
            return

        if self.server.mode == "http_error":
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"bad prompt"}}')
            return
        if self.server.mode == "no_url":
            payload = {"data": [{}]}
        else:
            host, port = self.server.server_address
            payload = {"data": [{"url": f"http://{host}:{port}/image.png"}]}

        out = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def do_GET(self):  # noqa: N802
        if self.server.mode == "blank_image":
            image = Image.new("L", (400, 400), 255)
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            data = buffer.getvalue()
        else:
            data = _line_art()
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    httpd.mode = "ok"
    httpd.requests = []
    httpd.fail_first = 0
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def _illustrator(server, tmp_path, **kwargs) -> GlmImageIllustrator:
    host, port = server.server_address
    defaults = dict(endpoint=f"http://{host}:{port}", model="cogview-3-flash",
                    size="1024x1024", cache_dir=tmp_path / "cache", watermark=False,
                    backoff=(0, 0, 0))   # 测试里不真的等
    return GlmImageIllustrator(**{**defaults, **kwargs})


def _settings(server, tmp_path, **overrides):
    host, port = server.server_address
    fields = {
        "illustrator": "glm_image",
        "image_endpoint": f"http://{host}:{port}",
        "image_model": "cogview-3-flash",
        "image_api_key": "",
        "image_watermark": False,
        "workspace": tmp_path,
        **overrides,
    }
    return dataclasses.replace(load_settings(), **fields)


# -- builtin ----------------------------------------------------------------

def test_builtin_returns_the_glyph_for_the_concept():
    assert BuiltinIllustrator().paths_for("齿轮", "", "gear") == GLYPHS["gear"]


def test_builtin_falls_back_to_doodle_for_unknown_concept():
    paths = BuiltinIllustrator().paths_for("薛定谔", "", "doodle")
    assert paths and paths[0].startswith("M ")


# -- 生图 -------------------------------------------------------------------

def test_generates_downloads_and_vectorizes(server, tmp_path):
    paths = _illustrator(server, tmp_path).paths_for("灯泡", "一个想法", "idea")
    assert paths and all(p.startswith("M ") for p in paths)


def test_request_carries_prompt_and_options(server, tmp_path):
    _illustrator(server, tmp_path).paths_for("齿轮", "", "gear")
    request = server.requests[0]
    assert request["model"] == "cogview-3-flash"
    assert request["watermark_enabled"] is False
    # 提示词必须写死这些约束，否则模型会加投影/文字，矢量化结果就散了
    assert "齿轮" in request["prompt"]
    for constraint in ("纯白背景", "禁止阴影", "居中"):
        assert constraint in request["prompt"]


def test_result_is_cached_across_calls(server, tmp_path):
    illustrator = _illustrator(server, tmp_path)
    first = illustrator.paths_for("灯泡", "", "idea")
    second = illustrator.paths_for("灯泡", "", "idea")
    assert first == second
    assert len(server.requests) == 1, "同一个关键词不该再花一次钱"


def test_cache_survives_a_new_instance(server, tmp_path):
    _illustrator(server, tmp_path).paths_for("灯泡", "", "idea")
    _illustrator(server, tmp_path).paths_for("灯泡", "", "idea")
    assert len(server.requests) == 1


def test_watermark_setting_changes_the_cache_key(server, tmp_path):
    _illustrator(server, tmp_path, watermark=False).paths_for("灯泡", "", "idea")
    _illustrator(server, tmp_path, watermark=True).paths_for("灯泡", "", "idea")
    assert len(server.requests) == 2


def test_http_error_surfaces(server, tmp_path):
    server.mode = "http_error"
    with pytest.raises(IllustrationError, match="400"):
        _illustrator(server, tmp_path).paths_for("灯泡", "", "idea")


# -- 退避重试 ---------------------------------------------------------------

def test_retries_past_rate_limiting(server, tmp_path):
    """逐镜连续生图必然撞账号限流，不重试的话一篇稿子会有几镜掉进兜底。"""
    server.fail_first = 2
    paths = _illustrator(server, tmp_path).paths_for("灯泡", "", "idea")
    assert paths
    assert len(server.requests) == 3


def test_gives_up_after_the_last_backoff(server, tmp_path):
    server.fail_first = 99
    with pytest.raises(IllustrationError, match="429"):
        _illustrator(server, tmp_path).paths_for("灯泡", "", "idea")
    assert len(server.requests) == 4        # 首次 + 三次重试


def test_non_retryable_error_is_not_retried(server, tmp_path):
    """400 是提示词写错了，重试多少次都一样。"""
    server.mode = "http_error"
    with pytest.raises(IllustrationError):
        _illustrator(server, tmp_path).paths_for("灯泡", "", "idea")
    assert len(server.requests) == 1


def test_missing_url_surfaces(server, tmp_path):
    server.mode = "no_url"
    with pytest.raises(IllustrationError, match="没有图片地址"):
        _illustrator(server, tmp_path).paths_for("灯泡", "", "idea")


def test_blank_image_is_an_error(server, tmp_path):
    server.mode = "blank_image"
    with pytest.raises(IllustrationError, match="没有任何笔迹"):
        _illustrator(server, tmp_path).paths_for("灯泡", "", "idea")


def test_download_failure_mentions_the_separate_domain(tmp_path):
    """图片托管在与 API 不同的域名上，这个坑要在报错里说清楚。"""
    illustrator = GlmImageIllustrator(
        endpoint="http://127.0.0.1:1", model="m", size="1024x1024",
        cache_dir=tmp_path, watermark=False, backoff=())
    with pytest.raises(IllustrationError, match="连接生图接口失败"):
        illustrator.paths_for("灯泡", "", "idea")


def test_missing_config_fails_fast(tmp_path):
    with pytest.raises(IllustrationError, match="WBS_IMAGE_"):
        GlmImageIllustrator(endpoint="", model="m", size="1", cache_dir=tmp_path)


# -- 兜底 -------------------------------------------------------------------

def test_falls_back_to_builtin_with_a_warning(server, tmp_path):
    server.mode = "http_error"
    warnings: list[str] = []
    paths = paths_for_scene("齿轮", "", "gear", _settings(server, tmp_path),
                            on_warning=warnings.append)
    assert paths == GLYPHS["gear"]
    assert len(warnings) == 1 and "内置简笔画" in warnings[0]


def test_builtin_mode_makes_no_network_call(server, tmp_path):
    paths_for_scene("齿轮", "", "gear", _settings(server, tmp_path, illustrator="builtin"))
    assert server.requests == []


def test_unknown_illustrator_is_rejected(server, tmp_path):
    with pytest.raises(IllustrationError, match="未知的配图器"):
        build_illustrator(_settings(server, tmp_path, illustrator="dalle"))
