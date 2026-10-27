from chaoba.agent.persona import ElderView
from chaoba.agent.prompts import DailyContext, recall_from_fact

PROFILE = {
    "id": "hanh", "display_name": "Bà Hạnh", "name_en": "Mrs Hanh", "honorific": "bà", "self_ref": "con",
    "age": 72, "province": "Bến Tre", "lives_alone": True,
    "medications": [{"name": "Amlodipine 5mg", "time": "07:00"}],
    "family": [{"id": "lan", "name": "Lan", "relation": "daughter", "role": "primary"}],
    "goals": ["Ngủ đủ 6 tiếng"], "memory_facts": ["Cây mai trước nhà sắp ra nụ"],
}


def make_ctx(profile=None, recall=True, hooks=None, family_message="Lan nhắn: chủ nhật con về thăm má."):
    p = dict(profile or PROFILE)
    ev = ElderView.from_profile(p)
    r = recall_from_fact("Cây mai trước nhà sắp ra nụ", ev.honorific) if recall else None
    return DailyContext(elder=ev, profile=p, last_summaries=["Bà kể chuyện tưới cây."], followup_hooks=hooks or [],
                        recall=r, family_message=family_message, day=91)
