# Chào Bà: Intended Use and Not-a-Medical-Device Statement

Prototype for the Future Health Digital Innovation Challenge 2026. This page states what Chào Bà is for, what it is not for, and who decides on care. It is a design statement written by the team. It is **not** a regulatory determination: no formal classification under Vietnam's Decree 98/2021/ND-CP or any other medical-device rules has been made (see [TECHNICAL_DOCUMENTATION §11.5](TECHNICAL_DOCUMENTATION.md#115-cross-border-processing-and-vietnamese-law)).

## Intended use

Chào Bà is a **wellbeing and family-communication service** for older adults living at home and their families:

- It helps adult children stay in light daily touch with an ageing parent (photos, love cards, a short daily chat).
- It tells the family, in plain words, when the parent's speech, recall, self-reported symptoms, mood or engagement has **changed against the parent's own usual**, and suggests an ordinary next step (call more often, bring the trend to the next routine check-up, contact the health station).
- With the parent's consent, it lets a commune health station see who may need a visit and record what was done.

**Intended users:** older adults (the person enrolled, who consents), their family care circle, and, only with the `clinician_sharing` consent, health-station or clinical staff.

## Not intended for

- **Diagnosis.** Chào Bà does not diagnose, screen for or rule out any disease, including dementia, depression, stroke or heart disease. A green light does not mean "healthy". A red light does not mean "ill".
- **Treatment or medication advice.** The AI companion refuses to change, stop or dose medication and says to ask a doctor or pharmacist (`chaoba/agent/guardrails.py`). Family free text is checked for diagnoses and medication advice.
- **Emergency monitoring.** Chào Bà is not an alarm system and does not watch the person continuously. If the parent mentions an emergency during a chat, the companion tells them to call **115** and raises a red alert for the family (`chaoba/agent/emergency.py`). That is a best-effort safety net, not a response service.
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
| "Changed against her own usual" | "Signs of dementia", "cognitive decline detected" |
| "Keep an eye", "Call today", "Bring this to the next check-up" | "At risk of …", "Diagnosis", "Screening result" |
| Evaluation numbers on a **simulated** cohort, with confidence intervals | Clinical accuracy, sensitivity or specificity on real patients |

## Before any real-world use

1. Formal regulatory classification with Vietnamese counsel (Decree 98/2021/ND-CP; PDPL 91/2025/QH15 and Decree 356/2025/ND-CP). For a UAE deployment, the equivalent review under UAE rules.
2. Ethics approval and a usability pilot (10–20 families) before any validation study (TECHNICAL_DOCUMENTATION §13).
3. A written agreement with each health station on review times, referral paths and data sharing. The prototype records reviews but does not guarantee anyone is on duty.
