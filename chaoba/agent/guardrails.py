"""Deterministic guardrails applied to every elder turn (before the engine) and every agent reply (after).

- Anti-scam: never discuss money transfers, bank accounts, OTP codes, passwords, prizes.
- No medication changes: questions about stopping/doubling/changing medicine -> refer to the doctor.
- No diagnosis: requests for "what disease do I have" -> refer to the doctor; agent replies are scrubbed of
  disease names (the agent must never name a condition).
- Opt-out: "đừng gọi nữa", "không muốn nói chuyện" -> confirmation flow, then record and stop scheduling.
"""
from __future__ import annotations

import re

from .textnorm import normalize, contains_phrase, strip_diacritics, has_vietnamese_diacritics

SCAM_PHRASES = [
    "chuyển tiền", "chuyển khoản", "số tài khoản", "tài khoản ngân hàng", "ngân hàng", "mã otp", "otp",
    "mã xác nhận", "mã xác thực", "mật khẩu", "mã pin", "số thẻ", "thẻ atm", "thẻ tín dụng", "mượn tiền",
    "gửi tiền", "trúng thưởng", "nhận quà", "đóng phí", "nộp phạt", "công an gọi", "căn cước", "cccd",
    "ví điện tử", "momo", "zalopay",
]
MEDICATION_CHANGE_PHRASES = [
    "bỏ thuốc", "ngưng thuốc", "ngừng thuốc", "đổi thuốc", "uống thêm thuốc", "uống gấp đôi", "uống hai viên",
    "tăng liều", "giảm liều", "bớt thuốc", "thôi uống thuốc", "uống thuốc gì", "có nên uống", "nên uống thuốc",
    "mua thuốc gì",
]
DIAGNOSIS_REQUEST_PHRASES = [
    "bị bệnh gì", "bệnh gì vậy", "có phải bị", "có bị bệnh", "bị gì vậy con", "mắc bệnh gì", "chẩn đoán",
    "tui bị lẫn", "bị lú lẫn hả", "có bị lẫn",
]
OPT_OUT_PHRASES = [
    "đừng gọi nữa", "đừng gọi tui nữa", "đừng có gọi nữa", "không muốn nói chuyện", "hổng muốn nói chuyện",
    "hông muốn nói chuyện", "khỏi gọi", "thôi đừng gọi", "không cần gọi nữa", "hổng cần gọi nữa",
    "ngưng gọi", "dừng gọi", "đừng gọi điện nữa",
]
YES_WORDS = ["dạ", "ừ", "ừa", "đúng", "phải", "ờ", "vâng", "có", "được", "ok", "chắc chắn", "đúng rồi", "phải rồi"]
NO_WORDS = ["không", "hổng", "hông", "thôi khỏi", "không phải", "hổng phải", "chưa", "để sau", "bận", "khoan"]

# Words the agent must never say as a finding. Replies containing them are replaced.
FORBIDDEN_IN_REPLY = [
    "sa sút trí tuệ", "mất trí nhớ", "alzheimer", "dementia", "trầm cảm", "depression", "parkinson",
    "đột quỵ", "tai biến", "chẩn đoán", "ung thư", "tiểu đường", "suy tim",
]


def _match_any(text: str, phrases: list[str]) -> str | None:
    n = normalize(text)
    if has_vietnamese_diacritics(text) or not n:
        for p in phrases:
            if contains_phrase(n, p):
                return p
        return None
    s = strip_diacritics(n)
    for p in phrases:
        sp = strip_diacritics(p)
        if (" " in sp or len(sp) > 3) and contains_phrase(s, sp):
            return p
    return None


def detect_scam(text: str) -> str | None:
    return _match_any(text, SCAM_PHRASES)


def detect_medication_change(text: str) -> str | None:
    return _match_any(text, MEDICATION_CHANGE_PHRASES)


def detect_diagnosis_request(text: str) -> str | None:
    return _match_any(text, DIAGNOSIS_REQUEST_PHRASES)


def detect_opt_out(text: str) -> str | None:
    return _match_any(text, OPT_OUT_PHRASES)


def is_yes(text: str) -> bool:
    n = normalize(text)
    if not n:
        return False
    if any(contains_phrase(n, w) for w in ("không phải", "hổng phải", "không", "hổng", "hông", "chưa")):
        # "dạ không" is a no
        return False
    return any(contains_phrase(n, w) for w in YES_WORDS)


def is_no(text: str) -> bool:
    n = normalize(text)
    return any(contains_phrase(n, w) for w in NO_WORDS)


def scam_reply(h: str = "bà") -> str:
    return (f"Dạ, chuyện tiền bạc, ngân hàng con hổng hỏi và hổng giúp được. "
            f"Ai xin mã số qua điện thoại {h} đừng đưa nha. Mình nói chuyện khác nghen {h}.")


def medication_reply(h: str = "bà") -> str:
    return (f"Dạ, chuyện đổi thuốc con hổng dám khuyên. {h.capitalize()} hỏi bác sĩ giùm con nha. "
            f"{h.capitalize()} cứ uống như bác sĩ dặn nghen.")


def diagnosis_reply(h: str = "bà") -> str:
    return (f"Dạ, con là trợ lý ảo, con hổng biết khám bệnh. Có gì lạ {h} hỏi bác sĩ nha, "
            f"con cũng nhắn người nhà để ý.")


def opt_out_confirm(h: str = "bà") -> str:
    return f"Dạ, {h} muốn con ngưng gọi mỗi sáng phải hông {h}?"


def opt_out_done(h: str = "bà", family: str | None = None) -> str:
    fam = f"cô {family}" if family else "người nhà"
    return (f"Dạ, con ghi nhận rồi. Con sẽ ngưng gọi và báo {fam} biết. "
            f"Khi nào {h} muốn nói chuyện lại thì nhắn {fam} nha. Con chào {h}.")


def opt_out_cancel(h: str = "bà") -> str:
    return f"Dạ, vậy con vẫn gọi {h} mỗi sáng nha. Mình nói chuyện tiếp nghen {h}."


_SAFE_FALLBACK = "Dạ, con nghe {h} nói rồi. {H} kể thêm cho con nghe với?"


def scrub_reply(reply: str, h: str = "bà") -> str:
    """Last line of defence on agent output: no disease names, no money requests."""
    n = normalize(reply)
    for w in FORBIDDEN_IN_REPLY:
        if contains_phrase(n, w):
            return _SAFE_FALLBACK.format(h=h, H=h.capitalize())
    if re.search(r"\b(otp|số tài khoản|mật khẩu)\b", n):
        return _SAFE_FALLBACK.format(h=h, H=h.capitalize())
    return reply.strip()
