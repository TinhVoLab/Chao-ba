"use client";
import { useState } from "react";
import { Check, MessageSquareHeart, NotebookPen, Phone, PhoneCall, Send, X } from "lucide-react";
import type { Note } from "@/lib/types";
import { API_BASE } from "@/lib/config";
import { useLang, useLocal, writeLocal } from "@/lib/useLang";
import { shortDate } from "@/lib/format";
import { T } from "./T";

const PRESETS: { vi: string; en: string }[] = [
  { vi: "Đã gọi, {k} khỏe", en: "Called, {K} is fine" },
  { vi: "{K} kêu khó ngủ", en: "{K} says sleep is poor" },
  { vi: "Đã nhắc {k} uống thuốc", en: "Reminded {k} about medicine" },
  { vi: "Cuối tuần sẽ về thăm", en: "Visiting this weekend" },
];

function fill(s: string, k: string) {
  return s.replace("{k}", k).replace("{K}", k.charAt(0).toUpperCase() + k.slice(1));
}

export function TodayActions({
  elderId,
  kinVi,
  kinEn,
  phone,
  author,
  initialNotes,
  daysSinceContact,
  live,
  todayDate,
  todayDay,
}: {
  elderId: string;
  kinVi: string;
  kinEn: string;
  phone: string;
  author: string;
  initialNotes: Note[];
  daysSinceContact: number | null;
  live: boolean;
  todayDate: string;
  todayDay: number;
}) {
  const lang = useLang();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [notes, setNotes] = useState<Note[]>(initialNotes);
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "local">("idle");
  const [toElder, setToElder] = useState(false);
  const calledAt = useLocal(`cb-called-${elderId}`);
  const calledToday = calledAt ? new Date(calledAt).toDateString() === new Date().toDateString() : false;

  async function save(body: string) {
    const t = body.trim();
    if (!t) return;
    setStatus("saving");
    let note: Note = { author, text: t, day: todayDay, date: todayDate, to_elder: toElder, created_at: new Date().toISOString() };
    let ok = false;
    if (live) {
      try {
        const res = await fetch(`${API_BASE}/api/elders/${encodeURIComponent(elderId)}/notes`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ author, text: t, to_elder: toElder }),
          signal: AbortSignal.timeout(4000),
        });
        ok = res.ok;
        if (ok) {
          const saved = (await res.json().catch(() => null)) as Partial<Note> | null;
          if (saved && typeof saved === "object" && "text" in saved) note = { ...note, ...saved, date: note.date };
        }
      } catch {
        ok = false;
      }
    }
    setNotes((n) => [note, ...n]);
    setText("");
    setOpen(false);
    setStatus(ok ? "saved" : "local");
    setToElder(false);
  }

  const k = lang === "en" ? kinEn : kinVi;

  return (
    <section className="flex flex-col gap-4" aria-label="Hành động / Actions">
      <div className="grid grid-cols-2 gap-3">
        <a
          href={`tel:${phone}`}
          onClick={() => writeLocal(`cb-called-${elderId}`, new Date().toISOString())}
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
          <T vi={`Bạn đã bấm gọi ${kinVi} hôm nay`} en={`You called ${kinEn} today`} />
        </p>
      ) : daysSinceContact != null && daysSinceContact >= 2 ? (
        <p className="flex items-start gap-3 rounded-xl bg-yellow-tint px-4 py-3 text-yellow-ink">
          <PhoneCall size={20} className="mt-0.5 shrink-0" aria-hidden />
          <span>
            <strong className="font-bold">
              <T vi={`Đã ${daysSinceContact} ngày chưa ai gọi ${kinVi}.`} en={`No one has called ${kinEn} for ${daysSinceContact} days.`} />
            </strong>{" "}
            <T vi="Một cuộc gọi 5 phút cũng đủ." en="Five minutes is enough." />
          </span>
        </p>
      ) : null}

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
                  disabled={status === "saving"}
                  onClick={() => save(label)}
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
              disabled={!text.trim() || status === "saving"}
              className="grid min-h-12 min-w-12 place-items-center rounded-xl bg-accent text-accent-ink transition-opacity duration-150 disabled:opacity-40"
            >
              <Send size={20} aria-hidden />
              <span className="sr-only">{lang === "en" ? "Save note" : "Lưu ghi chú"}</span>
            </button>
          </div>
        </form>
      )}

      <div aria-live="polite">
        {status === "saved" && (
          <p className="fade-in flex items-center gap-2 text-sm font-medium text-green-ink">
            <Check size={16} aria-hidden />
            <T vi="Đã lưu ghi chú. Cả nhà đều thấy." en="Note saved. The whole family can see it." />
          </p>
        )}
        {status === "local" && (
          <p className="fade-in flex items-center gap-2 text-sm font-medium text-ink-2">
            <Check size={16} aria-hidden />
            <T vi="Đã lưu trên máy này (chế độ demo ngoại tuyến)." en="Saved on this device (offline demo mode)." />
          </p>
        )}
      </div>

      {notes.length > 0 && (
        <div>
          <h2 className="mb-2 text-sm font-bold uppercase tracking-wide text-ink-3">
            <T vi="Ghi chú gần đây" en="Recent notes" />
          </h2>
          <ul className="divide-y divide-line">
            {notes.slice(0, 3).map((n, i) => (
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
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
