"""关键词提取。

算法是启发式的，所以尽量钉「不能错成什么样」，而不是钉某个具体输出。
"""

from app.pipeline.keywords import extract_keyword, extract_keywords


def test_picks_a_content_word():
    assert extract_keyword("很多人以为写作是天赋。") in {"写作", "天赋"}


def test_does_not_cut_through_a_real_word():
    assert extract_keyword("人工智能正在改变世界。") == "人工智能"


def test_rejects_cross_boundary_fragments():
    # 靠虚词猜边界的老实现会切出「事聊清楚」这种半截短语
    kw = extract_keyword("今天我们把这三件事聊清楚。")
    assert kw == "三件事"


def test_merges_quantifier_and_noun():
    assert extract_keyword("过去我们需要手写每一行代码，") == "一行代码"


def test_merges_nominal_compound():
    assert extract_keyword("但是架构设计和权衡取舍，") == "架构设计"


def test_does_not_merge_two_verbs():
    # 「需要」+「手写」都是动词，拼起来不是一个概念
    assert "需要手写" not in extract_keywords(["过去我们需要手写每一行代码，"])


def test_does_not_merge_time_word_with_noun():
    assert extract_keyword("现在模型可以生成大部分样板。") == "模型"


def test_blacklisted_part_blocks_the_merge():
    # 「很多」在黑名单里，「很多人」也不该冒出来
    assert extract_keyword("很多人以为写作是天赋。") != "很多人"


def test_merged_candidates_get_frequency_credit():
    """合并词也要参与全文词频统计。

    只统计分词结果的话，合并词的词频恒为 0，会被单个词的词频加成系统性压过去
    ——「三次会议」就是这样输给「有效率」的。
    """
    assert extract_keyword("往往比三次会议更有效率。") == "三次会议"


def test_light_verbs_are_rejected():
    assert extract_keyword("仍然需要人来决定。") == "决定"


def test_recurring_word_wins_among_comparable_candidates():
    """跨分镜反复出现的词更可能是主题词。

    用两个同词性、同字数的名词做对照，把词频信号和词性权重隔离开——
    「写作」（动词）对「天赋」（名词）那种比较，两个信号纠缠在一起，
    结果并不说明词频起没起作用。
    """
    recurring = extract_keywords(["流程决定结果。", "流程需要梳理。", "流程写清楚。"])
    assert recurring[0] == "流程"


def test_word_frequency_is_counted_per_scene_not_per_occurrence():
    """一句话里重复三遍不算主题，跨分镜反复出现才算。

    第一镜里「预算」出现三次、「成本」只有一次，但「成本」跨了两镜——
    按出现次数算会选「预算」，按文档频率算才会选「成本」。
    """
    result = extract_keywords(["预算预算预算和成本。", "成本也要控制。"])
    assert result[0] == "成本"


def test_avoids_repeating_previous_keyword():
    result = extract_keywords(["团队协作很重要。", "团队协作需要练习。"])
    assert result[0] != result[1]


def test_keyword_length_is_bounded():
    for kw in extract_keywords(["一段没有任何常见虚词夹杂的超长连续中文内容片段描述"]):
        assert 1 <= len(kw) <= 4


def test_all_function_words_still_returns_something():
    assert extract_keyword("的了是在。")
