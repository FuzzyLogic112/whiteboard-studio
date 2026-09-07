from app.jobs import _parse_render_percent
from app.pipeline.tts.base import MIN_SCENE_SECONDS, estimate_duration


def test_parses_remotion_progress():
    assert _parse_render_percent("Rendered 45/180") == 0.25
    assert _parse_render_percent("Encoded 90/180 frames") == 0.5


def test_parses_real_remotion_log_line():
    # 真实日志的分母后面紧跟逗号，按空格切分会解析失败
    assert _parse_render_percent("Rendered 353/503, time remaining: 26s") == 353 / 503


def test_ignores_unrelated_lines():
    assert _parse_render_percent("Bundling...") is None
    assert _parse_render_percent("Rendered nope") is None


def test_zero_total_does_not_divide_by_zero():
    assert _parse_render_percent("Rendered 0/0") is None


def test_short_text_gets_minimum_duration():
    assert estimate_duration("好") == MIN_SCENE_SECONDS


def test_duration_grows_with_length():
    assert estimate_duration("字" * 40) > estimate_duration("字" * 10)
