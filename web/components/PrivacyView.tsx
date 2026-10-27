"use client";
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Cpu, Eye, FileText, MicOff, ShieldCheck, ShieldOff, ChartLine, Undo2 } from "lucide-react";
import type { FamilyMember, Privacy, RawAccess, RawConsent } from "@/lib/types";
import { longDate, shortDate, vnTime } from "@/lib/format";
import { API_BASE } from "@/lib/config";
import { actorHeaders } from "@/lib/viewer";
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
  resume_calls: { vi: "Bật lại cuộc gọi", en: "Resumed calls" },
  read_contacts: { vi: "Xem nhật ký gọi thăm", en: "Viewed contact log" },
  log_contact: { vi: "Ghi một cuộc gọi cho người thân", en: "Logged a call" },
  withdraw_consent: { vi: "Rút lại một đồng ý", en: "Withdrew a consent" },
  grant_consent: { vi: "Bật lại một đồng ý", en: "Re-enabled a consent" },
  purge_transcripts: { vi: "Tự xoá lời nói quá hạn", en: "Auto-deleted expired transcripts" },
};

const RETENTION_TEXT: Record<string, { vi: string; en: string }> = {
  "derived numbers kept while enrolled": { vi: "Chỉ giữ các con số đo được, trong thời gian tham gia", en: "Only derived numbers are kept, while enrolled" },
  "on-device rules (no LLM)": { vi: "Phân tích bằng quy tắc cục bộ, không dùng mô hình AI bên ngoài", en: "Analysed with local rules, no external AI model" },
  "server-side rules (no LLM)": { vi: "Phân tích bằng quy tắc trên máy chủ, không dùng mô hình AI bên ngoài", en: "Analysed with server-side rules, no external AI model" },
  claude: { vi: "Lời nói (dạng chữ) được gửi tới Claude (Anthropic) để trò chuyện và tóm tắt", en: "Transcript text is sent to Claude (Anthropic) for conversation and summaries" },
};

/** What stops when a purpose is withdrawn (shown in the confirm dialog). */
const WITHDRAW_EFFECT: Record<string, { vi: string; en: string }> = {
  daily_call: {
    vi: "Út Thương sẽ ngừng gọi mỗi sáng, nên cũng không có đèn mới mỗi ngày.",
    en: "Út Thương will stop the morning calls, so there will be no new daily light.",
  },
  voice_metrics: {
    vi: "Út Thương vẫn gọi hỏi thăm, nhưng không đo nhịp nói, khoảng ngừng, từ đệm nữa.",
    en: "Út Thương still calls, but stops measuring speaking pace, pauses and filler words.",
  },
  family_sharing: {
    vi: "Gia đình sẽ không còn thấy đèn, tóm tắt, xu hướng và cảnh báo trong ứng dụng này.",
    en: "The family will no longer see the light, summaries, trends or alerts in this app.",
  },
  clinician_sharing: {
    vi: "Không gửi báo cáo xu hướng cho bác sĩ nữa.",
    en: "Trend reports will no longer be shared with a clinician.",
  },
};

function consentView(c: RawConsent, elderVi: string, elderEn: string) {
  const id = String(c.type ?? c.kind ?? c.id ?? "consent");
  const status = String(c.status ?? (c.granted === true ? "active" : c.granted === false ? "declined" : "not_requested"));
  const by = c.by ?? c.granted_by;
  const self = by === "self";
  const witness = c.witness === "family";
  return {
    id,
    labelVi: c.scope_vi ?? c.label_vi ?? id,
    labelEn: c.scope_en ?? c.label_en ?? id,
    status,
    byVi: self
      ? `${elderVi} ${status === "declined" ? "tự chọn không đồng ý" : "tự đồng ý"}${witness ? ", có gia đình chứng kiến" : ""}`
      : by ?? "",
    byEn: self
      ? `${status === "declined" ? `${elderEn} chose not to` : `${elderEn}, in person`}${witness ? ", family witnessed" : ""}`
      : by ?? "",
    date: (c.changed_at as string | undefined) ?? c.date ?? c.granted_at ?? c.ts ?? null,
    changedBy: (c.changed_by as string | undefined) ?? null,
  };
}

function accessView(a: RawAccess, family: FamilyMember[]) {
  const actor = a.actor ?? a.who ?? "";
  const [kind, role] = actor.includes(":") ? actor.split(":") : [a.role ?? "", ""];
  const member = kind === "family" ? family.find((f) => f.role === role) : undefined;
  const who = member?.name ?? (kind === "family" ? "Gia đình / Family" : kind === "system" ? "Hệ thống / System" : actor);
  const roleLabel = ROLE[member ? role : kind] ?? (a.role ? ROLE[a.role] : undefined);
  const act = ACTION[a.action] ?? { vi: String(a.action_vi ?? a.action), en: String(a.action_en ?? a.action) };
  return { who, roleLabel, act, at: a.last_ts ?? a.ts ?? a.at ?? "", n: typeof a.count === "number" ? a.count : 1 };
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
  const router = useRouter();
  const [paused, setPaused] = useState(privacy.scheduling_active === false);
  const [override, setOverride] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [target, setTarget] = useState<{ id: string; labelVi: string; labelEn: string } | null>(null);
  const [error, setError] = useState(false);
  const dlg = useRef<HTMLDialogElement>(null);

  /** Withdraw or re-enable one purpose. daily_call re-enable goes through /resume (same as after an in-call opt-out). */
  async function change(kind: string, on: boolean) {
    setBusy(kind);
    setError(false);
    let ok = !live; // offline demo: change the displayed state only
    if (live) {
      const base = `${API_BASE}/api/elders/${encodeURIComponent(elderId)}`;
      const url = on ? (kind === "daily_call" ? `${base}/resume` : `${base}/consents/${kind}/grant`) : `${base}/consents/${kind}/withdraw`;
      try {
        const res = await fetch(url, { method: "POST", headers: actorHeaders(elderId), signal: AbortSignal.timeout(4000) });
        ok = res.ok;
      } catch {
        ok = false;
      }
    }
    if (ok) {
      setOverride((o) => ({ ...o, [kind]: on ? "active" : "withdrawn" }));
      if (kind === "daily_call") setPaused(!on);
      if (live) router.refresh();
    } else setError(true);
    setBusy(null);
  }
  const r = privacy.data_retention ?? { audio: "not stored", transcript_days: 7 };
  const noAudio = /not/i.test(String(r.audio));
  const extras = Object.entries(r).filter(([k, v]) => !["audio", "transcript_days"].includes(k) && typeof v === "string") as [string, string][];
  // Collapse repeated reads (same person, same action, same day) into one row with a count.
  const log = (() => {
    const rows = [...(privacy.access_log ?? [])].map((a) => accessView(a, family)).sort((a, b) => b.at.localeCompare(a.at));
    // The API already collapses reads per actor/action/resource/day (with a count); merge across resources here.
    const out: (ReturnType<typeof accessView> & { count: number })[] = [];
    const seen = new Map<string, number>();
    for (const r of rows) {
      const k = `${r.who}|${r.act.en}|${r.at.slice(0, 10)}`;
      const i = seen.get(k);
      if (i != null) out[i].count += r.n;
      else {
        seen.set(k, out.length);
        out.push({ ...r, count: r.n });
      }
    }
    return out;
  })();
  const totalReads = (privacy.access_log ?? []).reduce((n, a) => n + (typeof a.count === "number" ? a.count : 1), 0);

  return (
    <div className="flex flex-col gap-8">
      {paused && (
        <div className="flex flex-col gap-3 rounded-2xl bg-yellow-tint p-5 text-yellow-ink" role="status">
          <p className="flex items-start gap-2 text-lg font-bold">
            <ShieldOff size={22} className="mt-0.5 shrink-0" aria-hidden />
            <T vi={`Cuộc gọi hằng ngày cho ${elderVi} đang tạm dừng.`} en={`Daily calls for ${elderEn} are paused.`} />
          </p>
          <p className="text-sm">
            <T
              vi="Út Thương không gọi và không đo cho tới khi bật lại. Dữ liệu cũ vẫn giữ nguyên. Chỉ bật lại khi chính người thân đồng ý."
              en="Út Thương won't call or measure until this is turned back on. Existing data is kept. Only turn back on with your parent's agreement."
            />
          </p>
          <button
            type="button"
            onClick={() => change("daily_call", true)}
            disabled={busy === "daily_call"}
            className="inline-flex min-h-11 w-fit items-center gap-2 rounded-xl border-2 border-current px-4 font-semibold disabled:opacity-50"
          >
            <Undo2 size={18} aria-hidden />
            <T vi="Bật lại cuộc gọi" en="Resume calls" />
          </button>
        </div>
      )}
      {error && (
        <p className="rounded-xl bg-red-tint px-4 py-3 text-red-ink" role="alert">
          <T vi="Chưa đổi được. Kiểm tra máy chủ rồi thử lại." en="Couldn't change that. Check the server and try again." />
        </p>
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
            const cur = override[c.id] ?? c.status;
            const st = STATUS[cur] ?? { vi: cur, en: cur, cls: "bg-surface-2 text-ink-2" };
            const when = c.date ? longDate(c.date.slice(0, 10)) : null;
            const canToggle = c.id in WITHDRAW_EFFECT && (cur === "active" || cur === "withdrawn");
            return (
              <li key={c.id} className="flex flex-col gap-2 px-4 py-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="font-semibold">
                      <T vi={c.labelVi} en={c.labelEn} />
                    </p>
                    <p className="text-sm text-ink-3">
                      {c.changedBy ? (
                        <T vi={`${cur === "active" ? "Bật lại" : "Rút lại"} bởi ${c.changedBy}`} en={`${cur === "active" ? "Re-enabled" : "Withdrawn"} by ${c.changedBy}`} />
                      ) : (
                        <T vi={c.byVi} en={c.byEn} />
                      )}
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
                </div>
                {canToggle && (
                  <button
                    type="button"
                    disabled={busy === c.id}
                    onClick={() => {
                      if (cur === "withdrawn") change(c.id, true);
                      else {
                        setTarget({ id: c.id, labelVi: c.labelVi, labelEn: c.labelEn });
                        dlg.current?.showModal();
                      }
                    }}
                    className={`inline-flex min-h-11 w-fit items-center gap-1.5 rounded-xl px-3 text-[0.9375rem] font-semibold transition-colors duration-150 disabled:opacity-50 ${
                      cur === "withdrawn" ? "border-2 border-ink text-ink hover:bg-surface-2" : "border border-red text-red-ink hover:bg-red-tint"
                    }`}
                  >
                    {cur === "withdrawn" ? <Undo2 size={16} aria-hidden /> : <ShieldOff size={16} aria-hidden />}
                    {cur === "withdrawn" ? <T vi="Bật lại" en="Turn back on" /> : <T vi="Rút lại" en="Withdraw" />}
                  </button>
                )}
              </li>
            );
          })}
        </ul>
        <p className="text-sm text-ink-3">
          <T
            vi="Rút lại một mục là ngừng xử lý cho mục đó ngay. Dữ liệu cũ không bị xoá; có thể bật lại bất cứ lúc nào, khi chính người thân đồng ý."
            en="Withdrawing a purpose stops processing for it at once. Existing data is not deleted; it can be turned back on any time, with your parent's agreement."
          />
        </p>
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
            <T vi={`Rút lại đồng ý cho ${elderVi}?`} en={`Withdraw consent for ${elderEn}?`} />
          </h2>
          {target && (
            <p className="font-semibold">
              <T vi={`“${target.labelVi}”`} en={`“${target.labelEn}”`} />
            </p>
          )}
          <p className="text-ink-2">
            {target && WITHDRAW_EFFECT[target.id] ? (
              <T vi={WITHDRAW_EFFECT[target.id].vi} en={WITHDRAW_EFFECT[target.id].en} />
            ) : null}{" "}
            <T vi="Có thể bật lại bất cứ lúc nào." en="You can turn it back on any time." />
          </p>
          <p className="rounded-xl bg-surface-2 px-3 py-2 text-sm text-ink-2">
            <T vi="Dữ liệu đã có không bị xoá." en="Existing data is not deleted." />
          </p>
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <button value="cancel" className="min-h-12 rounded-xl border border-line-strong px-4 font-semibold">
              <T vi="Giữ nguyên" en="Keep as is" />
            </button>
            <button
              value="confirm"
              onClick={() => target && change(target.id, false)}
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
