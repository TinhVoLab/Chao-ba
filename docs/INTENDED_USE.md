# Chào Bà: Intended Use and Not-a-Medical-Device Statement

Prototype for the Future Health Digital Innovation Challenge 2026. This page states what Chào Bà is for, what it is not for, and who decides on care. It is a design statement written by the team. It is **not** a regulatory determination: no formal classification under Vietnam's Decree 98/2021/ND-CP or any other medical-device rules has been made (see [TECHNICAL_DOCUMENTATION §11.5](TECHNICAL_DOCUMENTATION.md#115-cross-border-processing-and-vietnamese-law)).

## Intended use

Chào Bà is a **wellbeing and family-communication service** for older adults living at home and their families:

- It helps adult children stay in light daily touch with an ageing parent (photos, love cards, a short daily chat).
- It tells the family, in plain words, when the parent's speech, recall, self-reported symptoms, mood or engagement has **changed against the parent's own usual**, and suggests an ordinary next step (call more often, bring the trend to the next routine check-up, contact the health station).
- With the parent's consent, it lets a commune health station see who may need a visit and record what was done.

**Brain health.** The submission answers the challenge statement "Agentic AI lab for Protecting Brain Health Earlier". In that frame Chào Bà does two things: it supports **prevention** (daily family contact works on social isolation, a modifiable dementia risk factor at population level) and it **identifies change** in everyday cognitive and functional signals (recall, speech rate, pauses, word variety; answering the call, medication taken, daily engagement) against the person's own baseline. A change in memory or mood is not always dementia: many common causes are treatable (medicine effects, depression, thyroid problems, low vitamin B12, infection, sleep apnoea; see TECHNICAL_DOCUMENTATION §1). Chào Bà never suggests a cause. That is **risk identification, not diagnosis**:

- **Chào Bà is not a cognitive screening test**, and it is **not validated in any population yet**, Vietnamese, Emirati or other. All accuracy figures come from simulated data.
- A **yellow** light means "watch and check again": the family keeps an eye, talks more often, and the daily chat repeats the measurement over the following days. It is not a result to act on medically by itself.
- A **red** light, a rapid change or a high-risk statement goes to **qualified review** (health-station or clinical staff), who decide whether a referral to primary care, geriatrics, neurology or mental-health services is needed. The software never makes that referral decision.
- Explanations describe a change against her own usual, never a cause, and the app labels simulated data and its accuracy limits (TECHNICAL_DOCUMENTATION §10, §15).

**Intended users:** older adults (the person enrolled, who consents), their family care circle, and, only with the `clinician_sharing` consent, health-station or clinical staff.

## Not intended for

- **Diagnosis.** Chào Bà does not diagnose, screen for or rule out any disease, including dementia, depression, stroke or heart disease. A green light does not mean "healthy". A red light does not mean "ill".
- **Treatment or medication advice.** The AI companion refuses to change, stop or dose medication and says to ask a doctor or pharmacist (`chaoba/agent/guardrails.py`). Family free text is checked for diagnoses and medication advice.
- **Emergency monitoring.** Chào Bà is not an alarm system and does not watch the person continuously. If the parent mentions an emergency during a chat, the companion tells them to call **115** and raises a red alert for the family (`chaoba/agent/emergency.py`). The standing screen also has an always-visible **"Cần giúp / Help"** button: a confirmation screen counts down 10 seconds and then alerts the family unless the parent taps "Không, bấm nhầm" (pressed by mistake), and shows a **Gọi 115** button. These are best-effort safety nets, not a response service: nobody is guaranteed to be on duty, and an offline screen sends the alert only when the connection returns.
- **Replacing contact with people.** The service exists to bring family and the health station closer, not to stand in for them.

## Who decides

| Step | Who | What the software does |
|---|---|---|
| Notice a change | Software | Compares today with the person's own baseline and shows a green / yellow / red light with a plain explanation |
| Decide what to do (yellow) | Family | Suggests ordinary steps; the family chooses and records them in the care loop |
| Decide what to do (red) | Family **and** a person with a clinical role | Every red alert is marked *waiting for review* until health-station or clinical staff record an outcome: no further action, family keeps watching, station phoned, home visit, referred to a doctor, or sent to emergency care (`chaoba/server/care_review.py`). The family sees who reviewed it and the outcome |
| Check it helped | Family, with the health station | The DMAIC care loop compares before and after and re-sets the baseline (TECHNICAL_DOCUMENTATION §6) |

Only staff with the `clinician` or `health_station` role can record a review, and only while the parent's `clinician_sharing` consent is active. Each review is written to the parent's access log.

## Claims we make and do not make

| We say | We do not say |
|---|---|
| "Changed against her own usual" | "Signs of dementia", "cognitive decline detected", "dementia risk score" |
| "Risk identification; a person reviews it" | "Cognitive screening", "validated assessment" |
| "Keep an eye", "Call today", "Bring this to the next check-up" | "At risk of …", "Diagnosis", "Screening result" |
| Evaluation numbers on a **simulated** cohort, with confidence intervals | Clinical accuracy, sensitivity or specificity on real patients |

## Before any real-world use

1. Formal regulatory classification with Vietnamese counsel (Decree 98/2021/ND-CP; PDPL 91/2025/QH15 and Decree 356/2025/ND-CP). For a UAE deployment, the equivalent review under UAE rules.
2. Ethics approval and a usability pilot (10–20 families) before any validation study (TECHNICAL_DOCUMENTATION §13).
3. A written agreement with each health station on review times, referral paths and data sharing. The prototype records reviews but does not guarantee anyone is on duty.
