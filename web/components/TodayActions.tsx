"use client";
import { useEffect, useState, type ReactNode } from "react";
import { Check, CloudOff, MessageSquareHeart, NotebookPen, Phone, PhoneCall, Send, X } from "lucide-react";
import type { ContactStatus, Note } from "@/lib/types";
import { currentViewer } from "@/lib/viewer";
import { useLang, useLocal } from "@/lib/useLang";
import { SENT_EVENT, postWrite, useOutbox, type PendingWrite } from "@/lib/outbox";
import { shortDate } from "@/lib/format";
import { NotSaved, SaveRefused } from "./SaveState";
import { T } from "./T";

const PRESETS: { vi: string; en: string; logsCall?: boolean }[] = [
  { vi: "Đã gọi, {k} khỏe", en: "Called, {K} is fine", logsCall: true },
  { vi: "{K} kêu khó ngủ", en: "{K} says sleep is poor" },
  { vi: "Đã nhắc {k} uống thuốc", en: "Reminded {k} about medicine" },
  { vi: "Cuối tuần sẽ về thăm", en: "Visiting this weekend" },
];

function fill(s: string, k: string) {
  return s.replace("{k}", k).replace("{K}", k.charAt(0).toUpperCase() + k.slice(1));
}

const sameDay = (iso: string | null | undefined) => (iso ? new Date(iso).toDateString() === new Date().toDateString() : false);

type SaveStatus = { state: "idle" | "saving" | "saved" | "queued" } | { state: "rejected"; detail: string };

export function TodayActions({
  elderId,
  kinVi,
  kinEn,
  phone,
  author,
  initialNotes,
  contact,
  todayDate,
  todayDay,
  children,
}: {
  elderId: string;
  kinVi: string;
  kinEn: string;
  phone: string;
  author: string;
  initialNotes: Note[];
  contact: ContactStatus | null;
  todayDate: string;
  todayDay: number;
  /** Rendered right under the call / note buttons (the "Gửi yêu thương" tray). */
  children?: ReactNode;
}) {
  const lang = useLang();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [notes, setNotes] = useState<Note[]>(initialNotes);
  const [status, setStatus] = useState<SaveStatus>({ state: "idle" });
  const [callStatus, setCallStatus] = useState<SaveStatus>({ state: "idle" });
  const [toElder, setToElder] = useState(false);
  const pending = useOutbox(elderId);
  // Set only after the API stored the contact row (directly, or later from the outbox).
  const calledAt = useLocal(`cb-called-${elderId}`);
  const calledToday = sameDay(calledAt);
  const callPending = pending.some((p) => p.kind === "contact" && sameDay(p.createdAt));
  const pendingNotes = pending.filter((p) => p.kind === "note");
  const base = `/api/elders/${encodeURIComponent(elderId)}`;

  // A note that waited in the outbox reached the server: show the stored copy.
  useEffect(() => {
    function sent(e: Event) {
      const { item, json } = (e as CustomEvent<{ item: PendingWrite; json: unknown }>).detail;
      if (item.kind !== "note" || item.elderId !== elderId) return;
      const local = item.meta?.note as Note | undefined;
      const saved = json && typeof json === "object" && "text" in json ? (json as Partial<Note>) : {};
      if (local) setNotes((n) => [{ ...local, ...saved, date: local.date }, ...n]);
    }
    window.addEventListener(SENT_EVENT, sent);
    return () => window.removeEventListener(SENT_EVENT, sent);
  }, [elderId]);

  /** Log a family call in the contact log (feeds "N days since anyone called" and the DMAIC Improve step). */
  async function logCall() {
    setCallStatus({ state: "saving" });
    const r = await postWrite("contact", elderId, `${base}/contacts`, { kind: "call", member_id: currentViewer(elderId).memberId }, {
      markKey: `cb-called-${elderId}`,
    });
    setCallStatus(r.state === "rejected" ? { state: "rejected", detail: r.detail } : { state: r.state });
  }

  async function save(body: string, logsCall = false) {
    const t = body.trim();
    if (!t) return;
    setStatus({ state: "saving" });
    const note: Note = { author, text: t, day: todayDay, date: todayDate, to_elder: toElder, created_at: new Date().toISOString() };
    const r = await postWrite("note", elderId, `${base}/notes`, { author, text: t, to_elder: toElder }, { meta: { note } });
    if (r.state === "rejected") {
      setStatus({ state: "rejected", detail: r.detail });
      return; // keep the text in the box so nothing is lost
    }
    if (r.state === "saved") {
      const saved = r.json && typeof r.json === "object" && "text" in r.json ? (r.json as Partial<Note>) : {};
      setNotes((n) => [{ ...note, ...saved, date: note.date }, ...n]);
    }
    if (logsCall) logCall();
    setText("");
    setOpen(false);
    setStatus({ state: r.state });
    setToElder(false);
  }

  const shownNotes: (Note & { pending?: boolean })[] = [
    ...pendingNotes.map((p) => ({ ...(p.meta?.note as Note), pending: true })).filter((n) => n.text),
    ...notes,
  ];
  const k = lang === "en" ? kinEn : kinVi;

  return (
    <section className="flex flex-col gap-4" aria-label="Hành động / Actions">
      <div className="grid grid-cols-2 gap-3">
        <a
          href={`tel:${phone}`}
          onClick={logCall}
          className="flex min-h-16 items-center justify-center gap-2.5 rounded-2xl bg-accent px-4 text-lg font-bold text-accent-ink shadow-soft transition-colors duration-150 hover:bg-accent-hover active:translate-y-px"
        >
          <Phone size={22} aria-hidden />
          <T vi={`Gọi ${kinVi}`} en={`Call ${kinEn}`} />
        </a>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-controls="quick-note"
          className={`flex min-h-16 items-center justify-center gap-2 whitespace-nowrap rounded-2xl border-2 px-3 text-base font-semibold transition-colors duration-150 ${
            open ? "border-ink bg-ink text-bg" : "border-line-strong bg-surface text-ink hover:border-ink"
          }`}
        >
          {open ? <X size={20} aria-hidden /> : <NotebookPen size={20} aria-hidden />}
          <T vi="Ghi chú nhanh" en="Quick note" />
        </button>
      </div>

      {calledToday ? (
        <p className="flex items-center gap-2 rounded-xl bg-green-tint px-4 py-3 font-medium text-green-ink" role="status">
          <Check size={18} aria-hidden />
          <T vi={`Đã ghi: bạn gọi ${kinVi} hôm nay`} en={`Logged: you called ${kinEn} today`} />
        </p>
      ) : callPending ? (
        <NotSaved />
      ) : callStatus.state === "rejected" ? (
        <SaveRefused detail={callStatus.detail} />
      ) : contact?.nudge && contact.days_since != null ? (
        <p className="flex items-start gap-3 rounded-xl bg-yellow-tint px-4 py-3 text-yellow-ink" role="status">
          <PhoneCall size={20} className="mt-0.5 shrink-0" aria-hidden />
          <span>
            <strong className="font-bold">
              <T vi={`Đã ${contact.days_since} ngày chưa ai gọi ${kinVi}.`} en={`No one has called ${kinEn} for ${contact.days_since} days.`} />
            </strong>{" "}
            {contact.micro_7d ? (
              <T
                vi={`${kinVi[0].toUpperCase()}${kinVi.slice(1)} đã nhận ${contact.micro_7d} lời thương tuần này, gọi ${kinVi} một cuộc nữa nha.`}
                en={`${kinEn} got ${contact.micro_7d} love note${contact.micro_7d > 1 ? "s" : ""} this week; give ${kinEn} a call too.`}
              />
            ) : (
              <T vi="Một cuộc gọi 5 phút cũng đủ." en="Five minutes is enough." />
            )}
            {contact.last && (
              <span className="mt-0.5 block text-sm opacity-90">
                <T
                  vi={`Lần gần nhất: ${contact.last.member_name ?? "gia đình"} ${contact.last.kind === "visit" ? "ghé thăm" : "gọi"}, ${shortDate(contact.last.date)}.`}
                  en={`Last time: ${contact.last.member_name ?? "family"} ${contact.last.kind === "visit" ? "visited" : "called"}, ${shortDate(contact.last.date)}.`}
                />
              </span>
            )}
          </span>
        </p>
      ) : null}

      {children}

      {open && (
        <form
          id="quick-note"
          className="fade-in flex flex-col gap-3 rounded-2xl border border-line bg-surface p-4"
          onSubmit={(e) => {
            e.preventDefault();
            save(text);
          }}
        >
          <p className="text-sm font-semibold text-ink-2">
            <T vi="Chạm một câu có sẵn, hoặc tự viết" en="Tap a ready phrase, or write your own" />
          </p>
          <label className="flex min-h-11 cursor-pointer items-center gap-3 rounded-xl bg-surface-2 px-3 py-2 text-[0.9375rem]">
            <input
              type="checkbox"
              checked={toElder}
              onChange={(e) => setToElder(e.target.checked)}
              className="size-5 shrink-0 accent-[var(--accent)]"
            />
            <span>
              <T
                vi={`Nhờ Út Thương nhắn lại cho ${kinVi} trong cuộc gọi sáng mai`}
                en={`Ask Út Thương to pass this on to ${kinEn} in tomorrow's call`}
              />
            </span>
          </label>
          <div className="flex flex-wrap gap-2">
            {PRESETS.map((p) => {
              const label = fill(lang === "en" ? p.en : p.vi, k);
              return (
                <button
                  key={p.vi}
                  type="button"
                  disabled={status.state === "saving"}
                  onClick={() => save(label, p.logsCall)}
                  className="min-h-11 rounded-full border border-line-strong bg-bg px-3.5 text-[0.9375rem] font-medium transition-colors duration-150 hover:border-accent hover:text-accent disabled:opacity-50"
                >
                  {label}
                </button>
              );
            })}
          </div>
          <div className="flex gap-2">
            <label className="sr-only" htmlFor="note-text">
              {lang === "en" ? "Note" : "Ghi chú"}
            </label>
            <input
              id="note-text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={lang === "en" ? "e.g. Mom has a cough" : `VD: ${kinVi} hơi ho`}
              className="min-h-12 flex-1 rounded-xl border border-line-strong bg-bg px-3.5 text-base placeholder:text-ink-3"
            />
            <button
              type="submit"
              disabled={!text.trim() || status.state === "saving"}
              className="grid min-h-12 min-w-12 place-items-center rounded-xl bg-accent text-accent-ink transition-opacity duration-150 disabled:opacity-40"
            >
              <Send size={20} aria-hidden />
              <span className="sr-only">{lang === "en" ? "Save note" : "Lưu ghi chú"}</span>
            </button>
          </div>
        </form>
      )}

      <div aria-live="polite">
        {status.state === "saved" && (
          <p className="fade-in flex items-center gap-2 text-sm font-medium text-green-ink">
            <Check size={16} aria-hidden />
            <T vi="Đã lưu ghi chú. Cả nhà đều thấy." en="Note saved. The whole family can see it." />
          </p>
        )}
        {status.state === "queued" && pendingNotes.length > 0 && <NotSaved className="fade-in" />}
        {status.state === "rejected" && <SaveRefused detail={status.detail} className="fade-in" />}
      </div>

      {shownNotes.length > 0 && (
        <div>
          <h2 className="mb-2 text-sm font-bold uppercase tracking-wide text-ink-3">
            <T vi="Ghi chú gần đây" en="Recent notes" />
          </h2>
          <ul className="divide-y divide-line">
            {shownNotes.slice(0, 3).map((n, i) => (
              <li key={`${n.id ?? i}-${n.created_at ?? ""}`} className="flex gap-3 py-2.5">
                <span className="w-12 shrink-0 pt-0.5 text-sm text-ink-3 tnum">{n.date ? shortDate(n.date) : ""}</span>
                <p className="min-w-0">
                  <span className="font-semibold">{n.author}:</span> {n.text}
                  {n.to_elder && (
                    <span className="ml-2 inline-flex items-center gap-1 rounded-full bg-accent-tint px-2 py-px align-middle text-xs font-semibold text-accent">
                      <MessageSquareHeart size={12} aria-hidden />
                      <T vi={`nhắn cho ${kinVi}`} en={`to ${kinEn}`} />
                    </span>
                  )}
                  {n.pending && (
                    <span className="ml-2 inline-flex items-center gap-1 rounded-full bg-yellow-tint px-2 py-px align-middle text-xs font-semibold text-yellow-ink">
                      <CloudOff size={12} aria-hidden />
                      <T vi="chưa lưu, giữ trên máy này" en="not saved, kept on this device" />
                    </span>
                  )}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
