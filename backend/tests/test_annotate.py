"""分镜标注器。

GLM 那部分对着 mock 服务测：真实接口要花钱、有网络依赖，而这里要验的是
契约解析和**模型输出不可信时的兜底**，跟真模型无关。
"""

from __future__ import annotations

import dataclasses
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.config import load_settings
from app.pipeline.annotate import annotate_scenes, build_annotator
from app.pipeline.annotate.base import AnnotationError
from app.pipeline.annotate.glm import GlmAnnotator
from app.pipeline.sketch import known_concepts

SENTENCES = ["很多人以为写作是天赋。", "其实写作是一门手艺。", "今天聊三件事。"]


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.server.last_request = json.loads(body)
        self.server.last_auth = self.headers.get("Authorization")

        mode = self.server.mode
        if mode == "http_error":
            self.send_response(429)
            self.end_headers()
            self.wfile.write(b'{"error":{"code":"1305","message":"too busy"}}')
            return

        payloads = {
            "ok": {"scenes": [
                {"index": 0, "keyword": "天赋", "concept": "star"},
                {"index": 1, "keyword": "手艺", "concept": "edit"},
                {"index": 2, "keyword": "三件事", "concept": "chat"},
            ]},
            "bad_concept": {"scenes": [
                {"index": 0, "keyword": "天赋", "concept": "unicorn"},
                {"index": 1, "keyword": "手艺", "concept": "edit"},
                {"index": 2, "keyword": "三件事", "concept": "chat"},
            ]},
            "missing_scene": {"scenes": [
                {"index": 0, "keyword": "天赋", "concept": "star"},
            ]},
            "junk_index": {"scenes": [
                {"index": 99, "keyword": "越界", "concept": "star"},
                {"index": "x", "keyword": "非法", "concept": "star"},
                {"index": 1, "keyword": "手艺", "concept": "edit"},
            ]},
            "long_keyword": {"scenes": [
                {"index": i, "keyword": "这是一个非常长的短语", "concept": "star"}
                for i in range(3)
            ]},
            "no_scenes": {"result": []},
        }
        content = "不是 JSON" if mode == "not_json" else json.dumps(
            payloads[mode], ensure_ascii=False)

        out = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    httpd = HTTPServer(("127.0.0.1", 0), _Handler)
    httpd.mode = "ok"
    httpd.last_request = None
    httpd.last_auth = None
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def _annotator(server, **kwargs) -> GlmAnnotator:
    host, port = server.server_address
    defaults = dict(endpoint=f"http://{host}:{port}", model="glm-4-flash-250414")
    return GlmAnnotator(**{**defaults, **kwargs})


def _settings(server, **overrides):
    host, port = server.server_address
    fields = {
        "annotator": "glm",
        "glm_endpoint": f"http://{host}:{port}",
        "glm_model": "glm-4-flash-250414",
        "glm_api_key": "",
        **overrides,
    }
    return dataclasses.replace(load_settings(), **fields)


# -- 正常路径 ---------------------------------------------------------------

def test_parses_annotations(server):
    result = _annotator(server).annotate(SENTENCES)
    assert [(a.keyword, a.concept) for a in result] == [
        ("天赋", "star"), ("手艺", "edit"), ("三件事", "chat")]


def test_request_carries_scenes_and_concept_list(server):
    _annotator(server).annotate(SENTENCES)
    req = server.last_request
    assert req["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in req["messages"]] == ["system", "user"]

    payload = json.loads(req["messages"][1]["content"])
    assert [s["text"] for s in payload["scenes"]] == SENTENCES
    # 概念表要发给模型，否则它只能瞎猜 concept 名
    assert set(payload["concepts"]) == set(known_concepts())


def test_api_key_is_optional(server):
    """云环境里 key 由代理注入，请求本身不该带 Authorization。"""
    _annotator(server, api_key="").annotate(SENTENCES)
    assert server.last_auth is None


def test_api_key_is_sent_when_configured(server):
    _annotator(server, api_key="secret").annotate(SENTENCES)
    assert server.last_auth == "Bearer secret"


# -- 模型输出不可信 ---------------------------------------------------------

def test_invented_concept_is_discarded(server):
    server.mode = "bad_concept"
    result = _annotator(server).annotate(SENTENCES)
    assert result[0].concept == ""      # 留空，交给本地结果补
    assert result[0].keyword == "天赋"   # 关键词本身仍然可用


def test_out_of_range_and_non_integer_index_are_ignored(server):
    server.mode = "junk_index"
    result = _annotator(server).annotate(SENTENCES)
    assert result[1].keyword == "手艺"
    assert result[0].keyword == "" and result[2].keyword == ""


def test_overlong_keyword_is_truncated(server):
    server.mode = "long_keyword"
    for annotation in _annotator(server).annotate(SENTENCES):
        assert len(annotation.keyword) <= 4


@pytest.mark.parametrize("mode", ["not_json", "no_scenes"])
def test_unusable_output_raises(server, mode):
    server.mode = mode
    with pytest.raises(AnnotationError):
        _annotator(server).annotate(SENTENCES)


def test_http_error_surfaces_status(server):
    server.mode = "http_error"
    with pytest.raises(AnnotationError, match="429"):
        _annotator(server).annotate(SENTENCES)


def test_unreachable_endpoint_raises():
    with pytest.raises(AnnotationError, match="连接 GLM 失败"):
        GlmAnnotator(endpoint="http://127.0.0.1:1", model="m").annotate(SENTENCES)


# -- 兜底策略 ---------------------------------------------------------------

def test_falls_back_to_local_on_failure(server):
    """标注失败只是「词挑得没那么好」，片子仍然完整，所以自动兜底——但要留痕。"""
    server.mode = "http_error"
    warnings: list[str] = []
    result = annotate_scenes(SENTENCES, _settings(server), warnings.append)

    assert all(a.keyword and a.concept for a in result)
    assert len(warnings) == 1 and "本地结果" in warnings[0]


def test_partial_result_is_patched_from_local(server):
    server.mode = "missing_scene"
    warnings: list[str] = []
    result = annotate_scenes(SENTENCES, _settings(server), warnings.append)

    assert result[0].keyword == "天赋"          # 模型给的保留
    assert all(a.keyword and a.concept for a in result)   # 其余由本地补齐
    assert len(warnings) == 1 and "2/3" in warnings[0]


def test_bad_concept_is_patched_but_keyword_kept(server):
    server.mode = "bad_concept"
    result = annotate_scenes(SENTENCES, _settings(server))
    assert result[0].keyword == "天赋"
    assert result[0].concept in set(known_concepts())


def test_local_annotator_makes_no_network_call(server):
    annotate_scenes(SENTENCES, _settings(server, annotator="local"))
    assert server.last_request is None


def test_unknown_annotator_is_rejected(server):
    with pytest.raises(AnnotationError, match="未知的标注器"):
        build_annotator(_settings(server, annotator="magic"))
