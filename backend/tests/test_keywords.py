"""关键词提取是启发式的，所以只钉住「不能错成什么样」。"""

from app.pipeline.keywords import extract_keyword, extract_keywords


def test_picks_content_word_not_function_word():
    # 「写作」和「天赋」都可接受，但绝不能选到虚词或夹着虚词的碎片
    assert extract_keyword("很多人以为写作是天赋。") in {"写作", "天赋"}


def test_frequent_word_wins_across_the_whole_script():
    # 「写作」在全文重复出现，应该盖过只出现一次的「天赋」
    result = extract_keywords(["很多人以为写作是天赋。", "写作需要练习。", "坚持写作。"])
    assert result[0] == "写作"


def test_does_not_cut_through_a_real_word():
    # 「能」不该被当虚词切掉，否则「人工智能」会变成「人工智」
    assert extract_keyword("人工智能正在改变世界。") == "改变世界"
    assert "人工智" not in (extract_keyword("人工智能很重要。"),)


def test_rejects_half_phrases_with_bad_head():
    assert extract_keyword("谁都能进步。") == "进步"


def test_avoids_repeating_previous_keyword():
    result = extract_keywords(["团队协作很重要。", "团队协作需要练习。"])
    assert result[0] != result[1]


def test_keyword_length_is_bounded():
    for kw in extract_keywords(["一段没有任何常见虚词夹杂的超长连续中文内容片段描述"]):
        assert 1 <= len(kw) <= 6


def test_all_function_words_still_returns_something():
    assert extract_keyword("的了是在。")
