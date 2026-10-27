"use client";
// "Gửi yêu thương / Send some love": one tap sends a small card to the elder (standing screen at home, or relayed by
// Út Thương in the morning call). Below the tray: what you (or the family) sent, with Đã gửi → Má đã xem → Má đã trả lời
// and the reply inline. Micro-contacts are counted apart from calls; the tray never replaces "Gọi má".
import { useCallback, useEffect, useMemo, useState } from "react";
import { BookHeart, Check, ChevronDown, HandHeart, Lightbulb, Loader2, PenLine, Send, Sprout } from "lucide-react";
import { fetchKudos, saveAdviceToMemory, sendKudos, type Kudos, type KudosCatalog, type KudosKind, type KudosList, type KudosTemplate } from "@/lib/kudos";
import { useLang } from "@/lib/useLang";
import { shortDate } from "@/lib/format";
import { NotSaved } from "../SaveState";
import { T } from "../T";
import { KudosIcon } from "./KudosIcon";

type Panel = "advice" | "care_tip" | "message" | null;
type Flash = { kind: "sent"; vi: string; en: string } | { kind: "queued" } | { kind: "refused"; vi: string; en: string } | null;

const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);

export function KudosTray({
  elderId,
  kinVi,
  kinEn,
  catalog,
  initial,
  box = "sent",
  compact = false,
}: {
  elderId: string;
  kinVi: string;
  kinEn: string;
  catalog: KudosCatalog | null;
  initial: KudosList | null;
  box?: "sent" | "family";
  compact?: boolean;
}) {
  const lang = useLang();
  const [list, setList] = useState<Kudos[]>(initial?.items ?? []);
  const [remaining, setRemaining] = useState<number>(catalog?.remaining_today ?? initial?.remaining_today ?? 0);
  const [busy, setBusy] = useState<string | null>(null);
  const [justSent, setJustSent] = useState<string | null>(null);
  const [panel, setPanel] = useState<Panel>(null);
  const [flash, setFlash] = useState<Flash>(null);
  const [draft, setDraft] = useState("");
  const [showAll, setShowAll] = useState(false);

  const refresh = useCallback(async () => {
    const r = await fetchKudos(elderId, box);
    if (r) {
      setList(r.items);
      setRemaining(r.remaining_today);
    }
  }, [elderId, box]);

  // Replies arrive from the screen or the morning call: refresh while the page is visible.
  useEffect(() => {
    const id = setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, 15_000);
    return () => clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    if (!justSent) return;
    const id = setTimeout(() => setJustSent(null), 2600);
    return () => clearTimeout(id);
  }, [justSent]);

  const byKind = useMemo(() => {
    const m: Record<string, KudosTemplate[]> = {};
    for (const t of catalog?.templates ?? []) (m[t.kind] ??= []).push(t);
    return m;
  }, [catalog]);

  if (!catalog || !catalog.can_send) {
    return (
      <section aria-labelledby="kudos-h" className="flex flex-col gap-2 rounded-3xl border border-line bg-surface p-4">
        <Header kinVi={kinVi} kinEn={kinEn} remaining={null} />
        <p className="text-[0.9375rem] text-ink-2">
          <T vi="Chưa kết nối được máy chủ, nên chưa gửi được lời thương lúc này." en="The server can't be reached, so love notes can't be sent right now." />
        </p>
      </section>
    );
  }

  const limitReached = remaining <= 0;

  async function send(kind: KudosKind, key: string, body: { kind: KudosKind; template_id?: string; text?: string }) {
    if (busy) return;
    setBusy(key);
    setFlash(null);
    const r = await sendKudos(elderId, body);
    setBusy(null);
    if (r.state === "saved") {
      setList((l) => [r.kudos, ...l.filter((x) => x.id !== r.kudos.id)]);
      setRemaining(r.remaining);
      setJustSent(key);
      setFlash({ kind: "sent", vi: `Đã gửi cho ${kinVi}: “${r.kudos.text_vi}”`, en: `Sent to ${kinEn}: “${r.kudos.text_en}”` });
      if (kind !== "checkin" && kind !== "love") {
        setDraft("");
        setPanel(null);
      }
    } else if (r.state === "queued") {
      setFlash({ kind: "queued" });
    } else {
      setFlash({
        kind: "refused",
        vi: r.message?.vi ?? "Chưa gửi được: máy chủ từ chối.",
        en: r.message?.en ?? "Not sent: the server refused it.",
      });
    }
  }

  const shown = showAll ? list : list.slice(0, compact ? 3 : 5);
  const checkins = byKind.checkin ?? [];
  const loves = byKind.love ?? [];

  return (
    <section aria-labelledby="kudos-h" className="flex flex-col gap-4 rounded-3xl border border-line bg-surface p-4 sm:p-5" data-testid="kudos-tray">
      <Header kinVi={kinVi} kinEn={kinEn} remaining={remaining} />

      <div className="flex flex-col gap-2">
        <h3 className="text-xs font-bold uppercase tracking-wide text-ink-3">
          <T vi="Hỏi thăm" en="Check in" />
        </h3>
        <div className="grid grid-cols-2 gap-2">
          {checkins.map((t) => (
            <button
              key={t.id}
              type="button"
              disabled={limitReached || busy !== null}
              onClick={() => send("checkin", t.id, { kind: "checkin", template_id: t.id })}
              data-testid={`kudos-${t.id}`}
              className="group flex min-h-[4.25rem] flex-col items-start gap-2 rounded-2xl border border-line bg-bg px-3 py-3 text-left transition-colors duration-150 hover:border-accent active:translate-y-px disabled:cursor-not-allowed disabled:opacity-55 sm:flex-row sm:items-center sm:gap-2.5"
            >
              <span
                className={`grid size-9 shrink-0 place-items-center rounded-full transition-colors duration-200 ${
                  justSent === t.id ? "bg-green-tint text-green-ink" : "bg-accent-tint text-accent"
                }`}
              >
                {busy === t.id ? (
                  <Loader2 size={19} className="animate-spin" aria-hidden />
                ) : justSent === t.id ? (
                  <Check size={19} aria-hidden />
                ) : (
                  <KudosIcon name={t.icon} size={19} />
                )}
              </span>
              <span className="min-w-0 text-[0.9375rem] font-semibold leading-snug">
                <T vi={t.label_vi} en={t.label_en} />
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <h3 className="text-xs font-bold uppercase tracking-wide text-ink-3">
          <T vi="Gửi thương" en="Love" />
        </h3>
        <div className="grid grid-cols-4 gap-2">
          {loves.map((t) => (
            <button
              key={t.id}
              type="button"
              disabled={limitReached || busy !== null}
              onClick={() => send("love", t.id, { kind: "love", template_id: t.id })}
              data-testid={`kudos-${t.id}`}
              className="flex min-h-[5.25rem] flex-col items-center justify-center gap-1.5 rounded-2xl bg-rose-tint px-1.5 py-2.5 text-center text-rose-ink transition-[transform,filter] duration-150 hover:brightness-[0.97] active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-55"
            >
              {busy === t.id ? (
                <Loader2 size={22} className="animate-spin" aria-hidden />
              ) : justSent === t.id ? (
                <Check size={22} aria-hidden />
              ) : (
                <KudosIcon name={t.icon} size={22} />
              )}
              <span className="text-[0.8125rem] font-semibold leading-tight">
                <T vi={t.label_vi} en={t.label_en} />
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2" role="group" aria-label={lang === "en" ? "More" : "Thêm"}>
        {(
          [
            ["advice", Lightbulb, `Hỏi ý ${kinVi}`, `Ask ${kinEn}`],
            ["care_tip", Sprout, "Lời dặn", "Caring tip"],
            ["message", PenLine, "Tự viết", "Write"],
          ] as const
        ).map(([k, Icon, vi, en]) => (
          <button
            key={k}
            type="button"
            aria-expanded={panel === k}
            aria-controls="kudos-panel"
            onClick={() => {
              setPanel((p) => (p === k ? null : k));
              setDraft("");
              setFlash(null);
            }}
            data-testid={`kudos-panel-${k}`}
            className={`flex min-h-12 items-center justify-center gap-1 rounded-full border px-1.5 text-sm font-semibold sm:gap-1.5 sm:px-2 sm:text-[0.9375rem] transition-colors duration-150 ${
              panel === k ? "border-ink bg-ink text-bg" : "border-line-strong bg-bg text-ink hover:border-ink"
            }`}
          >
            <Icon size={16} className="shrink-0" aria-hidden />
            <span className="truncate">
              <T vi={vi} en={en} />
            </span>
          </button>
        ))}
      </div>

      {panel && (
        <FreePanel
          panel={panel}
          kinVi={kinVi}
          kinEn={kinEn}
          templates={byKind[panel] ?? []}
          draft={draft}
          setDraft={setDraft}
          maxText={catalog.max_text}
          disabled={limitReached || busy !== null}
          busy={busy}
          voiceNote={catalog.voice_note}
          onPreset={(t) => send(panel, t.id, { kind: panel, template_id: t.id })}
          onText={() => send(panel, `free-${panel}`, { kind: panel, text: draft.trim() })}
        />
      )}

      <div aria-live="polite" className="empty:hidden">
        {flash?.kind === "sent" && (
          <p className="fade-in flex items-start gap-2 text-sm font-medium text-green-ink" data-testid="kudos-flash">
            <Check size={16} className="mt-0.5 shrink-0" aria-hidden />
            <T vi={flash.vi} en={flash.en} />
          </p>
        )}
        {flash?.kind === "queued" && <NotSaved className="fade-in" />}
        {flash?.kind === "refused" && (
          <p className="fade-in rounded-xl bg-yellow-tint px-3 py-2 text-sm font-medium text-yellow-ink" role="alert" data-testid="kudos-refused">
            <T vi={flash.vi} en={flash.en} />
          </p>
        )}
        {limitReached && flash?.kind !== "refused" && (
          <p className="rounded-xl bg-surface-2 px-3 py-2 text-sm text-ink-2">
            <T
              vi={`Hôm nay bạn đã gửi đủ ${catalog.limit_per_day} lời thương. Mai gửi tiếp, hoặc gọi ${kinVi} một cuộc nha.`}
              en={`You've sent ${catalog.limit_per_day} notes today. Send more tomorrow, or give ${kinEn} a call.`}
            />
          </p>
        )}
      </div>

      {shown.length > 0 && (
        <div className="flex flex-col gap-2 border-t border-line pt-4">
          <h3 className="text-xs font-bold uppercase tracking-wide text-ink-3">
            {box === "family" ? <T vi="Cả nhà đã gửi" en="Sent by the family" /> : <T vi="Bạn đã gửi" en="You sent" />}
          </h3>
          <ul className="flex flex-col gap-2" data-testid="kudos-list">
            {shown.map((k) => (
              <KudosRow key={k.id} k={k} elderId={elderId} kinVi={kinVi} kinEn={kinEn} showSender={box === "family"} onChanged={refresh} />
            ))}
          </ul>
          {!showAll && list.length > shown.length && (
            <button
              type="button"
              onClick={() => setShowAll(true)}
              className="flex min-h-11 items-center gap-1 self-start rounded-full px-1 text-sm font-semibold text-accent"
            >
              <ChevronDown size={16} aria-hidden />
              <T vi={`Xem thêm ${list.length - shown.length}`} en={`Show ${list.length - shown.length} more`} />
            </button>
          )}
          <p className="text-xs text-ink-3">
            <T
              vi="Câu trả lời là má tự chọn: chỉ để cả nhà biết, không tính vào đèn. Lời thương không thay cho cuộc gọi."
              en="Answers are self-reported: for the family to know, never scored into the light. Love notes never replace a call."
            />
          </p>
        </div>
      )}
    </section>
  );
}

function Header({ kinVi, kinEn, remaining }: { kinVi: string; kinEn: string; remaining: number | null }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <h2 id="kudos-h" className="flex items-center gap-2 text-lg font-extrabold tracking-tight">
          <span className="grid size-8 place-items-center rounded-full bg-rose-tint text-rose-ink">
            <HandHeart size={18} aria-hidden />
          </span>
          <T vi="Gửi yêu thương" en="Send some love" />
        </h2>
        <p className="mt-1 text-[0.9375rem] leading-snug text-ink-2">
          <T
            vi={`Một chạm là ${kinVi} nhận được, trên màn hình ở nhà hoặc qua cuộc gọi sáng.`}
            en={`One tap and ${kinEn} gets it, on the home screen or in the morning call.`}
          />
        </p>
      </div>
      {remaining !== null && (
        <span className="mt-1 shrink-0 rounded-full bg-surface-2 px-2.5 py-1 text-xs font-semibold text-ink-2 tnum" data-testid="kudos-remaining">
          <T vi={`Còn ${remaining} lượt`} en={`${remaining} left today`} />
        </span>
      )}
    </div>
  );
}

function FreePanel({
  panel,
  kinVi,
  kinEn,
  templates,
  draft,
  setDraft,
  maxText,
  disabled,
  busy,
  voiceNote,
  onPreset,
  onText,
}: {
  panel: "advice" | "care_tip" | "message";
  kinVi: string;
  kinEn: string;
  templates: KudosTemplate[];
  draft: string;
  setDraft: (s: string) => void;
  maxText: number;
  disabled: boolean;
  busy: string | null;
  voiceNote: { note_vi: string; note_en: string };
  onPreset: (t: KudosTemplate) => void;
  onText: () => void;
}) {
  const lang = useLang();
  const copy = {
    advice: {
      vi: `Hỏi ý ${kinVi} một chuyện ${kinVi} rành. Được con cháu hỏi tới, ${kinVi} thấy mình còn được cần.`,
      en: `Ask ${kinEn} about something ${kinEn} knows well. Being asked makes ${kinEn} feel needed.`,
      ph: lang === "en" ? `Ask ${kinEn} something else…` : `Hỏi ${kinVi} chuyện khác…`,
    },
    care_tip: {
      vi: "Lời dặn nhẹ nhàng. Chào Bà không chuyển lời khuyên về thuốc hay chẩn đoán.",
      en: "A gentle reminder. Chào Bà never passes on medication advice or diagnoses.",
      ph: lang === "en" ? "e.g. Wear a hat in the garden" : `VD: Ra vườn ${kinVi} nhớ đội nón nha`,
    },
    message: {
      vi: "Một lời nhắn ngắn.",
      en: "A short message.",
      ph: lang === "en" ? "Your message…" : "Lời nhắn của bạn…",
    },
  }[panel];
  return (
    <form
      id="kudos-panel"
      className="fade-in flex flex-col gap-3 rounded-2xl bg-surface-2 p-3.5"
      onSubmit={(e) => {
        e.preventDefault();
        if (draft.trim()) onText();
      }}
    >
      <p className="text-[0.9375rem] text-ink-2">
        <T vi={copy.vi} en={copy.en} />
      </p>
      {templates.length > 0 && (
        <div className="flex flex-col gap-2">
          {templates.map((t) => (
            <button
              key={t.id}
              type="button"
              disabled={disabled}
              onClick={() => onPreset(t)}
              data-testid={`kudos-${t.id}`}
              className="flex min-h-12 items-center gap-3 rounded-xl border border-line bg-surface px-3 py-2 text-left transition-colors duration-150 hover:border-accent disabled:opacity-55"
            >
              <span className={`grid size-8 shrink-0 place-items-center rounded-full ${panel === "advice" ? "bg-yellow-tint text-yellow-ink" : "bg-green-tint text-green-ink"}`}>
                {busy === t.id ? <Loader2 size={16} className="animate-spin" aria-hidden /> : <KudosIcon name={t.icon} size={16} />}
              </span>
              <span className="min-w-0 flex-1 text-[0.9375rem] font-medium leading-snug">
                <T vi={t.text_vi} en={t.text_en} />
              </span>
              <Send size={16} className="shrink-0 text-ink-3" aria-hidden />
            </button>
          ))}
        </div>
      )}
      <div className="flex gap-2">
        <label htmlFor="kudos-text" className="sr-only">
          {lang === "en" ? "Your own words" : "Tự viết"}
        </label>
        <input
          id="kudos-text"
          value={draft}
          maxLength={maxText}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={copy.ph}
          autoComplete="off"
          data-testid="kudos-text"
          className="min-h-12 min-w-0 flex-1 rounded-xl border border-line-strong bg-surface px-3.5 text-base placeholder:text-ink-3"
        />
        <button
          type="submit"
          disabled={disabled || !draft.trim()}
          data-testid="kudos-send-text"
          className="grid min-h-12 min-w-12 place-items-center rounded-xl bg-accent text-accent-ink transition-opacity duration-150 disabled:opacity-40"
        >
          {busy?.startsWith("free-") ? <Loader2 size={20} className="animate-spin" aria-hidden /> : <Send size={20} aria-hidden />}
          <span className="sr-only">{lang === "en" ? "Send" : "Gửi"}</span>
        </button>
      </div>
      {panel === "message" && (
        <p className="text-xs text-ink-3">
          <T vi={voiceNote.note_vi} en={voiceNote.note_en} />
        </p>
      )}
    </form>
  );
}

const STEPS = ["sent", "seen", "replied"] as const;

function KudosRow({
  k,
  elderId,
  kinVi,
  kinEn,
  showSender,
  onChanged,
}: {
  k: Kudos;
  elderId: string;
  kinVi: string;
  kinEn: string;
  showSender: boolean;
  onChanged: () => void;
}) {
  const [confirm, setConfirm] = useState(false);
  const [agreed, setAgreed] = useState(false);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [openReply, setOpenReply] = useState(false);
  const step = STEPS.indexOf(k.status);
  const K = cap(kinVi);
  const canSave = k.kind === "advice" && !!k.reply?.text && !k.story?.saved && !k.story?.declined && !k.redacted;
  const love = k.kind === "love";
  const labels = [
    { vi: "Đã gửi", en: "Sent" },
    { vi: `${K} đã xem`, en: `${kinEn} saw it` },
    { vi: `${K} đã trả lời`, en: `${kinEn} replied` },
  ];

  async function save() {
    setSaveState("saving");
    const r = await saveAdviceToMemory(elderId, k.id);
    if (r.state === "saved") {
      setSaveState("saved");
      onChanged();
    } else setSaveState("error");
  }

  return (
    <li className="flex gap-3 rounded-2xl border border-line bg-bg p-3" data-testid="kudos-row" data-status={k.status}>
      <span className={`grid size-9 shrink-0 place-items-center rounded-full ${love ? "bg-rose-tint text-rose-ink" : "bg-surface-2 text-ink-2"}`}>
        <KudosIcon name={k.icon} size={17} />
      </span>
      <div className="min-w-0 flex-1">
        <p className="flex items-baseline justify-between gap-2">
          <span className={`min-w-0 font-semibold leading-snug ${k.redacted ? "italic text-ink-3" : ""}`}>
            {showSender && <span className="font-bold">{k.sender_name}: </span>}
            {k.text_lang === "vi" ? <span lang="vi">“{k.text_vi}”</span> : <T vi={`“${k.text_vi}”`} en={`“${k.text_en}”`} />}
          </span>
          <span className="shrink-0 text-xs text-ink-3 tnum">
            {shortDate(k.date)} {k.sent_time}
          </span>
        </p>
        <p className="mt-1.5 flex items-center gap-2 text-xs font-semibold text-ink-2" data-testid="kudos-status">
          <span className="flex items-center gap-1" aria-hidden>
            {STEPS.map((_, i) => (
              <span
                key={i}
                className={`h-1.5 w-4 rounded-full ${i <= step ? (step === 2 ? "bg-green" : "bg-accent") : "bg-line-strong"}`}
              />
            ))}
          </span>
          <T vi={labels[step].vi} en={labels[step].en} />
        </p>
        {(k.reply_vi || k.reply_hidden) && (
          <p
            className={`mt-2 rounded-xl px-3 py-2 text-[0.9375rem] leading-snug ${k.reply?.heart && !k.reply?.choice && !k.reply?.text ? "bg-rose-tint text-rose-ink" : "bg-green-tint text-green-ink"}`} data-testid="kudos-reply">
            <span className={`block ${openReply ? "" : "line-clamp-3"}`}>
              <T vi={k.reply_vi} en={k.reply_en} />
            </span>
          </p>
        )}
        {(k.reply?.text?.length ?? 0) > 140 && (
          <button type="button" onClick={() => setOpenReply((o) => !o)} aria-expanded={openReply} className="mt-1 min-h-9 text-sm font-semibold text-accent">
            {openReply ? <T vi="Thu gọn" en="Show less" /> : <T vi="Xem hết câu trả lời" en="Read the whole answer" />}
          </button>
        )}
        {k.folk_note && k.reply?.text && (
          <p className="mt-1 text-xs text-ink-3">
            <T vi="Kinh nghiệm dân gian của người lớn trong nhà, không phải lời khuyên y khoa." en="Family folk wisdom, not medical advice." />
          </p>
        )}
        {k.story?.saved && (
          <p className="mt-1.5 flex items-center gap-1.5 text-sm font-semibold text-accent">
            <BookHeart size={15} aria-hidden />
            <T vi={`Đã lưu vào Sổ ký ức: Lời ${kinVi} dạy`} en={`Saved to the memory book: ${kinEn}'s advice`} />
          </p>
        )}
        {k.story?.declined && (
          <p className="mt-1.5 text-sm text-ink-3">
            <T vi={`${K} muốn giữ riêng câu trả lời này.`} en={`${kinEn} prefers to keep this answer private.`} />
          </p>
        )}
        {canSave && saveState !== "saved" && (
          <div className="mt-2">
            {!confirm ? (
              <button
                type="button"
                onClick={() => setConfirm(true)}
                className="flex min-h-11 items-center gap-1.5 rounded-full border border-line-strong px-3.5 text-sm font-semibold transition-colors duration-150 hover:border-accent hover:text-accent"
              >
                <BookHeart size={16} aria-hidden />
                <T vi="Lưu vào Sổ ký ức" en="Save to the memory book" />
              </button>
            ) : (
              <div className="flex flex-col gap-2 rounded-xl bg-surface-2 p-3">
                <label className="flex cursor-pointer items-start gap-2.5 text-[0.9375rem]">
                  <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} className="mt-1 size-5 shrink-0 accent-[var(--accent)]" />
                  <span>
                    <T vi={`${K} đã đồng ý cho lưu lời dạy này để cả nhà cùng đọc.`} en={`${kinEn} agreed to keep this advice for the whole family to read.`} />
                  </span>
                </label>
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={!agreed || saveState === "saving"}
                    onClick={save}
                    className="min-h-11 rounded-full bg-accent px-4 text-sm font-semibold text-accent-ink disabled:opacity-40"
                  >
                    <T vi="Lưu" en="Save" />
                  </button>
                  <button type="button" onClick={() => setConfirm(false)} className="min-h-11 rounded-full px-3 text-sm font-semibold text-ink-2">
                    <T vi="Để sau" en="Later" />
                  </button>
                </div>
                {saveState === "error" && (
                  <p className="text-sm text-red-ink" role="alert">
                    <T vi="Chưa lưu được, thử lại sau nha." en="Couldn't save; please try again later." />
                  </p>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </li>
  );
}
