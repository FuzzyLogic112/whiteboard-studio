"""位图 → SVG 笔迹。

全部用合成图，不联网也不依赖生图模型：这里要验的是骨架化和路径提取本身。
"""

from __future__ import annotations

import math
import re

import pytest
from PIL import Image, ImageDraw

from app.pipeline.vectorize import (
    _build_graph, _polyline_length, load_mask, simplify, thin, trace, vectorize,
)


def _canvas(draw_fn, size=(400, 400)) -> Image.Image:
    image = Image.new("L", size, 255)
    draw_fn(ImageDraw.Draw(image))
    return image


def _write(tmp_path, name, draw_fn, size=(400, 400)):
    path = tmp_path / name
    _canvas(draw_fn, size).save(path)
    return path


def _points(path: str):
    nums = [float(v) for v in re.findall(r"-?\d+\.?\d*", path)]
    return list(zip(nums[::2], nums[1::2]))


# -- 端到端 -----------------------------------------------------------------

def test_single_line_becomes_one_stroke(tmp_path):
    path = _write(tmp_path, "line.png",
                  lambda d: d.line([(60, 200), (340, 200)], fill=0, width=5))
    assert len(vectorize(path)) == 1


def test_two_shapes_become_two_strokes(tmp_path):
    def draw(d):
        d.ellipse([40, 40, 160, 160], outline=0, width=5)
        d.ellipse([240, 240, 360, 360], outline=0, width=5)
    assert len(vectorize(_write(tmp_path, "two.png", draw))) == 2


def test_blank_image_yields_nothing(tmp_path):
    assert vectorize(_write(tmp_path, "blank.png", lambda d: None)) == []


def test_paths_are_svg_and_inside_the_viewbox(tmp_path):
    path = _write(tmp_path, "circle.png",
                  lambda d: d.ellipse([80, 80, 320, 320], outline=0, width=5))
    for d in vectorize(path):
        assert d.startswith("M ")
        for x, y in _points(d):
            assert -1 <= x <= 101 and -1 <= y <= 101


def test_output_is_deterministic(tmp_path):
    path = _write(tmp_path, "det.png",
                  lambda d: d.ellipse([80, 80, 320, 320], outline=0, width=5))
    assert vectorize(path) == vectorize(path)


def test_tiny_speck_is_dropped_as_noise(tmp_path):
    def draw(d):
        d.line([(60, 200), (340, 200)], fill=0, width=5)
        d.ellipse([20, 20, 26, 26], fill=0)      # 噪点
    assert len(vectorize(_write(tmp_path, "speck.png", draw))) == 1


def test_crop_bottom_removes_content_there(tmp_path):
    """生图平台的显式水印固定在右下角，靠裁底部去掉。"""
    def draw(d):
        d.line([(60, 100), (340, 100)], fill=0, width=5)   # 主体，在上方
        d.rectangle([300, 370, 390, 395], fill=0)          # 「水印」，在底部
    path = _write(tmp_path, "wm.png", draw)
    assert len(vectorize(path)) == 2
    assert len(vectorize(path, crop_bottom=0.12)) == 1


# -- 各阶段 -----------------------------------------------------------------

def test_thinning_reduces_a_thick_line_to_one_pixel_wide(tmp_path):
    path = _write(tmp_path, "thick.png",
                  lambda d: d.line([(60, 200), (340, 200)], fill=0, width=15))
    mask = load_mask(path)
    skeleton = thin(mask)
    assert skeleton.sum() < mask.sum() / 3
    # 每一列最多剩一个骨架像素
    assert skeleton.sum(axis=0).max() <= 2


def test_diagonal_staircase_does_not_fragment_the_chain(tmp_path):
    """八连通下斜线的阶梯会造出假交叉点，把一条线切成几百段。

    建图时丢掉冗余对角边就能修好——这是整个矢量化能跑通的前提。
    """
    path = _write(tmp_path, "diag.png",
                  lambda d: d.line([(60, 60), (340, 340)], fill=0, width=4))
    graph = _build_graph(thin(load_mask(path)))
    branching = sum(1 for neighbours in graph.values() if len(neighbours) > 2)
    assert branching == 0, f"斜线上不该有交叉点，实际有 {branching} 个"
    assert len(trace(thin(load_mask(path)))) == 1


def test_junction_splits_into_separate_strokes(tmp_path):
    """T 形交叉应该拆成多笔，而不是一笔画完。"""
    def draw(d):
        d.line([(60, 200), (340, 200)], fill=0, width=5)
        d.line([(200, 200), (200, 360)], fill=0, width=5)
    assert len(trace(thin(load_mask(_write(tmp_path, "tee.png", draw))))) == 3


def test_simplify_drops_collinear_points():
    line = [(x, 0) for x in range(20)]
    assert simplify(line) == [(0, 0), (19, 0)]


def test_simplify_keeps_corners():
    corner = [(x, 0) for x in range(10)] + [(9, y) for y in range(1, 10)]
    assert len(simplify(corner)) == 3          # 起点、拐点、终点


def test_simplify_handles_short_input():
    assert simplify([(0, 0)]) == [(0, 0)]
    assert simplify([(0, 0), (1, 1)]) == [(0, 0), (1, 1)]


def test_polyline_length():
    assert _polyline_length([(0, 0), (3, 4)]) == pytest.approx(5.0)


def test_strokes_are_ordered_longest_first(tmp_path):
    def draw(d):
        d.line([(40, 60), (360, 60)], fill=0, width=4)     # 长
        d.line([(40, 300), (120, 300)], fill=0, width=4)   # 短
    paths = vectorize(_write(tmp_path, "order.png", draw))
    lengths = [_polyline_length(_points(p)) for p in paths]
    assert lengths == sorted(lengths, reverse=True)


def test_content_is_centred_in_the_viewbox(tmp_path):
    """原图里靠角落的主体，归一化后应该居中。"""
    path = _write(tmp_path, "corner.png",
                  lambda d: d.ellipse([20, 20, 120, 120], outline=0, width=4))
    xs = [p[0] for d in vectorize(path) for p in _points(d)]
    ys = [p[1] for d in vectorize(path) for p in _points(d)]
    assert 40 < (min(xs) + max(xs)) / 2 < 60
    assert 40 < (min(ys) + max(ys)) / 2 < 60
