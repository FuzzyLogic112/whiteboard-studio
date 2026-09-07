from app.pipeline.sketch import GLYPHS, TRIGGERS, pick_concept, pick_concepts, strokes_for


# -- 概念选择 ---------------------------------------------------------------

def test_longer_trigger_wins_over_shorter():
    # 「人」和「智能」都命中，应该按更具体的那个画
    assert pick_concept("人工智能", "人工智能正在改变世界") == "code"


def test_single_char_triggers_do_not_match_the_sentence():
    """否则几乎每句中文都含「我」或「人」，满屏都是小人图。"""
    assert pick_concept("流程", "我们的流程需要梳理") == "gear"


def test_single_char_trigger_still_works_on_the_keyword():
    assert pick_concept("云", "") == "cloud"


def test_unknown_keyword_falls_back_to_doodle():
    concept, strokes = strokes_for("薛定谔", "一句没有触发词的话")
    assert concept == "doodle"
    assert strokes


def test_every_trigger_maps_to_a_real_glyph():
    for concept, _ in TRIGGERS:
        assert concept in GLYPHS, f"触发表引用了不存在的简笔画：{concept}"


# -- 相邻去重 ---------------------------------------------------------------

def test_adjacent_scenes_avoid_the_same_picture():
    concepts = pick_concepts(
        ["沟通", "会议安排"],
        ["沟通是最大的成本。", "会议安排要提前定。"],
    )
    assert concepts[0] != concepts[1]


def test_repeat_is_kept_rather_than_substituting_a_weak_match():
    """画对但重复，好过画错。

    「一行代码」的次优候选是句子里那个「我」触发的小人图，让给它更糟。
    """
    concepts = pick_concepts(
        ["人工智能", "一行代码"],
        ["人工智能正在改变开发方式。", "过去我们需要手写每一行代码。"],
    )
    assert concepts == ["code", "code"]


def test_consecutive_doodles_are_allowed():
    # 涂鸦由关键词哈希决定，图形天然不同，不需要去重
    concepts = pick_concepts(["薛定谔", "海森堡"], ["一句话。", "另一句话。"])
    assert concepts == ["doodle", "doodle"]


# -- 笔迹 -------------------------------------------------------------------

def test_doodle_is_deterministic():
    a = strokes_for("薛定谔", "")[1]
    b = strokes_for("薛定谔", "")[1]
    assert [s.d for s in a] == [s.d for s in b]


def test_explicit_concept_overrides_detection():
    concept, strokes = strokes_for("人工智能", "人工智能", concept="balance")
    assert concept == "balance"
    assert [s.d for s in strokes] == [
        s.d for s in strokes_for("", "", concept="balance")[1]
    ]


def test_stroke_timing_covers_draw_ratio_without_overlap():
    _, strokes = strokes_for("团队协作", "团队协作最大的成本")
    assert abs(sum(s.span for s in strokes) - 0.62) < 1e-6
    # start/span 都四舍五入到 4 位，允许一点点量化误差，但不能累积成缝
    for prev, cur in zip(strokes, strokes[1:]):
        assert abs((prev.start + prev.span) - cur.start) < 1e-3
    assert strokes[0].start == 0.0


def test_every_glyph_path_is_wellformed():
    for concept, paths in GLYPHS.items():
        assert paths, concept
        for path in paths:
            assert path.startswith("M "), (concept, path)


def test_glyphs_start_inside_the_viewbox():
    """坐标系是 100x100 的 viewBox，起笔跑到外面就会被裁掉。

    只检查起笔的绝对 M 坐标：path 里的其它数字可能来自 `m`/`a` 这类相对指令，
    负数在那里是位移而不是坐标。
    """
    for concept, paths in GLYPHS.items():
        for path in paths:
            _, x, y = path.split(maxsplit=3)[:3]
            assert -5 <= float(x) <= 105, (concept, path)
            assert -5 <= float(y) <= 105, (concept, path)
