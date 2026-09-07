from app.pipeline.sketch import GLYPHS, pick_concept, strokes_for


def test_longer_trigger_wins_over_shorter():
    # 「人」和「智能」都命中，应该按更具体的那个画
    assert pick_concept("人工智能", "人工智能正在改变世界") == "code"


def test_unknown_keyword_falls_back_to_doodle():
    concept, strokes = strokes_for("薛定谔", "一句没有触发词的话")
    assert concept == "doodle"
    assert strokes


def test_doodle_is_deterministic():
    a = strokes_for("薛定谔", "")[1]
    b = strokes_for("薛定谔", "")[1]
    assert [s.d for s in a] == [s.d for s in b]


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
