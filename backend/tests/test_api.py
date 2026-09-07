"""HTTP 接口的行为约束，重点是逐镜修正这条链路。

渲染被换成了空实现：这里要验的是修正有没有正确落到渲染计划上，
真去跑一遍 Remotion 要好几分钟，且和本文件要测的东西无关。
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import jobs as jobs_module
from app.main import app

SCRIPT = "很多人以为写作是天赋。\n其实写作是一门可以练习的手艺。"


@pytest.fixture
def client(monkeypatch):
    def fake_render(plan, job_dir: Path, settings, on_log=None) -> Path:
        out = job_dir / "output.mp4"
        out.write_bytes(b"fake mp4")
        return out

    monkeypatch.setattr(jobs_module, "render_video", fake_render)
    with TestClient(app) as c:
        yield c


def _wait_for(client, job_id: str, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError("任务超时未结束")


# -- 预览 -------------------------------------------------------------------

def test_preview_returns_scenes_and_digest(client):
    body = client.post("/api/preview", json={"text": SCRIPT}).json()
    assert len(body["scenes"]) == 2
    assert body["script_digest"]
    scene = body["scenes"][0]
    # auto_* 保留自动结果，前端才能显示「已改过」并支持还原
    assert scene["keyword"] == scene["auto_keyword"]
    assert scene["concept"] == scene["auto_concept"]


def test_preview_reflects_overrides(client):
    body = client.post("/api/preview", json={
        "text": SCRIPT,
        "overrides": [{"index": 0, "keyword": "灵感", "concept": "idea"}],
    }).json()
    scene = body["scenes"][0]
    assert (scene["keyword"], scene["concept"]) == ("灵感", "idea")
    assert scene["auto_keyword"] != "灵感"   # 自动结果不被覆盖，仍然可还原


def test_preview_rejects_empty_script(client):
    assert client.post("/api/preview", json={"text": "   "}).status_code == 400


def test_concept_catalog_has_paths_for_thumbnails(client):
    concepts = client.get("/api/concepts").json()["concepts"]
    assert len(concepts) > 30
    assert all(c["paths"] for c in concepts)
    assert any(c["id"] == "doodle" for c in concepts)


# -- 校验 -------------------------------------------------------------------

def test_unknown_concept_is_rejected(client):
    res = client.post("/api/jobs", json={
        "text": SCRIPT, "overrides": [{"index": 0, "concept": "unicorn"}],
    })
    assert res.status_code == 400
    assert "unicorn" in res.json()["detail"]


def test_out_of_range_scene_is_rejected(client):
    res = client.post("/api/jobs", json={
        "text": SCRIPT, "overrides": [{"index": 9, "keyword": "无"}],
    })
    assert res.status_code == 400
    assert "不存在" in res.json()["detail"]


def test_stale_digest_is_rejected(client):
    """改了文稿又带着旧修正来渲染，修正会错位落到别的分镜上。"""
    digest = client.post("/api/preview", json={"text": SCRIPT}).json()["script_digest"]
    res = client.post("/api/jobs", json={
        "text": SCRIPT + "又加了一句完全不同的话。",
        "script_digest": digest,
        "overrides": [{"index": 0, "keyword": "灵感"}],
    })
    assert res.status_code == 409


def test_matching_digest_is_accepted(client):
    digest = client.post("/api/preview", json={"text": SCRIPT}).json()["script_digest"]
    res = client.post("/api/jobs", json={"text": SCRIPT, "script_digest": digest})
    assert res.status_code == 201


# -- 修正真的落到渲染计划上 --------------------------------------------------

def test_overrides_reach_the_render_plan(client):
    created = client.post("/api/jobs", json={
        "text": SCRIPT,
        "overrides": [{"index": 1, "keyword": "手艺活", "concept": "balance"}],
    }).json()
    assert _wait_for(client, created["id"])["status"] == "done"

    scenes = client.get(f"/api/jobs/{created['id']}/plan").json()["scenes"]
    assert (scenes[1]["keyword"], scenes[1]["concept"]) == ("手艺活", "balance")
    # 笔迹必须跟着改成天平，而不是留着原来那张图
    assert scenes[1]["strokes"][0]["d"].startswith("M 50 14 L 50 30")


def test_keyword_only_override_keeps_the_automatic_concept(client):
    auto = client.post("/api/preview", json={"text": SCRIPT}).json()["scenes"][0]
    created = client.post("/api/jobs", json={
        "text": SCRIPT, "overrides": [{"index": 0, "keyword": "随便写点"}],
    }).json()
    assert _wait_for(client, created["id"])["status"] == "done"

    scene = client.get(f"/api/jobs/{created['id']}/plan").json()["scenes"][0]
    assert scene["keyword"] == "随便写点"
    assert scene["concept"] == auto["auto_concept"]


def test_job_without_overrides_still_works(client):
    created = client.post("/api/jobs", json={"text": SCRIPT}).json()
    assert _wait_for(client, created["id"])["status"] == "done"
    assert client.get(f"/api/jobs/{created['id']}").json()["has_video"] is True
