// Server-rendered parts of the Family page: weekly synthesis, viewer notice, "who has been looking".
import { Bot, Eye, Lock, Puzzle, UserRound } from "lucide-react";
import type { FamilyOverview, Synthesis } from "@/lib/types";
import { shortDate, vnTime } from "@/lib/format";
import { T } from "../T";

export function SectionTitle({ id, icon, vi, en, aside }: { id: string; icon: React.ReactNode; vi: string; en: string; aside?: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <h2 id={id} className="flex items-center gap-2 text-sm font-bold uppercase tracking-wide text-ink-3">
        {icon}
        <T vi={vi} en={en} />
      </h2>
      {aside}
    </div>
  );
}

/** "AI ghép mảnh rời rạc": the same complaint heard by several people this week.
 *  `action`: the “Mình hỏi rồi” control of the matching suggestion (folded in here so the topic is not listed twice). */
export function SynthesisCard({ s, kinVi, kinEn, action }: { s: Synthesis; kinVi: string; kinEn: string; action?: React.ReactNode }) {
  const range = `${shortDate(s.from_date)}–${shortDate(s.to_date)}`;
  return (
    <section aria-labelledby="syn-h" className="flex flex-col gap-3">
      <SectionTitle id="syn-h" icon={<Puzzle size={16} aria-hidden />} vi={`Ghép mảnh tuần này · ${range}`} en={`This week, pieced together · ${range}`} />
      <div className="rounded-[24px] bg-accent-tint p-5">
        <p className="text-[1.125rem] font-semibold leading-snug text-ink">
          <T vi={s.summary_vi} en={s.summary_en} />
        </p>
        {action}
        {s.items.length > 0 && (
          <ul className="mt-4 flex flex-col gap-3">
            {s.items.map((it) => (
              <li key={it.topic} className="rounded-2xl bg-surface p-3.5">
                <p className="font-semibold">
                  <T vi={`${it.label_vi[0].toUpperCase()}${it.label_vi.slice(1)}`} en={`${it.label_en[0].toUpperCase()}${it.label_en.slice(1)}`} />
                  <span className="ml-2 rounded-full bg-surface-2 px-2 py-px text-sm font-semibold text-ink-2 tnum">
                    <T vi={`${it.count} lần`} en={it.count === 1 ? "once" : `${it.count} times`} />
                  </span>
                </p>
                <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Nghe từ / Heard by">
                  {it.mentions.map((m, i) => (
                    <li
                      key={`${m.who}-${m.day}-${i}`}
                      className={`inline-flex min-h-8 items-center gap-1.5 rounded-full border px-2.5 text-sm ${
                        m.source === "ai" ? "border-accent/40 text-accent" : "border-line-strong text-ink-2"
                      }`}
                    >
                      {m.source === "ai" ? <Bot size={14} aria-hidden /> : <UserRound size={14} aria-hidden />}
                      <span className="font-semibold">{m.source === "ai" ? "Út Thương" : m.who}</span>
                      <span className="tnum opacity-80">{shortDate(m.date)}</span>
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-4 text-sm text-ink-2">
          <T vi={s.contact_vi} en={s.contact_en} />
        </p>
        <p className="mt-2 text-xs text-ink-3">
          {s.engine === "claude" ? (
            <T
              vi="Câu chữ do Claude viết lại từ bản quy tắc, đã kiểm tra không thêm số liệu hay chẩn đoán."
              en="Wording rewritten by Claude from the rule-based text, checked for no new numbers or diagnoses."
            />
          ) : (
            <T
              vi={`Ghép tự động từ ghi chú của cả nhà và các cuộc gọi của Út Thương (theo quy tắc, không chẩn đoán). Nếu lo cho ${kinVi}, hãy hỏi bác sĩ.`}
              en={`Pieced together automatically from family notes and Út Thương's calls (rule-based, not a diagnosis). If you are worried about ${kinEn}, ask a doctor.`}
            />
          )}
          {s.sharing_paused && (
            <>
              {" "}
              <T vi="Chia sẻ đang tạm dừng: chỉ dùng ghi chú gia đình." en="Sharing is paused: family notes only." />
            </>
          )}
        </p>
      </div>
    </section>
  );
}

/** Shown to viewers: what they can and cannot see, and who can. */
export function ViewerNotice({ o }: { o: FamilyOverview }) {
  if (o.viewer.permissions.full_view) return null;
  const primary = o.members.find((m) => m.role === "primary")?.name ?? "";
  return (
    <p className="flex items-start gap-3 rounded-2xl border border-line bg-surface px-4 py-3 text-[0.9375rem] text-ink-2">
      <Eye size={18} className="mt-0.5 shrink-0" aria-hidden />
      <span>
        <T
          vi={`Bạn đang xem bản tóm tắt. Ghi chú chi tiết của người khác và lời kể nguyên văn chỉ ${primary} (người chăm sóc chính) xem được. Bạn vẫn ghi chú, nhận việc và đánh dấu đã hỏi được.`}
          en={`You are seeing the summary view. Other people's notes and verbatim quotes are visible to ${primary} (primary carer) only. You can still add notes, take tasks and mark topics as asked.`}
        />
      </span>
    </p>
  );
}

const ROLE_LABEL: Record<string, { vi: string; en: string }> = {
  primary: { vi: "người chăm sóc chính", en: "primary carer" },
  viewer: { vi: "người nhà (tóm tắt)", en: "family (summary)" },
  elder_self: { vi: "chính người cao tuổi", en: "the elder" },
  health_station: { vi: "trạm y tế", en: "health station" },
  clinician: { vi: "nhân viên y tế", en: "clinician" },
};

/** The elder can see who has been looking (per-person summary of the access log; on the Privacy page). */
export function AccessCard({ access, kinVi, kinEn }: { access: FamilyOverview["access"]; kinVi: string; kinEn: string }) {
  const people = access.people.slice(0, 6);
  return (
    <section aria-labelledby="acc-h" className="flex flex-col gap-3">
      <SectionTitle id="acc-h" icon={<Lock size={16} aria-hidden />} vi={`Ai đã xem thông tin của ${kinVi} (${access.days} ngày)`} en={`Who looked at ${kinEn}'s information (${access.days} days)`} />
      {people.length === 0 ? (
        <p className="text-ink-2">
          <T vi="Chưa có ai xem." en="Nobody yet." />
        </p>
      ) : (
        <ul className="divide-y divide-line rounded-2xl border border-line bg-surface">
          {people.map((p) => {
            const r = ROLE_LABEL[p.role] ?? { vi: p.role, en: p.role };
            return (
              <li key={p.actor} className="flex items-center justify-between gap-3 px-4 py-2.5">
                <span className="min-w-0">
                  <span className="block truncate font-semibold">
                    <T vi={p.label_vi ?? p.actor} en={p.label_en ?? p.label_vi ?? p.actor} />
                  </span>
                  <span className="block text-sm text-ink-3">
                    <T vi={r.vi} en={r.en} />
                  </span>
                </span>
                <span className="shrink-0 text-right text-sm text-ink-2 tnum">
                  <T vi={`${p.views} lần xem`} en={`${p.views} view${p.views === 1 ? "" : "s"}`} />
                  {p.writes > 0 && (
                    <>
                      {" · "}
                      <T vi={`${p.writes} lần ghi`} en={`${p.writes} edit${p.writes === 1 ? "" : "s"}`} />
                    </>
                  )}
                  <span className="block text-ink-3">
                    {shortDate(p.last_ts)} {vnTime(p.last_ts)}
                  </span>
                </span>
              </li>
            );
          })}
        </ul>
      )}
      <p className="text-sm text-ink-3">
        <T
          vi={`${kinVi[0].toUpperCase()}${kinVi.slice(1)} cũng thấy danh sách này. Từng lượt xem ở mục “Ai đã xem” phía trên.`}
          en={`${kinEn} sees this list too. Each view is listed under “Who viewed” above.`}
        />
      </p>
    </section>
  );
}
