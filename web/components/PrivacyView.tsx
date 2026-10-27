"use client";
import { useRef, useState } from "react";
import { Cpu, Eye, FileText, MicOff, ShieldCheck, ShieldOff, ChartLine, Undo2 } from "lucide-react";
import type { FamilyMember, Privacy, RawAccess, RawConsent } from "@/lib/types";
import { longDate, shortDate, vnTime } from "@/lib/format";
import { API_BASE } from "@/lib/config";
import { T } from "./T";

const STATUS: Record<string, { vi: string; en: string; cls: string }> = {
  active: { vi: "Đang bật", en: "On", cls: "bg-green-tint text-green-ink" },
  declined: { vi: "Đã từ chối", en: "Declined", cls: "bg-surface-2 text-ink-2" },
  not_requested: { vi: "Chưa hỏi", en: "Not asked", cls: "bg-surface-2 text-ink-2" },
  withdrawn: { vi: "Đã rút", en: "Withdrawn", cls: "bg-red-tint text-red-ink" },
};

const ROLE: Record<string, { vi: string; en: string }> = {
  family: { vi: "gia đình", en: "family" },
  primary: { vi: "người chăm chính", en: "primary carer" },
  secondary: { vi: "gia đình", en: "family" },
  clinician: { vi: "bác sĩ", en: "clinician" },
  system: { vi: "tự động", en: "automatic" },
};

const ACTION: Record<string, { vi: string; en: string }> = {
  read_today: { vi: "Xem đèn hôm nay", en: "Viewed today's light" },
  read_profile: { vi: "Xem hồ sơ", en: "Viewed profile" },
  read_timeline: { vi: "Xem xu hướng", en: "Viewed trends" },
  read_alerts: { vi: "Xem cảnh báo", en: "Viewed alerts" },
  read_dmaic: { vi: "Xem chu trình chăm sóc", en: "Viewed care cycle" },
  read_notes: { vi: "Xem ghi chú", en: "Viewed notes" },
  read_privacy: { vi: "Xem quyền riêng tư", en: "Viewed privacy" },
  write_note: { vi: "Viết ghi chú", en: "Wrote a note" },
  add_note: { vi: "Viết ghi chú", en: "Wrote a note" },
  ack_alert: { vi: "Đánh dấu đã xem cảnh báo", en: "Acknowledged an alert" },
  resume: { vi: "Bật lại cuộc gọi", en: "Resumed calls" },
  purge_transcripts: { vi: "Tự xoá lời nói quá hạn", en: "Auto-deleted expired transcripts" },
};

const RETENTION_TEXT: Record<string, { vi: string; en: string }> = {
  "derived numbers kept while enrolled": { vi: "Chỉ giữ các con số đo được, trong thời gian tham gia", en: "Only derived numbers are kept, while enrolled" },
  "on-device rules (no LLM)": { vi: "Phân tích bằng quy tắc cục bộ, không dùng mô hình AI bên ngoài", en: "Analysed with local rules, no external AI model" },
};

function consentView(c: RawConsent, elderVi: string, elderEn: string) {
  const id = String(c.type ?? c.kind ?? c.id ?? "consent");
  const status = c.status ?? (c.granted === true ? "active" : c.granted === false ? "declined" : "not_requested");
  const by = c.by ?? c.granted_by;
  const self = by === "self";
  const witness = c.witness === "family";
  return {
    id,
    labelVi: c.scope_vi ?? c.label_vi ?? id,
    labelEn: c.scope_en ?? c.label_en ?? id,
    status,
    byVi: self ? `${elderVi} tự đồng ý${witness ? ", có gia đình chứng kiến" : ""}` : by ?? "",
    byEn: self ? `${elderEn}, in person${witness ? ", family witnessed" : ""}` : by ?? "",
    date: c.date ?? c.granted_at ?? c.ts ?? null,
  };
}

function accessView(a: RawAccess, family: FamilyMember[]) {
  const actor = a.actor ?? a.who ?? "";
  const [kind, role] = actor.includes(":") ? actor.split(":") : [a.role ?? "", ""];
  const member = kind === "family" ? family.find((f) => f.role === role) : undefined;
  const who = member?.name ?? (kind === "family" ? "Gia đình / Family" : kind === "system" ? "Hệ thống / System" : actor);
  const roleLabel = ROLE[member ? role : kind] ?? (a.role ? ROLE[a.role] : undefined);
  const act = ACTION[a.action] ?? { vi: String(a.action_vi ?? a.action), en: String(a.action_en ?? a.action) };
  return { who, roleLabel, act, at: a.ts ?? a.at ?? "" };
}

export function PrivacyView({
  privacy,
  elderId,
  elderVi,
  elderEn,
  family,
  live,
}: {
  privacy: Privacy;
  elderId: string;
  elderVi: string;
  elderEn: string;
  family: FamilyMember[];
  live: boolean;
}) {
  const [withdrawn, setWithdrawn] = useState(false);
  const [paused, setPaused] = useState(privacy.scheduling_active === false);
  const [resuming, setResuming] = useState(false);
  async function resume() {
    setResuming(true);
    try {
      const res = await fetch(`${API_BASE}/api/elders/${encodeURIComponent(elderId)}/resume`, { method: "POST", signal: AbortSignal.timeout(4000) });
      if (res.ok) setPaused(false);
    } catch {}
    setResuming(false);
  }
  const dlg = useRef<HTMLDialogElement>(null);
  const r = privacy.data_retention ?? { audio: "not stored", transcript_days: 7 };
  const noAudio = /not/i.test(String(r.audio));
  const extras = Object.entries(r).filter(([k, v]) => !["audio", "transcript_days"].includes(k) && typeof v === "string") as [string, string][];
  // Collapse repeated reads (same person, same action, same day) into one row with a count.
  const log = (() => {
    const rows = [...(privacy.access_log ?? [])].map((a) => accessView(a, family)).sort((a, b) => b.at.localeCompare(a.at));
    const out: (ReturnType<typeof accessView> & { count: number })[] = [];
    const seen = new Map<string, number>();
    for (const r of rows) {
      const k = `${r.who}|${r.act.en}|${r.at.slice(0, 10)}`;
      const i = seen.get(k);
      if (i != null) out[i].count++;
      else {
        seen.set(k, out.length);
        out.push({ ...r, count: 1 });
      }
    }
    return out;
  })();
  const totalReads = privacy.access_log?.length ?? 0;

  return (
    <div className="flex flex-col gap-8">
      {paused && (
        <div className="flex flex-col gap-3 rounded-2xl bg-yellow-tint p-5 text-yellow-ink" role="status">
          <p className="text-lg font-bold">
            <T vi={`${elderVi} đã xin tạm dừng cuộc gọi hằng ngày.`} en={`${elderEn} asked to pause the daily calls.`} />
          </p>
          <p className="text-sm">
            <T vi="Chỉ bật lại khi chính người thân đồng ý." en="Only turn back on with your parent's agreement." />
          </p>
          {live && (
            <button type="button" onClick={resume} disabled={resuming} className="inline-flex min-h-11 w-fit items-center gap-2 rounded-xl border-2 border-current px-4 font-semibold disabled:opacity-50">
              <Undo2 size={18} aria-hidden />
              <T vi="Bật lại cuộc gọi" en="Resume calls" />
            </button>
          )}
        </div>
      )}

      {withdrawn && (
        <div className="fade-in flex flex-col gap-3 rounded-2xl bg-red-tint p-5 text-red-ink" role="status">
          <p className="flex items-start gap-2 text-lg font-bold">
            <ShieldOff size={22} className="mt-0.5 shrink-0" aria-hidden />
            <T vi={`Đã rút đồng ý cho ${elderVi}. Út Thương sẽ không gọi và không đo nữa.`} en={`Consent withdrawn for ${elderEn}. Út Thương will stop calling and measuring.`} />
          </p>
          <p className="text-sm">
            <T vi="Bản demo: chỉ đổi trạng thái hiển thị, không xoá dữ liệu nào." en="Demo: only the displayed state changes; no data is deleted." />
          </p>
          <button
            type="button"
            onClick={() => setWithdrawn(false)}
            className="inline-flex min-h-11 w-fit items-center gap-2 rounded-xl border-2 border-current px-4 font-semibold"
          >
            <Undo2 size={18} aria-hidden />
            <T vi="Bật lại" en="Turn back on" />
          </button>
        </div>
      )}

      {/* Retention: the promise, said plainly */}
      <section aria-labelledby="ret-h" className="flex flex-col gap-3">
        <h2 id="ret-h" className="text-sm font-bold uppercase tracking-wide text-ink-3">
          <T vi="Dữ liệu được giữ thế nào" en="How data is kept" />
        </h2>
        <ul className="flex flex-col gap-3">
          <li className="flex items-start gap-3">
            <span className="grid size-11 shrink-0 place-items-center rounded-full bg-accent text-accent-ink">
              <MicOff size={22} aria-hidden />
            </span>
            <p>
              <strong className="block text-lg">
                {noAudio ? <T vi="Không lưu ghi âm" en="No recordings kept" /> : <T vi={`Ghi âm: ${r.audio}`} en={`Audio: ${r.audio}`} />}
              </strong>
              <span className="text-ink-2">
                <T vi="Giọng nói chỉ được chuyển thành chữ và số đo ngay trong cuộc gọi, rồi bỏ đi." en="Speech becomes text and measurements during the call, then the audio is discarded." />
              </span>
            </p>
          </li>
          <li className="flex items-start gap-3">
            <span className="grid size-11 shrink-0 place-items-center rounded-full bg-surface-2 text-ink">
              <FileText size={20} aria-hidden />
            </span>
            <p>
              <strong className="block text-lg">
                <T vi={`Lời nói (dạng chữ) tự xoá sau ${r.transcript_days} ngày`} en={`Transcripts auto-delete after ${r.transcript_days} days`} />
              </strong>
              <span className="text-ink-2">
                <T
                  vi="Gia đình thấy bản tóm tắt; chỉ cảnh báo triệu chứng hoặc khẩn cấp mới kèm vài câu trích ngắn nguyên văn."
                  en="Family sees summaries; only symptom or emergency alerts include short verbatim quotes."
                />
              </span>
            </p>
          </li>
          {extras.map(([k, v]) => {
            const txt = RETENTION_TEXT[v] ?? { vi: v, en: v };
            return (
              <li key={k} className="flex items-start gap-3">
                <span className="grid size-11 shrink-0 place-items-center rounded-full bg-surface-2 text-ink">
                  {k.includes("llm") ? <Cpu size={20} aria-hidden /> : <ChartLine size={20} aria-hidden />}
                </span>
                <p className="pt-2.5 text-lg font-semibold">
                  <T vi={txt.vi} en={txt.en} />
                </p>
              </li>
            );
          })}
        </ul>
      </section>

      {/* Consents */}
      <section aria-labelledby="con-h" className="flex flex-col gap-2">
        <h2 id="con-h" className="text-sm font-bold uppercase tracking-wide text-ink-3">
          <T vi="Đồng ý" en="Consents" />
        </h2>
        <ul className="divide-y divide-line rounded-2xl border border-line bg-surface">
          {(privacy.consents ?? []).map((raw) => {
            const c = consentView(raw, elderVi, elderEn);
            const st = STATUS[withdrawn && c.status === "active" ? "withdrawn" : c.status] ?? { vi: c.status, en: c.status, cls: "bg-surface-2 text-ink-2" };
            const when = c.date ? longDate(c.date.slice(0, 10)) : null;
            return (
              <li key={c.id} className="flex items-start justify-between gap-3 px-4 py-3">
                <div className="min-w-0">
                  <p className="font-semibold">
                    <T vi={c.labelVi} en={c.labelEn} />
                  </p>
                  <p className="text-sm text-ink-3">
                    <T vi={c.byVi} en={c.byEn} />
                    {when && (
                      <>
                        {" · "}
                        <T vi={when.vi} en={when.en} />
                      </>
                    )}
                  </p>
                </div>
                <span className={`shrink-0 rounded-full px-2.5 py-0.5 text-sm font-semibold ${st.cls}`}>
                  <T vi={st.vi} en={st.en} />
                </span>
              </li>
            );
          })}
        </ul>
        {!withdrawn && (
          <button
            type="button"
            onClick={() => dlg.current?.showModal()}
            className="mt-2 inline-flex min-h-12 w-fit items-center gap-2 rounded-xl border-2 border-red px-4 font-semibold text-red-ink transition-colors duration-150 hover:bg-red-tint"
          >
            <ShieldOff size={18} aria-hidden />
            <T vi="Rút lại đồng ý" en="Withdraw consent" />
          </button>
        )}
      </section>

      {/* Access log */}
      <section aria-labelledby="log-h" className="flex flex-col gap-2">
        <h2 id="log-h" className="flex items-center gap-2 text-sm font-bold uppercase tracking-wide text-ink-3">
          <Eye size={16} aria-hidden />
          <T vi="Ai đã xem" en="Who viewed" />
          {totalReads > 0 && <span className="font-medium normal-case tracking-normal">· <T vi={`${totalReads} lượt truy cập`} en={`${totalReads} accesses`} /></span>}
        </h2>
        {log.length === 0 && (
          <p className="text-ink-2">
            <T vi="Chưa ai xem dữ liệu." en="No one has viewed the data yet." />
          </p>
        )}
        <ol className="flex flex-col">
          {log.slice(0, 12).map((a, i) => {
            return (
              <li key={`${a.at}-${i}`} className="grid grid-cols-[4rem_1fr] gap-3 border-t border-line py-2.5 first:border-t-0">
                <span className="text-sm text-ink-3 tnum">
                  {shortDate(a.at.slice(0, 10))}
                  <span className="block">{vnTime(a.at)}</span>
                </span>
                <p>
                  <span className="font-semibold">{a.who}</span>
                  {a.roleLabel && (
                    <span className="text-ink-3">
                      {" "}
                      (<T vi={a.roleLabel.vi} en={a.roleLabel.en} />)
                    </span>
                  )}
                  <span className="block text-ink-2">
                    <T vi={a.act.vi} en={a.act.en} />
                    {a.count > 1 && <span className="text-ink-3 tnum"> · {a.count}×</span>}
                  </span>
                </p>
              </li>
            );
          })}
        </ol>
      </section>

      <dialog
        ref={dlg}
        aria-labelledby="wd-title"
        className="m-auto w-[min(92vw,26rem)] rounded-3xl border border-line bg-surface p-0 text-ink shadow-soft"
      >
        <form method="dialog" className="flex flex-col gap-4 p-6">
          <ShieldCheck size={28} className="text-red-ink" aria-hidden />
          <h2 id="wd-title" className="text-xl font-bold">
            <T vi={`Rút đồng ý cho ${elderVi}?`} en={`Withdraw consent for ${elderEn}?`} />
          </h2>
          <p className="text-ink-2">
            <T
              vi="Út Thương sẽ ngừng gọi mỗi sáng và ngừng đo. Gia đình sẽ không còn thấy đèn hằng ngày. Có thể bật lại bất cứ lúc nào."
              en="Út Thương will stop the morning calls and stop measuring. The family will no longer see a daily light. You can turn it back on any time."
            />
          </p>
          <p className="rounded-xl bg-surface-2 px-3 py-2 text-sm text-ink-2">
            <T vi="Bản demo: không xoá dữ liệu nào." en="Demo: nothing is deleted." />
          </p>
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button value="cancel" className="min-h-12 rounded-xl border border-line-strong px-4 font-semibold">
              <T vi="Giữ nguyên" en="Keep as is" />
            </button>
            <button
              value="confirm"
              onClick={() => setWithdrawn(true)}
              className="min-h-12 rounded-xl bg-red px-4 font-bold text-on-red"
            >
              <T vi="Rút đồng ý" en="Withdraw" />
            </button>
          </div>
        </form>
      </dialog>
    </div>
  );
}
