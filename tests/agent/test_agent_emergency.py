import pytest

from chaoba.agent.emergency import spot, emergency_reply, FLAG_EMERGENCY_TOOL

TRUE_POSITIVES = [
    ("Hồi sáng tui bị té trong nhà tắm", "fall"),
    ("Tui té ngã ngoài sân nè con", "fall"),
    ("Bà ngã một cái đau quá", "fall"),
    ("Tui thấy tức ngực quá con ơi", "chest_pain"),
    ("Đau ngực từ hồi khuya tới giờ", "chest_pain"),
    ("Khó thở quá con", "breathing"),
    ("Tui thở hổng được nữa", "breathing"),
    ("Hồi nãy tui xỉu một chút", "syncope"),
    ("Tui hổng muốn sống nữa", "self_harm"),
    ("Buồn quá muốn chết cho rồi", "self_harm"),
    ("Sáng dậy thấy méo miệng, nói đớ", "stroke_signs"),
    ("tui bi te o nha tam", "fall"),          # typed without diacritics
    ("kho tho qua con oi", "breathing"),
]
FALSE_POSITIVES = [
    "Kinh tế dạo này khó khăn quá",          # tế != té
    "Té ra là thằng Tư nó về hồi hôm",        # "té ra" = it turns out
    "Tới ngã ba thì quẹo trái",               # crossroads
    "Nước Nga lạnh lắm",                      # Russia
    "Mệt muốn chết luôn mà vui",              # hyperbole
    "Tui hổng có té đâu con",                 # negated
    "Bà không khó thở gì hết",                # negated
    "Tui sợ té nên đi chậm",                  # fear of falling, not a fall
    "Sáng nay ăn cháo, ngủ ngon",
    "Tế lễ ở đình vui lắm",
    "",
]


@pytest.mark.parametrize("text,cat", TRUE_POSITIVES)
def test_true_positives(text, cat):
    hit = spot(text)
    assert hit is not None, text
    assert hit.category == cat
    assert hit.quote == text.strip()


@pytest.mark.parametrize("text", FALSE_POSITIVES)
def test_false_positives(text):
    assert spot(text) is None, text


def test_reply_mentions_115_and_family_no_diagnosis():
    r = emergency_reply("chest_pain", "bà", "Lan")
    assert "115" in r and "Lan" in r
    for bad in ("đột quỵ", "nhồi máu", "bệnh"):
        assert bad not in r
    assert "115" in emergency_reply("self_harm", "ông", None)


def test_tool_schema_strict():
    assert FLAG_EMERGENCY_TOOL["name"] == "flag_emergency"
    assert FLAG_EMERGENCY_TOOL["strict"] is True
    assert FLAG_EMERGENCY_TOOL["input_schema"]["additionalProperties"] is False
