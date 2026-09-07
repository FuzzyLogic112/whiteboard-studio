"""分镜切分的行为约束。"""

from app.pipeline.script import MAX_CHARS, split_script


def test_splits_on_sentence_end():
    text = "这是第一个完整的句子。这是第二个完整的句子。"
    assert split_script(text) == ["这是第一个完整的句子。", "这是第二个完整的句子。"]


def test_very_short_sentences_merge_into_one_scene():
    # 每句都不到 MIN_CHARS，分开显示会一闪而过，合成一镜更合理
    assert split_script("好的。行吧。") == ["好的。行吧。"]


def test_long_sentence_is_cut_at_clause_breaks():
    text = "这是一个相当长的句子，它有好几个分句，需要被切开，否则字幕一行放不下。"
    scenes = split_script(text)
    assert len(scenes) > 1
    assert all(len(s) <= MAX_CHARS for s in scenes)
    # 切开后拼回去必须和原文一致，不能吞字
    assert "".join(scenes) == text


def test_sentence_without_punctuation_is_hard_cut():
    text = "啊" * 100
    scenes = split_script(text)
    assert all(len(s) <= MAX_CHARS for s in scenes)
    assert "".join(scenes) == text


def test_short_fragment_merges_into_previous():
    scenes = split_script("这是一个足够长的开头句子。好。")
    assert len(scenes) == 1


def test_newline_is_a_hard_break():
    # 即使两段都短于 MIN_CHARS，也不能跨段合并
    assert split_script("上半段\n下半段") == ["上半段", "下半段"]


def test_empty_input():
    assert split_script("") == []
    assert split_script("   \n  ") == []
