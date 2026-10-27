import pytest

from chaoba.core.metrics import compute_call_metrics, count_syllables, mattr, tokenize
from chaoba.core.models import Turn


def test_count_syllables_basic():
    assert count_syllables("Bà ăn cháo, tưới cây mai.") == 6
    assert count_syllables("Ờ... hôm nay   con khỏe!") == 5
    assert count_syllables("") == 0
    assert count_syllables("  ,.!? -- ") == 0


def test_numbers_and_hyphens():
    assert count_syllables("uống 2 viên lúc 7 giờ") == 4  # digits are not counted
    assert tokenize("Ừ-ừ, CHỢ/quán") == ["ừ", "ừ", "chợ", "quán"]


def test_nfd_input_normalised():
    import unicodedata
    s = unicodedata.normalize("NFD", "chóng mặt")
    assert tokenize(s) == ["chóng", "mặt"]


def _call(text_words, dur, pauses):
    return [
        Turn("agent", "Chào bà, hôm nay bà khỏe không?", 0.0, 2.0),
        Turn("elder", text_words, 2.0, 2.0 + dur, pauses),
    ]


def test_handcrafted_call():
    words = " ".join(["ờ"] * 10 + [f"từ{i % 50}" for i in range(190)])  # 200 tokens, 10 fillers
    m = compute_call_metrics(_call(words, 60.0, [0.5, 1.0, 2.5, 5.0, 0.2]))
    # voiced = 60 - (0.5+1+2.5+5) = 51 ; pauses counted (0.4-3s) = 4.0
    assert m.elder_speech_sec == pytest.approx(51.0)
    assert m.word_count == 200
    assert m.speech_rate_sps == pytest.approx(200 / 51, abs=1e-3)
    assert m.pause_ratio == pytest.approx(4.0 / 60, abs=1e-3)
    assert m.filled_pause_rate == pytest.approx(0.05)
    assert m.mattr is not None and 0 < m.mattr <= 1
    assert m.valid and m.invalid_reason is None


def test_agent_turns_ignored_and_too_short():
    m = compute_call_metrics(_call("con khỏe lắm bà ơi", 20.0, []))
    assert m.word_count == 5
    assert not m.valid and m.invalid_reason == "too_short"
    assert m.mattr is None  # < 60 tokens


def test_mattr_values():
    assert mattr(["a"] * 59) is None
    assert mattr([f"w{i}" for i in range(80)]) == pytest.approx(1.0)
    assert mattr(["a", "b"] * 40) == pytest.approx(2 / 40)
