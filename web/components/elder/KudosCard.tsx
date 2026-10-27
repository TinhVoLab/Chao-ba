"use client";
// A family love note on the elder's standing screen ("Lan gửi: Má ăn cơm chưa?"): sender photo with a soft visual
// chime (no sound), the card in big type, huge answer buttons, "Gửi thương lại", and for "Hỏi ý má" a spoken answer
// (the screen's voice listener; typed fallback) or "Để má gọi lại nói". Answers are self-reports, never scored.
import { useEffect, useRef, useState } from "react";
import { BookHeart, Check, Clock, Heart, Keyboard, Mic, PhoneCall, RotateCcw, Send, X } from "lucide-react";
import type { FamilyMember } from "@/lib/types";
import type { Kudos } from "@/lib/kudos";
import { Listener } from "@/lib/voice/listener";
import { KudosIcon } from "../kudos/KudosIcon";
import { Portrait } from "./Portrait";
import { cap, elderCalls, useT } from "./util";
import s from "./classes";

export type KudosAnswer = { choice?: string; text?: string; heart?: boolean };

type Stage = "ask" | "speak" | "review" | "save" | "done";

export function KudosCard({
  card,
  member,
  index,
  total,
  elderLabel,
  typed,
  onAnswer,
  onLater,
  onClose,
  onSave,
  onDone,
}: {
  card: Kudos;
  member: FamilyMember;
  index: number;
  total: number;
  elderLabel: string;
  typed: boolean;
  onAnswer: (a: KudosAnswer) => Promise<void>;
  onLater: () => void;
  onClose: () => void;
  onSave: (agree: boolean) => Promise<void>;
  onDone: () => void;
}) {
  const t = useT();
  const [stage, setStage] = useState<Stage>("ask");
  const [doneMsg, setDoneMsg] = useState<{ heart: boolean; text: string }>({ heart: false, text: "" });
  const [answer, setAnswer] = useState("");
  const [interim, setInterim] = useState("");
  const [typing, setTyping] = useState(typed);
  const [listening, setListening] = useState(false);
  const [busy, setBusy] = useState(false);
  const listenerRef = useRef<Listener | null>(null);
  const who = elderCalls(member); // "con Lan", "Vy", "bà Tư"
  const me = card.elder_self_vi || "má";

  useEffect(() => {
    if (stage !== "done") return;
    const id = setTimeout(onDone, 2600);
    return () => clearTimeout(id);
  }, [stage, onDone]);

  useEffect(() => () => listenerRef.current?.close(), []);

  async function answerWith(a: KudosAnswer, msg: { heart: boolean; text: string }, next: Stage = "done") {
    if (busy) return;
    setBusy(true);
    await onAnswer(a);
    setBusy(false);
    setDoneMsg(msg);
    setStage(next);
  }

  const sentTo = t(`Đã gửi cho ${who} rồi nha.`, `Sent to ${card.sender_name}.`);
  const heartTo = t(`Đã gửi thương lại cho ${who}.`, `Love sent back to ${card.sender_name}.`);

  async function startSpeaking() {
    setStage("speak");
    setInterim("");
    if (typing) return;
    setAnswer("");
    const l =
      listenerRef.current ??
      new Listener(() => performance.now() / 1000, {
        onInterim: setInterim,
        onSttBroken: () => setTyping(true),
        isActive: () => true,
      });
    listenerRef.current = l;
    setListening(true);
    await l.initMic();
    const turn = await l.listen();
    setListening(false);
    l.close();
    if (turn.toTyped) {
      setTyping(true);
      return;
    }
    if (turn.text.trim()) {
      setAnswer(turn.text.trim());
      setStage("review");
    }
  }

  function stopListening() {
    listenerRef.current?.cancelToTypedIfListening();
    setTyping(true);
  }

  const advice = card.kind === "advice";
  const love = card.kind === "love" || card.kind === "message";

  return (
    <section className={s.kudos} aria-label={t("Lời thương từ gia đình", "A note from the family")} data-testid="kudos-card" data-kind={card.kind}>
      <header className={s.kTop}>
        <p className={s.kKicker}>{t("Lời thương từ gia đình", "From the family")}</p>
        {total > 1 && (
          <p className={s.kCount} data-testid="kudos-queue">
            {t(`${index + 1} / ${total}`, `${index + 1} of ${total}`)}
          </p>
        )}
      </header>

      <div className={s.kFrom}>
        <span className={s.kPhoto} data-chime={stage === "ask"}>
          <span className={s.kPhotoClip}>
            <Portrait member={member} id={`kp-${card.id}`} fit="meet" />
          </span>
        </span>
        <div>
          <p className={s.kWho}>{t(`${cap(who)} gửi`, `${card.sender_name} sent`)}</p>
          <p className={s.kWhen}>{t(`lúc ${card.sent_time}`, `at ${card.sent_time}`)}</p>
        </div>
      </div>

      <div className={s.kBubble} data-love={love}>
        <KudosIcon name={card.icon} className={s.kIco} />
        <p className={s.kText} lang="vi" data-testid="kudos-text">
          {card.text_vi}
        </p>
      </div>

      {stage === "ask" && (
        <div className={s.kActions}>
          {card.kind === "checkin" && (
            <div className={s.kChoices} data-n={card.choices.length}>
              {card.choices.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  className={s.kChoice}
                  disabled={busy}
                  onClick={() => answerWith({ choice: c.id }, { heart: false, text: sentTo })}
                  data-testid={`kudos-choice-${c.id}`}
                >
                  {t(c.vi, c.en)}
                </button>
              ))}
            </div>
          )}
          {card.kind === "care_tip" && (
            <button type="button" className={s.kPrimary} disabled={busy} onClick={() => answerWith({ choice: "ok" }, { heart: false, text: sentTo })} data-testid="kudos-choice-ok">
              <Check aria-hidden /> {t("Nhớ rồi", "Got it")}
            </button>
          )}
          {advice && (
            <>
              <button type="button" className={s.kPrimary} onClick={() => void startSpeaking()} data-testid="kudos-speak">
                {typing ? <Keyboard aria-hidden /> : <Mic aria-hidden />}
                {typing ? t("Gõ câu trả lời", "Type the answer") : t("Nói câu trả lời", "Say the answer")}
              </button>
              <button
                type="button"
                className={s.kGhost}
                disabled={busy}
                onClick={() => answerWith({ choice: "call_back" }, { heart: false, text: t(`Con nhắn ${who} chờ ${elderLabel} gọi nha.`, `${card.sender_name} will wait for your call.`) })}
                data-testid="kudos-callback"
              >
                <PhoneCall aria-hidden /> {t(`Để ${me} gọi lại nói`, "I'll call back")}
              </button>
            </>
          )}
          <div className={s.kRow}>
            <button
              type="button"
              className={love ? s.kHeartBig : s.kHeart}
              disabled={busy}
              onClick={() => answerWith({ heart: true }, { heart: true, text: heartTo })}
              data-testid="kudos-heart"
            >
              <Heart aria-hidden /> {t("Gửi thương lại", "Send love back")}
            </button>
            {love ? (
              <button type="button" className={s.kLater} onClick={onClose} data-testid="kudos-close">
                <X aria-hidden /> {t("Đóng", "Close")}
              </button>
            ) : (
              <button type="button" className={s.kLater} onClick={onLater} data-testid="kudos-later">
                <Clock aria-hidden /> {t("Để sau", "Later")}
              </button>
            )}
          </div>
        </div>
      )}

      {stage === "speak" && (
        <div className={s.kActions}>
          {!typing && (
            <p className={s.kListening} role="status" data-on={listening}>
              <Mic aria-hidden />
              {interim || t(`Đang nghe… ${cap(elderLabel)} cứ nói tự nhiên nha.`, "Listening… just speak naturally.")}
            </p>
          )}
          {typing ? (
            <form
              className={s.kTyped}
              onSubmit={(e) => {
                e.preventDefault();
                if (answer.trim()) setStage("review");
              }}
            >
              <textarea
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                rows={3}
                placeholder={t("Gõ câu trả lời…", "Type the answer…")}
                aria-label={t("Câu trả lời", "Your answer")}
                data-testid="kudos-typed"
                autoFocus
              />
              <button type="submit" className={s.kPrimary} disabled={!answer.trim()} data-testid="kudos-typed-done">
                <Check aria-hidden /> {t("Xong", "Done")}
              </button>
            </form>
          ) : (
            <button type="button" className={s.kGhost} onClick={stopListening}>
              <Keyboard aria-hidden /> {t("Gõ chữ", "Type instead")}
            </button>
          )}
          <button type="button" className={s.kLater} onClick={() => setStage("ask")}>
            {t("Quay lại", "Back")}
          </button>
        </div>
      )}

      {stage === "review" && (
        <div className={s.kActions}>
          <div className={s.kSaid}>
            <p className={s.kSaidWho}>{t(`${cap(elderLabel)} nói:`, "You said:")}</p>
            <p className={s.kSaidText} data-testid="kudos-said">
              “{answer}”
            </p>
          </div>
          <button
            type="button"
            className={s.kPrimary}
            disabled={busy}
            onClick={() => answerWith({ text: answer }, { heart: false, text: sentTo }, "save")}
            data-testid="kudos-send-answer"
          >
            <Send aria-hidden /> {t(`Gửi cho ${who}`, `Send to ${card.sender_name}`)}
          </button>
          <button type="button" className={s.kGhost} onClick={() => void startSpeaking()}>
            <RotateCcw aria-hidden /> {typing ? t("Sửa lại", "Edit") : t("Nói lại", "Say it again")}
          </button>
        </div>
      )}

      {stage === "save" && (
        <div className={s.kActions}>
          <div className={s.kSaid}>
            <p className={s.kSaidWho}>{t(`${cap(elderLabel)} đã gửi ${who}:`, `You sent ${card.sender_name}:`)}</p>
            <p className={s.kSaidText}>“{answer}”</p>
          </div>
          <p className={s.kAsk} data-testid="kudos-save-ask">
            <BookHeart aria-hidden />
            {t(`Lưu lời ${me} dạy vào Sổ ký ức cho cả nhà cùng đọc?`, "Keep this advice in the memory book for the whole family?")}
          </p>
          <div className={s.kChoices} data-n={2}>
            <button
              type="button"
              className={s.kChoice}
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                await onSave(true);
                setBusy(false);
                setDoneMsg({ heart: false, text: t("Đã lưu vào Sổ ký ức. Cả nhà sẽ đọc được.", "Saved to the memory book.") });
                setStage("done");
              }}
              data-testid="kudos-save-yes"
            >
              {t("Lưu lại", "Keep it")}
            </button>
            <button
              type="button"
              className={s.kChoice}
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                await onSave(false);
                setBusy(false);
                setDoneMsg({ heart: false, text: t(`Dạ, con giữ riêng. Đã gửi cho ${who}.`, `Kept private. Sent to ${card.sender_name}.`) });
                setStage("done");
              }}
              data-testid="kudos-save-no"
            >
              {t("Thôi, giữ riêng", "Keep it private")}
            </button>
          </div>
        </div>
      )}

      {stage === "done" && (
        <div className={s.kDone} role="status" data-testid="kudos-done">
          <span className={s.kDoneIco} data-heart={doneMsg.heart}>
            {doneMsg.heart ? <Heart aria-hidden /> : <Check aria-hidden />}
          </span>
          <p>{doneMsg.text}</p>
        </div>
      )}
    </section>
  );
}
