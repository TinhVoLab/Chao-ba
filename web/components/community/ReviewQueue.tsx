"use client";
import { useState } from "react";
import { Check, Stethoscope } from "lucide-react";
import type { Alert, ReviewOutcome, ReviewRow } from "@/lib/types";
import { API_BASE } from "@/lib/config";
import { longDate } from "@/lib/format";
import { stationHeaders } from "@/lib/viewer";
import { T } from "../T";

// Outcomes accepted by POST /api/elders/{id}/alerts/{aid}/review (care_review.py OUTCOMES), in two rows:
// follow-up close to home, then referral. A specialty referral is the reviewer's decision, never suggested by the app.
// The 2-week repeat interval is a placeholder to be set with clinical partners (TECHNICAL_DOCUMENTATION §8.5).
type Outcome = { key: ReviewOutcome; vi: string; en: string };
const OUTCOME_GROUPS: { id: string; vi: string; en: string; items: Outcome[] }[] = [
  {
    id: "follow",
    vi: "Theo dõi",
    en: "Follow-up",
    items: [
      { key: "phone_check", vi: "Đã gọi hỏi thăm", en: "Phoned to check in" },
      { key: "home_visit", vi: "Đến nhà thăm", en: "Home visit" },
      { key: "repeat_assessment", vi: "Kiểm tra lại sau 2 tuần", en: "Repeat check in 2 weeks" },
      { key: "family_follow_up", vi: "Gia đình theo dõi", en: "Family keeps watching" },
      { key: "no_action", vi: "Không cần thêm", en: "No further action" },
    ],
  },
  {
    id: "refer",
    vi: "Chuyển khám",
    en: "Referral",
    items: [
      { key: "gp_referral", vi: "Hẹn khám bác sĩ", en: "Refer to a doctor" },
      { key: "geriatrics", vi: "Lão khoa", en: "Geriatrics" },
      { key: "neurology", vi: "Thần kinh", en: "Neurology" },
      { key: "mental_health", vi: "Sức khỏe tâm thần", en: "Mental-health services" },
      { key: "emergency", vi: "Chuyển cấp cứu", en: "Emergency care" },
    ],
  },
];

/** Red alerts waiting for a person with a clinical role. The light only flags a change; the decision is human. */
export function ReviewQueue({ initial }: { initial: ReviewRow[] }) {
  const [rows, setRows] = useState(initial);
  const [open, setOpen] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const waiting = rows.filter((r) => r.needs_review).length;

  async function review(r: ReviewRow, outcome: ReviewOutcome) {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(
        `${API_BASE}/api/elders/${encodeURIComponent(r.elder_ref)}/alerts/${r.alert_id}/review`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", ...stationHeaders() },
          body: JSON.stringify({ outcome, note: note.trim() || undefined }),
        },
      );
      if (!res.ok) throw new Error(String(res.status));
      const a = (await res.json()) as Alert;
      setRows((list) => list.map((x) => (x.alert_id === r.alert_id ? { ...x, needs_review: false, review: a.review ?? null } : x)));
      setOpen(null);
      setNote("");
    } catch {
      setError("Chưa lưu được, thử lại sau. / Not saved, try again later.");
    }
    setBusy(false);
  }

  return (
    <section aria-labelledby="rv-h" className="flex flex-col gap-3" data-testid="review-queue">
      <h2 id="rv-h" className="flex items-center gap-2 text-sm font-bold uppercase tracking-wide text-ink-3">
        <Stethoscope size={16} aria-hidden />
        <T vi={`Cảnh báo đỏ cần xem xét · ${waiting}`} en={`Red alerts to review · ${waiting}`} />
      </h2>
      <p className="max-w-[65ch] text-[0.9375rem] text-ink-2">
        <T
          vi="Đèn đỏ chỉ báo một thay đổi so với mức bình thường của chính người đó, không phải chẩn đoán. Nhân viên y tế xem và ghi lại việc đã làm; gia đình thấy kết quả này trên cảnh báo."
          en="A red light only flags a change against the person's own usual, not a diagnosis. Clinical staff review it and record what was done; the family sees this on the alert."
        />
      </p>
      {rows.length === 0 && (
        <p className="rounded-2xl bg-surface-2 p-4 text-ink-2">
          <T vi="Không có cảnh báo đỏ nào gần đây." en="No recent red alerts." />
        </p>
      )}
      <ul className="flex flex-col gap-2">
        {rows.map((r) => {
          const d = longDate(r.date);
          return (
            <li key={r.alert_id} className={`rounded-2xl border p-3.5 ${r.needs_review ? "border-red-ink/40 bg-surface" : "border-line"}`}>
              <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                <span className="font-semibold">{r.label}</span>
                <span className="text-sm text-ink-3 tnum">
                  <T vi={d.vi} en={d.en} />
                </span>
              </div>
              {r.review ? (
                <p className="mt-1.5 flex items-start gap-1.5 text-[0.9375rem] text-ink-2">
                  <Check size={17} aria-hidden className="mt-0.5 shrink-0" />
                  <span>
                    <T vi={`Đã xem: ${r.review.outcome_vi}`} en={`Reviewed: ${r.review.outcome_en}`} />
                    {r.review.note && <span className="block text-ink-3">“{r.review.note}”</span>}
                  </span>
                </p>
              ) : open === r.alert_id ? (
                <div className="mt-2 flex flex-col gap-2">
                  <label className="flex flex-col gap-1 text-sm text-ink-2">
                    <T vi="Ghi chú (không bắt buộc)" en="Note (optional)" />
                    <input
                      value={note}
                      onChange={(e) => setNote(e.target.value.slice(0, 280))}
                      maxLength={280}
                      className="min-h-11 rounded-xl border border-line bg-bg px-3 text-base text-ink"
                    />
                  </label>
                  {OUTCOME_GROUPS.map((g) => (
                    <fieldset key={g.id} className="flex flex-col gap-1.5" data-testid={`outcomes-${g.id}`}>
                      <legend className="mb-1.5 text-sm font-semibold text-ink-3">
                        <T vi={g.vi} en={g.en} />
                      </legend>
                      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
                        {g.items.map((o) => (
                          <button
                            key={o.key}
                            type="button"
                            disabled={busy}
                            onClick={() => review(r, o.key)}
                            className="min-h-11 rounded-xl border border-line-strong bg-surface px-3 py-1.5 text-[0.9375rem] font-semibold leading-snug disabled:opacity-50"
                          >
                            <T vi={o.vi} en={o.en} />
                          </button>
                        ))}
                      </div>
                    </fieldset>
                  ))}
                  {error && (
                    <p role="alert" className="text-sm text-red-ink">
                      {error}
                    </p>
                  )}
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => {
                    setOpen(r.alert_id);
                    setNote("");
                    setError(null);
                  }}
                  className="mt-2 inline-flex min-h-11 items-center gap-2 rounded-xl bg-ink px-4 font-semibold text-bg"
                >
                  <Stethoscope size={18} aria-hidden />
                  <T vi="Xem xét và ghi kết quả" en="Review and record" />
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
