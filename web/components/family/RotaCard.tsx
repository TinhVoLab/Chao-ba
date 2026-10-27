"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { CalendarSync, Check, Minus, Pencil, PhoneCall, X } from "lucide-react";
import type { FamilyMemberRow, FamilyViewer, Rota } from "@/lib/types";
import { postWrite, useOutbox } from "@/lib/outbox";
import { shortDate } from "@/lib/format";
import { NotSaved, SaveRefused } from "../SaveState";
import { T } from "../T";

const SHORT_VI = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];
const SHORT_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const initial = (name: string | null) => (name ?? "?").replace(/^Bà /, "").charAt(0);

/** "Lịch gọi luân phiên": who calls on which weekday, whose turn it is today, and the last 7 days. */
export function RotaCard({
  elderId,
  rota,
  members,
  viewer,
  kinVi,
  kinEn,
}: {
  elderId: string;
  rota: Rota;
  members: FamilyMemberRow[];
  viewer: FamilyViewer;
  kinVi: string;
  kinEn: string;
}) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, string>>(() =>
    Object.fromEntries(rota.week.map((s) => [String(s.weekday), s.member_id ?? ""])),
  );
  const [status, setStatus] = useState<{ state: "idle" | "saving" | "queued" } | { state: "rejected"; detail: string }>({ state: "idle" });
  const pending = useOutbox(elderId).some((p) => p.kind === "rota");
  const today = rota.today;
  const mine = rota.mine;

  async function save() {
    setStatus({ state: "saving" });
    const assignments = Object.fromEntries(Object.entries(draft).map(([k, v]) => [k, v || null]));
    const r = await postWrite("rota", elderId, `/api/elders/${encodeURIComponent(elderId)}/family/rota`, { assignments });
    if (r.state === "rejected") return setStatus({ state: "rejected", detail: r.detail });
    setStatus({ state: r.state === "queued" ? "queued" : "idle" });
    setEditing(false);
    if (r.state === "saved") router.refresh();
  }

  return (
    <section aria-labelledby="rota-h" className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="rota-h" className="flex items-center gap-2 text-sm font-bold uppercase tracking-wide text-ink-3">
          <CalendarSync size={16} aria-hidden />
          <T vi="Lịch gọi luân phiên" en="Call rota" />
        </h2>
        {viewer.permissions.edit_rota && !editing && (
          <button type="button" onClick={() => setEditing(true)} className="inline-flex min-h-11 items-center gap-1.5 font-semibold text-accent">
            <Pencil size={15} aria-hidden />
            <T vi="Sửa lịch" en="Edit" />
          </button>
        )}
      </div>

      {/* Today */}
      {mine?.your_turn ? (
        <p className="flex items-start gap-3 rounded-2xl bg-accent px-4 py-3 text-accent-ink" role="status">
          <PhoneCall size={20} className="mt-0.5 shrink-0" aria-hidden />
          <span>
            <strong className="block font-bold">
              <T vi={`Hôm nay tới lượt bạn gọi ${kinVi}.`} en={`It's your turn to call ${kinEn} today.`} />
            </strong>
            <span className="text-sm opacity-90">
              <T vi="Gọi xong, bấm “Gọi” ở trang Hôm nay để cả nhà biết." en="After the call, tap “Call” on Today so everyone knows." />
            </span>
          </span>
        </p>
      ) : (
        <p className={`rounded-2xl px-4 py-3 ${today.done ? "bg-green-tint text-green-ink" : "bg-surface-2 text-ink"}`} role="status">
          {today.member_name ? (
            today.done ? (
              <T vi={`Hôm nay ${today.member_name} đã gọi ${kinVi}.`} en={`${today.member_name} has called ${kinEn} today.`} />
            ) : (
              <T vi={`Hôm nay (${today.weekday_vi}) tới lượt ${today.member_name}.`} en={`Today (${today.weekday_en}) is ${today.member_name}'s turn.`} />
            )
          ) : (
            <T vi="Hôm nay chưa ai nhận lượt gọi." en="Nobody is down to call today." />
          )}
          {mine?.next && !mine.your_turn && (
            <span className="block text-sm text-ink-2">
              <T
                vi={`Lượt của bạn: ${SHORT_VI[mine.next.weekday]}, ${shortDate(mine.next.date)}${mine.next.in_days === 1 ? " (mai)" : ""}.`}
                en={`Your turn: ${SHORT_EN[mine.next.weekday]} ${shortDate(mine.next.date)}${mine.next.in_days === 1 ? " (tomorrow)" : ""}.`}
              />
            </span>
          )}
        </p>
      )}
      {rota.gap.nudge && rota.nudge_vi && (
        <p className="flex items-start gap-3 rounded-2xl bg-yellow-tint px-4 py-3 font-medium text-yellow-ink" role="status">
          <PhoneCall size={18} className="mt-0.5 shrink-0" aria-hidden />
          <T vi={rota.nudge_vi} en={rota.nudge_en ?? rota.nudge_vi} />
        </p>
      )}

      {/* Week */}
      {editing ? (
        <div className="fade-in flex flex-col gap-2 rounded-2xl border border-line bg-surface p-3">
          {rota.week.map((s) => (
            <label key={s.weekday} className="flex min-h-11 items-center justify-between gap-3">
              <span className="font-medium">
                <T vi={s.weekday_vi} en={s.weekday_en} />
              </span>
              <select
                value={draft[String(s.weekday)] ?? ""}
                onChange={(e) => setDraft((d) => ({ ...d, [String(s.weekday)]: e.target.value }))}
                className="min-h-11 w-40 rounded-xl border border-line-strong bg-bg px-3"
              >
                <option value="">—</option>
                {members.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
            </label>
          ))}
          <div className="mt-1 flex gap-2">
            <button
              type="button"
              onClick={save}
              disabled={status.state === "saving"}
              className="min-h-11 flex-1 rounded-xl bg-accent font-semibold text-accent-ink disabled:opacity-50"
            >
              <T vi="Lưu lịch" en="Save rota" />
            </button>
            <button type="button" onClick={() => setEditing(false)} className="min-h-11 rounded-xl border border-line-strong px-4 font-semibold">
              <T vi="Huỷ" en="Cancel" />
            </button>
          </div>
        </div>
      ) : (
        <ol className="grid grid-cols-7 gap-1" aria-label="Tuần / Week">
          {rota.week.map((s) => {
            const isToday = s.weekday === today.weekday;
            const isMine = s.member_id != null && s.member_id === viewer.member_id;
            return (
              <li
                key={s.weekday}
                className={`flex flex-col items-center gap-1 rounded-xl py-2 ${isToday ? "bg-ink text-bg" : "bg-surface"}`}
              >
                <span className={`text-xs font-semibold ${isToday ? "" : "text-ink-3"}`}>
                  <T vi={SHORT_VI[s.weekday]} en={SHORT_EN[s.weekday]} />
                </span>
                <span
                  className={`grid size-8 place-items-center rounded-full text-sm font-bold ${
                    isMine ? "bg-accent text-accent-ink" : isToday ? "bg-bg/20" : "bg-surface-2 text-ink-2"
                  }`}
                  title={s.member_name ?? ""}
                >
                  {s.member_id ? initial(s.member_name) : "–"}
                </span>
                <span className="sr-only">{s.member_name ?? "—"}</span>
              </li>
            );
          })}
        </ol>
      )}
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink-3">
        {members.map((m) => (
          <li key={m.id}>
            <span className="font-semibold text-ink-2">{initial(m.name)}</span> = {m.name}
          </li>
        ))}
      </ul>

      {/* Last 7 days */}
      <div>
        <p className="mb-1.5 text-sm font-semibold text-ink-2">
          <T vi="7 ngày qua" en="Last 7 days" />
        </p>
        <ol className="grid grid-cols-7 gap-1">
          {rota.history.map((h) => {
            const who = h.contacts.map((c) => c.member_name).join(", ");
            const label = h.by_assignee
              ? { vi: `${h.member_name} đã gọi`, en: `${h.member_name} called` }
              : h.contacted
                ? { vi: `${who} gọi thay`, en: `${who} called instead` }
                : { vi: "Không ai gọi", en: "Nobody called" };
            return (
              <li key={h.date} className="flex flex-col items-center gap-1" title={`${shortDate(h.date)}: ${label.vi} / ${label.en}`}>
                <span
                  className={`grid size-8 place-items-center rounded-full ${
                    h.by_assignee ? "bg-green text-on-green" : h.contacted ? "bg-green-tint text-green-ink" : "border-2 border-dashed border-line-strong text-ink-3"
                  }`}
                >
                  {h.by_assignee ? <Check size={16} aria-hidden /> : h.contacted ? <Minus size={16} aria-hidden /> : <X size={14} aria-hidden />}
                </span>
                <span className="text-[0.6875rem] text-ink-3 tnum">{shortDate(h.date)}</span>
                <span className="sr-only">
                  <T vi={label.vi} en={label.en} />
                </span>
              </li>
            );
          })}
        </ol>
        <p className="mt-1.5 flex flex-wrap gap-x-3 text-xs text-ink-3">
          <span className="inline-flex items-center gap-1"><Check size={12} aria-hidden /><T vi="đúng người gọi" en="on rota" /></span>
          <span className="inline-flex items-center gap-1"><Minus size={12} aria-hidden /><T vi="người khác gọi" en="someone else" /></span>
          <span className="inline-flex items-center gap-1"><X size={12} aria-hidden /><T vi="không ai gọi" en="nobody" /></span>
        </p>
      </div>
      {(pending || status.state === "queued") && <NotSaved />}
      {status.state === "rejected" && <SaveRefused detail={status.detail} />}
    </section>
  );
}
