"""把线稿位图变成可以「一笔一笔画出来」的 SVG 路径。

这是接 AI 生图的必要一步。生图模型返回的是位图，而白板动画的全部观感来自
`stroke-dashoffset` 让线条从起点长出来——位图做不到这件事，直接贴上去淡入
就退化成幻灯片了。

**取中心线，不取轮廓。**
常见的位图转矢量（potrace 那一类）描的是色块**轮廓**：一条 3 像素宽的线会
变成一个绕着它跑一圈的闭合环。动画播出来是「沿着线画过去、再沿另一侧画回来」，
明显不像手写。所以这里先把笔画细化成 1 像素宽的骨架，再沿骨架走——笔尖轨迹
就是真正的中心线，画一次就完事。

流程：灰度 → 二值化（Otsu）→ Zhang-Suen 细化 → 骨架图遍历 → RDP 简化
→ 归一化到 100x100 的 viewBox。

只依赖 numpy 和 Pillow，没有 OpenCV / potrace——它们体积大、装起来麻烦，
而这里要做的事总共不到两百行。
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Dict, List, Sequence, Set, Tuple

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

Point = Tuple[int, int]
Polyline = List[Point]

# 细化前把图缩到这个尺寸。1024x1024 逐像素跑 Zhang-Suen 太慢，而后面 RDP
# 本来就要大幅简化，多出来的分辨率全会被丢掉。
WORK_SIZE = 320
# RDP 容差（工作尺度下的像素）。太小则路径点爆炸，太大则圆弧被切成折线。
SIMPLIFY_EPSILON = 0.9
# 短于对角线这个比例的笔画当噪点丢掉
MIN_STROKE_RATIO = 0.035
# 归一化后内容占 viewBox 的比例，四周留白
CONTENT_EXTENT = 88.0


# ---------------------------------------------------------------------------
# 二值化
# ---------------------------------------------------------------------------

def _otsu_threshold(gray: np.ndarray) -> int:
    """Otsu 大津法：让前景背景两类的类间方差最大。

    固定阈值在这里不好用——生图模型给的「白底」经常是米白、带渐变，
    不同图的底色深浅差得远。
    """
    histogram = np.bincount(gray.ravel(), minlength=256).astype(np.float64)
    total = histogram.sum()
    if total == 0:
        return 128

    levels = np.arange(256)
    weight_bg = np.cumsum(histogram)
    weight_fg = total - weight_bg
    sum_total = float((histogram * levels).sum())
    sum_bg = np.cumsum(histogram * levels)

    valid = (weight_bg > 0) & (weight_fg > 0)
    between = np.zeros(256, dtype=np.float64)
    mean_bg = np.divide(sum_bg, weight_bg, out=np.zeros(256), where=weight_bg > 0)
    mean_fg = np.divide(sum_total - sum_bg, weight_fg, out=np.zeros(256), where=weight_fg > 0)
    between[valid] = (weight_bg * weight_fg * (mean_bg - mean_fg) ** 2)[valid]
    return int(between.argmax())


def load_mask(image_path: Path, work_size: int = WORK_SIZE,
              crop_bottom: float = 0.0) -> np.ndarray:
    """读图并二值化，返回 True 表示墨迹的布尔数组。

    crop_bottom 按比例裁掉底部——生图平台的显式水印固定在右下角，
    没关掉水印时用它切掉，否则水印会被当成笔迹描出来。
    """
    image = Image.open(image_path).convert("L")
    if crop_bottom > 0:
        width, height = image.size
        image = image.crop((0, 0, width, int(height * (1 - crop_bottom))))

    image.thumbnail((work_size, work_size), Image.LANCZOS)
    gray = np.asarray(image, dtype=np.uint8)
    return gray <= _otsu_threshold(gray)


# ---------------------------------------------------------------------------
# Zhang-Suen 细化
# ---------------------------------------------------------------------------

def _neighbour_stack(padded: np.ndarray) -> List[np.ndarray]:
    """按 P2..P9 的顺序（正北开始顺时针）取八邻域。"""
    return [
        padded[:-2, 1:-1],  # P2 N
        padded[:-2, 2:],    # P3 NE
        padded[1:-1, 2:],   # P4 E
        padded[2:, 2:],     # P5 SE
        padded[2:, 1:-1],   # P6 S
        padded[2:, :-2],    # P7 SW
        padded[1:-1, :-2],  # P8 W
        padded[:-2, :-2],   # P9 NW
    ]


def thin(mask: np.ndarray, max_iterations: int = 100) -> np.ndarray:
    """Zhang-Suen 细化：把墨迹削成 1 像素宽的骨架，保持连通性。"""
    image = mask.astype(np.uint8)

    for _ in range(max_iterations):
        changed = False
        for sub_iteration in (0, 1):
            padded = np.pad(image, 1)
            p = _neighbour_stack(padded)

            transitions = sum(
                ((p[i] == 0) & (p[(i + 1) % 8] == 1)).astype(np.uint8) for i in range(8)
            )
            neighbours = sum(p)

            if sub_iteration == 0:
                cond3 = (p[0] * p[2] * p[4]) == 0   # P2*P4*P6
                cond4 = (p[2] * p[4] * p[6]) == 0   # P4*P6*P8
            else:
                cond3 = (p[0] * p[2] * p[6]) == 0   # P2*P4*P8
                cond4 = (p[0] * p[4] * p[6]) == 0   # P2*P6*P8

            removable = (
                (image == 1)
                & (neighbours >= 2) & (neighbours <= 6)
                & (transitions == 1)
                & cond3 & cond4
            )
            if removable.any():
                image[removable] = 0
                changed = True

        if not changed:
            break
    else:
        logger.warning("细化未在 %d 轮内收敛，按当前结果继续", max_iterations)

    return image.astype(bool)


# ---------------------------------------------------------------------------
# 骨架 → 折线
# ---------------------------------------------------------------------------

_ORTHOGONAL = [(0, -1), (-1, 0), (1, 0), (0, 1)]
_DIAGONAL = [(-1, -1), (1, -1), (-1, 1), (1, 1)]


def _build_graph(skeleton: np.ndarray) -> Dict[Point, List[Point]]:
    """骨架像素的邻接表，**丢掉冗余的对角边**。

    这一步不做的话什么都跑不通。斜线在像素网格上是阶梯状的，比如
    (0,0)(1,0)(1,1)(2,1)：(0,0) 和 (1,1) 在八连通下也算相邻，于是和
    (0,0)-(1,0)-(1,1) 这条正交通路组成一个三角形，度数凭空多出来一。
    结果整条骨架上一大半像素的度都不是 2，链在每个阶梯处都被打断——
    实测一条完整的灯泡轮廓会碎成几百段长度为 1 的「折线」。

    规则很简单：一条对角边如果能绕着两个正交邻居走过去，它就是多余的。
    去掉之后阶梯变成规规矩矩的正交链，度数恢复正常。
    """
    ys, xs = np.nonzero(skeleton)
    pixels: Set[Point] = set(zip(xs.tolist(), ys.tolist()))

    graph: Dict[Point, List[Point]] = {}
    for x, y in pixels:
        neighbours = [(x + dx, y + dy) for dx, dy in _ORTHOGONAL
                      if (x + dx, y + dy) in pixels]
        for dx, dy in _DIAGONAL:
            if (x + dx, y + dy) not in pixels:
                continue
            # 能从正交方向绕过去，这条对角线就是阶梯造出来的多余边
            if (x + dx, y) in pixels or (x, y + dy) in pixels:
                continue
            neighbours.append((x + dx, y + dy))
        graph[(x, y)] = neighbours
    return graph


def trace(skeleton: np.ndarray) -> List[Polyline]:
    """把骨架拆成一条条折线。

    先从端点和交叉点出发走完所有链，再处理剩下的纯环（比如一个圆圈，
    整条骨架上每个点的度都是 2，没有任何端点可以起步）。
    """
    graph = _build_graph(skeleton)
    used: Set[frozenset] = set()
    paths: List[Polyline] = []

    def walk(start: Point, first: Point) -> Polyline:
        path = [start, first]
        used.add(frozenset((start, first)))
        previous, current = start, first
        while len(graph[current]) == 2:
            nxt = next((n for n in graph[current] if n != previous), None)
            if nxt is None or frozenset((current, nxt)) in used:
                break
            used.add(frozenset((current, nxt)))
            path.append(nxt)
            previous, current = current, nxt
        return path

    # 度不为 2 的点：端点（1）和交叉点（>=3）
    nodes = [p for p, neighbours in graph.items() if len(neighbours) != 2]
    for node in sorted(nodes):
        for neighbour in graph[node]:
            if frozenset((node, neighbour)) not in used:
                paths.append(walk(node, neighbour))

    # 剩下的都是闭环
    for pixel in sorted(graph):
        for neighbour in graph[pixel]:
            if frozenset((pixel, neighbour)) not in used:
                loop = walk(pixel, neighbour)
                if loop[-1] != loop[0] and pixel in graph[loop[-1]]:
                    loop.append(pixel)   # 闭合
                paths.append(loop)

    return paths


# ---------------------------------------------------------------------------
# 简化与归一化
# ---------------------------------------------------------------------------

def simplify(points: Sequence[Point], epsilon: float = SIMPLIFY_EPSILON) -> Polyline:
    """Ramer–Douglas–Peucker：丢掉对形状没有贡献的中间点。"""
    if len(points) < 3:
        return list(points)

    start, end = points[0], points[-1]
    dx, dy = end[0] - start[0], end[1] - start[1]
    span = math.hypot(dx, dy)

    if span == 0:
        # 闭环：首尾重合，退化成点到点的距离
        distances = [math.hypot(p[0] - start[0], p[1] - start[1]) for p in points]
    else:
        distances = [
            abs(dy * (p[0] - start[0]) - dx * (p[1] - start[1])) / span for p in points
        ]

    index = int(np.argmax(distances))
    if distances[index] <= epsilon:
        return [start, end]

    left = simplify(points[: index + 1], epsilon)
    right = simplify(points[index:], epsilon)
    return left[:-1] + right


def _polyline_length(points: Sequence[Point]) -> float:
    return sum(
        math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:])
    )


def to_paths(polylines: Sequence[Polyline], extent: float = CONTENT_EXTENT) -> List[str]:
    """折线 → 100x100 viewBox 里的 SVG path，等比缩放并居中。

    按长度从长到短排序：先画主体轮廓再补细节，和人的作画顺序一致，
    也和内置简笔画的书写顺序一致。
    """
    points = [p for line in polylines for p in line]
    if not points:
        return []

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    scale = extent / max(1e-6, max(max_x - min_x, max_y - min_y))

    offset_x = (100 - (max_x - min_x) * scale) / 2
    offset_y = (100 - (max_y - min_y) * scale) / 2

    def place(point: Point) -> Tuple[float, float]:
        return ((point[0] - min_x) * scale + offset_x,
                (point[1] - min_y) * scale + offset_y)

    ordered = sorted(polylines, key=_polyline_length, reverse=True)
    return [_smooth_path([place(p) for p in line]) for line in ordered]


def _smooth_path(points: Sequence[Tuple[float, float]]) -> str:
    """折线 → 平滑的 SVG path。

    RDP 之后剩下的是折线，直接输出 `L` 会让圆弧变成看得见的多边形——灯泡的
    球面尤其明显。这里用经典的「过中点画二次贝塞尔」把拐角抹圆：每个顶点当
    控制点，相邻两点的中点当锚点，曲线自然穿过去。

    和兜底涂鸦用的是同一个手法，所以 AI 生成的图和内置简笔画画出来笔感一致。
    """
    if len(points) < 3:
        head = f"M {points[0][0]:.1f} {points[0][1]:.1f}"
        tail = " ".join(f"L {x:.1f} {y:.1f}" for x, y in points[1:])
        return f"{head} {tail}".strip()

    parts = [f"M {points[0][0]:.1f} {points[0][1]:.1f}"]
    for current, following in zip(points[1:-1], points[2:]):
        mid_x = (current[0] + following[0]) / 2
        mid_y = (current[1] + following[1]) / 2
        parts.append(f"Q {current[0]:.1f} {current[1]:.1f} {mid_x:.1f} {mid_y:.1f}")
    parts.append(f"L {points[-1][0]:.1f} {points[-1][1]:.1f}")
    return " ".join(parts)


# ---------------------------------------------------------------------------

def vectorize(image_path: Path, crop_bottom: float = 0.0,
              min_stroke_ratio: float = MIN_STROKE_RATIO) -> List[str]:
    """线稿位图 → SVG path 列表（100x100 viewBox，已按书写顺序排序）。"""
    mask = load_mask(image_path, crop_bottom=crop_bottom)
    if not mask.any():
        return []

    skeleton = thin(mask)
    diagonal = math.hypot(*skeleton.shape)
    minimum = diagonal * min_stroke_ratio

    polylines = [
        simplified
        for line in trace(skeleton)
        if _polyline_length(line) >= minimum
        and len(simplified := simplify(line)) >= 2
    ]
    logger.info("矢量化 %s：%d 条笔画", image_path.name, len(polylines))
    return to_paths(polylines)
