"""把关键词变成一组「画得出来」的笔迹。

白板动画的观感几乎全部来自笔迹本身：一条 SVG path 配合 stroke-dashoffset
就能做出「正在被画出来」的效果，所以这里的产物是一组 path 的 d 属性，
坐标统一在 100x100 的 viewBox 里，由渲染层负责缩放和摆位。

命中内置概念时画对应的简笔画；命不中就按关键词的哈希生成一个确定性的
涂鸦——同一个词永远画出同一张图，这样重渲染的结果是可复现的。

要接入 AI 生图，在 `strokes_for` 里加一个分支：把生成的位图矢量化成 path
即可，下游不需要任何改动。
"""

from __future__ import annotations

import hashlib
import math
from typing import Dict, List, Sequence, Tuple

from ..models import Stroke

# ---------------------------------------------------------------------------
# 内置简笔画。每个概念是一串 SVG path，按书写顺序排列（先画主体，后画细节）。
# ---------------------------------------------------------------------------

GLYPHS: Dict[str, List[str]] = {
    "person": [
        "M 50 24 m -12 0 a 12 12 0 1 0 24 0 a 12 12 0 1 0 -24 0",
        "M 50 36 L 50 64",
        "M 28 46 L 72 44",
        "M 50 64 L 34 88",
        "M 50 64 L 66 88",
    ],
    "idea": [
        "M 50 20 C 32 20 23 34 30 47 C 33 53 39 57 39 64 L 61 64 C 61 57 67 53 70 47 C 77 34 68 20 50 20 Z",
        "M 42 71 L 58 71",
        "M 45 79 L 55 79",
        "M 50 10 L 50 3",
        "M 20 26 L 12 20",
        "M 80 26 L 88 20",
    ],
    "growth": [
        "M 18 84 L 18 14",
        "M 18 84 L 88 84",
        "M 30 84 L 30 62",
        "M 46 84 L 46 46",
        "M 62 84 L 62 30",
        "M 24 68 L 40 54 L 54 60 L 82 26",
        "M 68 24 L 82 24 L 82 38",
    ],
    "gear": [
        "M 50 22 a 28 28 0 1 0 0.1 0",
        "M 50 40 a 10 10 0 1 0 0.1 0",
        "M 50 8 L 50 22",
        "M 50 78 L 50 92",
        "M 8 50 L 22 50",
        "M 78 50 L 92 50",
        "M 21 21 L 31 31",
        "M 69 69 L 79 79",
    ],
    "cloud": [
        "M 28 70 C 13 70 13 49 29 49 C 29 30 57 26 63 43 C 79 39 89 54 82 64 C 90 68 87 70 78 70 Z",
    ],
    "book": [
        "M 50 30 C 40 21 24 21 15 25 L 15 78 C 24 74 40 74 50 82",
        "M 50 30 C 60 21 76 21 85 25 L 85 78 C 76 74 60 74 50 82",
        "M 50 30 L 50 82",
    ],
    "time": [
        "M 50 16 a 34 34 0 1 0 0.1 0",
        "M 50 50 L 50 28",
        "M 50 50 L 67 59",
    ],
    "arrow": [
        "M 12 50 L 78 50",
        "M 60 33 L 80 50 L 60 67",
    ],
    "star": [
        "M 50 12 L 61 40 L 91 42 L 68 61 L 76 90 L 50 73 L 24 90 L 32 61 L 9 42 L 39 40 Z",
    ],
    "home": [
        "M 12 52 L 50 17 L 88 52",
        "M 23 46 L 23 86 L 77 86 L 77 46",
        "M 41 86 L 41 63 L 59 63 L 59 86",
    ],
    "question": [
        "M 31 35 C 31 15 69 15 69 37 C 69 54 50 54 50 68",
        "M 50 79 L 50 84",
    ],
    "check": [
        "M 16 52 L 40 78 L 86 20",
    ],
    "risk": [
        "M 50 13 L 90 85 L 10 85 Z",
        "M 50 40 L 50 63",
        "M 50 73 L 50 77",
    ],
    "money": [
        "M 50 14 a 36 36 0 1 0 0.1 0",
        "M 33 34 L 50 54 L 67 34",
        "M 35 58 L 65 58",
        "M 35 70 L 65 70",
        "M 50 54 L 50 80",
    ],
    "link": [
        "M 41 59 L 59 41",
        "M 35 45 C 24 34 35 17 47 27 L 55 35",
        "M 65 55 C 76 66 65 83 53 73 L 45 65",
    ],
    "search": [
        "M 43 41 a 24 24 0 1 0 0.1 0",
        "M 61 60 L 85 86",
    ],
    "team": [
        "M 30 32 m -9 0 a 9 9 0 1 0 18 0 a 9 9 0 1 0 -18 0",
        "M 70 32 m -9 0 a 9 9 0 1 0 18 0 a 9 9 0 1 0 -18 0",
        "M 14 78 C 14 56 46 56 46 78",
        "M 54 78 C 54 56 86 56 86 78",
    ],
    "target": [
        "M 50 14 a 36 36 0 1 0 0.1 0",
        "M 50 30 a 20 20 0 1 0 0.1 0",
        "M 50 44 a 6 6 0 1 0 0.1 0",
    ],
    "doc": [
        "M 24 12 L 62 12 L 78 30 L 78 88 L 24 88 Z",
        "M 62 12 L 62 30 L 78 30",
        "M 34 44 L 68 44",
        "M 34 56 L 68 56",
        "M 34 68 L 56 68",
    ],
    "code": [
        "M 34 30 L 12 50 L 34 70",
        "M 66 30 L 88 50 L 66 70",
        "M 57 22 L 43 78",
    ],
}

# 概念触发词。命中即用对应简笔画；一句话里出现多个时，先出现的优先。
TRIGGERS: Sequence[Tuple[str, Sequence[str]]] = (
    ("team", ("团队", "协作", "合作", "大家", "同事", "组织", "群体", "社区", "用户")),
    ("person", ("人", "我", "你", "他", "她", "自己", "个人", "读者", "观众")),
    ("idea", ("想法", "灵感", "创意", "点子", "思路", "洞察", "发现", "启发", "创新")),
    ("growth", ("增长", "提升", "上升", "趋势", "数据", "指标", "效率", "进步", "改善", "业绩")),
    ("gear", ("系统", "流程", "机制", "架构", "引擎", "自动", "工程", "运转", "配置")),
    ("cloud", ("云", "网络", "在线", "服务", "平台", "互联网", "远程")),
    ("book", ("学习", "知识", "书", "阅读", "课程", "教程", "理论", "笔记")),
    ("time", ("时间", "效率", "速度", "周期", "节奏", "及时", "延迟", "多久", "小时")),
    ("money", ("成本", "收益", "利润", "价格", "投入", "回报", "预算", "钱", "商业", "付费")),
    ("risk", ("风险", "问题", "危险", "警告", "错误", "失败", "陷阱", "注意", "麻烦", "隐患")),
    ("check", ("完成", "正确", "成功", "达成", "通过", "解决", "搞定", "确认")),
    ("question", ("为什么", "疑问", "困惑", "不确定", "如何", "怎么", "是否", "什么")),
    ("search", ("分析", "研究", "调查", "查找", "观察", "洞察", "定位", "排查", "细节")),
    ("link", ("连接", "关联", "关系", "结合", "整合", "打通", "衔接", "联系")),
    ("target", ("目标", "重点", "核心", "关键", "聚焦", "方向", "定位", "命中")),
    ("doc", ("文档", "报告", "文章", "写作", "内容", "文案", "记录", "总结", "方案")),
    ("code", ("代码", "编程", "开发", "程序", "软件", "脚本", "算法", "模型", "技术", "人工智能", "智能", "AI")),
    ("home", ("公司", "企业", "家", "房", "机构", "本地", "内部")),
    ("arrow", ("导致", "因此", "所以", "流向", "转化", "变成", "推动", "带来")),
    ("star", ("优势", "亮点", "推荐", "最佳", "精彩", "价值", "重要")),
)

DEFAULT_CONCEPT = "idea"


def pick_concept(keyword: str, sentence: str = "") -> str:
    """先在关键词里找触发词，找不到再看整句，都没有就走涂鸦。

    命中多个时先比触发词长度：「人工智能」里的「智能」比「人」更能说明画
    什么。长度相同才比出现位置。
    """
    for haystack in (keyword, sentence):
        if not haystack:
            continue
        best: Tuple[int, int, str] | None = None
        for concept, words in TRIGGERS:
            for word in words:
                pos = haystack.find(word)
                if pos < 0:
                    continue
                key = (-len(word), pos, concept)
                if best is None or key < best:
                    best = key
        if best is not None:
            return best[2]
    return "doodle"


# ---------------------------------------------------------------------------
# 兜底涂鸦：由关键词哈希确定，同词同图，可复现
# ---------------------------------------------------------------------------

def _rng(seed_text: str):
    """一个够用的确定性伪随机流：对哈希做游标推进。"""
    digest = hashlib.sha256(seed_text.encode("utf-8")).digest()
    state = int.from_bytes(digest[:8], "big")

    def nxt(lo: float, hi: float) -> float:
        nonlocal state
        state = (state * 6364136223846793005 + 1442695040888963407) & ((1 << 64) - 1)
        return lo + (state >> 11) / float(1 << 53) * (hi - lo)

    return nxt


def _doodle(keyword: str) -> List[str]:
    """围绕中心画一个多边闭合图形，再加两三笔装饰。"""
    nxt = _rng(keyword)
    sides = int(nxt(5, 8.99))
    cx, cy, base_r = 50.0, 48.0, 26.0

    points: List[Tuple[float, float]] = []
    for i in range(sides):
        angle = 2 * math.pi * i / sides - math.pi / 2
        r = base_r * nxt(0.72, 1.18)
        points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))

    # 用二次贝塞尔把折线抹圆，看起来更像随手画的
    d = f"M {points[0][0]:.1f} {points[0][1]:.1f}"
    for i in range(1, sides + 1):
        cur = points[i % sides]
        prev = points[i - 1]
        mx, my = (prev[0] + cur[0]) / 2, (prev[1] + cur[1]) / 2
        d += f" Q {prev[0]:.1f} {prev[1]:.1f} {mx:.1f} {my:.1f}"
    d += " Z"

    strokes = [d]
    for _ in range(int(nxt(2, 3.99))):
        x1, y1 = nxt(24, 76), nxt(28, 70)
        strokes.append(f"M {x1:.1f} {y1:.1f} L {x1 + nxt(-18, 18):.1f} {y1 + nxt(-14, 14):.1f}")
    return strokes


# ---------------------------------------------------------------------------

def strokes_for(keyword: str, sentence: str = "", draw_ratio: float = 0.62) -> Tuple[str, List[Stroke]]:
    """返回 (概念名, 笔迹列表)。

    draw_ratio 是画完整幅图占用镜头时长的比例，剩下的时间留给观众读字幕。
    每一笔的时间片按 path 的粗略长度分配，长笔画得久，短笔一带而过——
    等分会让一条长曲线唰地一下画完，很出戏。
    """
    concept = pick_concept(keyword, sentence)
    paths = GLYPHS[concept] if concept in GLYPHS else _doodle(keyword)

    weights = [max(1.0, _rough_length(p)) for p in paths]
    total = sum(weights)

    strokes: List[Stroke] = []
    cursor = 0.0
    for path, weight in zip(paths, weights):
        span = draw_ratio * weight / total
        strokes.append(
            Stroke(
                d=path,
                width=2.6 if len(paths) <= 3 else 2.2,
                start=round(cursor, 4),
                span=round(span, 4),
            )
        )
        cursor += span
    return concept, strokes


def _rough_length(path: str) -> float:
    """粗估 path 长度：把所有坐标点当折线顶点算距离。

    真实弧长要解析贝塞尔，但这里只用来分配时间片，量级对就够了。
    """
    numbers: List[float] = []
    token = ""
    for ch in path:
        if ch.isdigit() or ch in ".-":
            token += ch
        else:
            if token:
                try:
                    numbers.append(float(token))
                except ValueError:
                    pass
                token = ""
    if token:
        try:
            numbers.append(float(token))
        except ValueError:
            pass

    length = 0.0
    for i in range(2, len(numbers) - 1, 2):
        dx = numbers[i] - numbers[i - 2]
        dy = numbers[i + 1] - numbers[i - 1]
        length += math.hypot(dx, dy)
    return length
