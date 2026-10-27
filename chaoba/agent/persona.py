"""Persona "Út Thương": a warm, Southern (miền Tây) virtual companion.

She calls the elder "bà"/"ông" (from the profile's `honorific`), refers to herself as "con", openly says she is a
virtual assistant ("trợ lý ảo"), speaks in short turns (<= 20 words, one question per turn), and never gives
medical advice, diagnoses, or medication changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

PERSONA_NAME = "Út Thương"
MAX_WORDS_PER_TURN = 20

# Southern particles and vocabulary the persona uses (also used by ScriptedEngine to sound natural).
SOUTHERN_STYLE = {
    "particles": ["nha", "nghen", "hen", "hông", "ha", "đó", "nè"],
    "vocab": {"không": "hông/hổng", "gì": "chi/gì", "vậy": "dzậy/vầy", "được": "được", "ăn cơm": "ăn cơm",
              "đi chợ": "đi chợ", "con heo": "con heo", "trái cây": "trái cây", "ly": "ly"},
}


# How Út Thương (who calls herself "con") refers to a family member, by relation, when the profile entry has no
# explicit `honorific`. The synthetic profiles in chaoba.core.synth carry no honorific, so the server fills this in
# at seed time (Service._seed_persona) and ElderView falls back to the same mapping.
RELATION_HONORIFIC = {
    "daughter": "chị", "son": "anh", "daughter_in_law": "chị", "son_in_law": "anh",
    "wife": "bà", "husband": "ông", "sister": "bà", "brother": "ông",
    "niece": "chị", "nephew": "anh", "granddaughter": "", "grandson": "", "grandchild": "",
}
HONORIFIC_WORDS = ("bà", "ông", "cô", "chú", "anh", "chị", "bác", "dì", "cậu", "mợ", "thím", "em")


def family_honorific(member: dict | None) -> str:
    """anh / chị / cô / chú / bà / ông (or "" = name only) for a family-member entry."""
    if not member:
        return ""
    if member.get("honorific") is not None:
        return str(member["honorific"]).lower()
    name = (member.get("name") or "").split()
    if len(name) > 1 and name[0].lower() in HONORIFIC_WORDS:   # "Bà Tư" already carries it
        return name[0].lower()
    return RELATION_HONORIFIC.get((member.get("relation") or "").lower(), "")


def family_ref(member: dict | None) -> str | None:
    """Mid-sentence reference to a family member: "chị Lan", "bà Tư" (never "cô Bà Tư")."""
    if not member or not member.get("name"):
        return None
    name = member["name"].strip()
    parts = name.split()
    if len(parts) > 1 and parts[0].lower() in HONORIFIC_WORDS:
        return parts[0].lower() + " " + " ".join(parts[1:])
    h = family_honorific(member)
    return f"{h} {name}".strip()


def with_family_honorifics(profile: dict) -> dict:
    """Copy of the profile whose family entries all carry an explicit `honorific`."""
    p = dict(profile)
    p["family"] = [dict(f, honorific=family_honorific(f)) for f in (profile.get("family") or [])]
    return p


@dataclass
class ElderView:
    """The bits of the profile the agent needs, with safe defaults."""
    id: str
    display_name: str = "Bà"
    honorific: str = "bà"
    self_ref: str = "con"
    short_name: str = ""
    family_primary: str | None = None
    family_relation: str | None = None
    family_ref: str | None = None          # "chị Lan", "bà Tư": how the agent names the primary family member
    medications: list[dict] = field(default_factory=list)
    province: str = ""

    @classmethod
    def from_profile(cls, p: dict) -> "ElderView":
        fam = p.get("family") or []
        primary = next((f for f in fam if f.get("role") == "primary"), fam[0] if fam else None)
        display = p.get("display_name") or "Bà"
        honor = (p.get("honorific") or "bà").lower()
        parts = display.split()
        short = parts[-1] if len(parts) > 1 else display
        return cls(
            id=p.get("id", "?"), display_name=display, honorific=honor, self_ref=p.get("self_ref") or "con",
            short_name=short, family_primary=primary.get("name") if primary else None,
            family_relation=primary.get("relation") if primary else None,
            family_ref=family_ref(primary),
            medications=list(p.get("medications") or []), province=p.get("province") or "",
        )

    @property
    def H(self) -> str:
        return self.honorific.capitalize()

    @property
    def address(self) -> str:
        """e.g. "bà Hạnh"."""
        return f"{self.honorific} {self.short_name}".strip()


def family_child_term(relation: str | None, honorific: str) -> str:
    """How the family member refers to the elder in a recorded greeting ("Má ơi", "Ba ơi")."""
    if relation in ("daughter", "son", "child"):
        return "Má" if honorific == "bà" else "Ba"
    if relation in ("granddaughter", "grandson", "grandchild"):
        return "Nội" if honorific == "bà" else "Ông nội"
    return honorific.capitalize()
