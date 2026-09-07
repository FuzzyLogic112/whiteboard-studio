"""分词器的行为约束。"""

from app.pipeline.segment import DICT_PATH, segment, words_of


def test_dictionary_ships_with_the_package():
    assert DICT_PATH.exists(), "词典是随仓库分发的资源，缺了分词就跑不起来"


def test_keeps_multi_character_words_together():
    # 最大概率分词的核心价值：不会把「人工智能」切成「人工」+「智能」或更碎
    assert "人工智能" in words_of("人工智能正在改变世界。")


def test_punctuation_becomes_its_own_token():
    words = segment("你好，世界。")
    assert [w.text for w in words if w.pos == "w"] == ["，", "。"]


def test_whitespace_is_dropped():
    assert "".join(words_of("你好  世界")) == "你好世界"


def test_latin_and_digits_survive_as_blocks():
    assert "GPU" in "".join(words_of("需要 GPU 加速"))


def test_pos_comes_from_the_dictionary():
    tags = {w.text: w.pos for w in segment("软件开发的方式")}
    assert tags["软件"].startswith("n")
    assert tags["的"].startswith("u")


def test_unknown_characters_fall_back_to_single_chars():
    words = words_of("砼")
    assert words == ["砼"]


def test_segmentation_is_deterministic():
    assert words_of("架构设计和权衡取舍") == words_of("架构设计和权衡取舍")
