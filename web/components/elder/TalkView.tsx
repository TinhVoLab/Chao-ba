"use client";
import { useEffect, useRef, useState } from "react";
import { Keyboard, Mic, PhoneOff, Send } from "lucide-react";
import { CallSession, type CallPhase, type Caption, type EndResult, type TurnReply } from "@/lib/voice/callSession";
import { Avatar, type AvatarState } from "./Avatar";
import { cap, useT } from "./util";
import s from "./classes";

export interface TalkEnd {
  result: EndResult | null;
  error?: "opted_out" | "offline" | "save_failed";
  emergency: boolean;
}

export function TalkView({
  apiBase,
  elderId,
  elderLabel,
  calleeAgent,
  flags,
  onReply,
  onEnded,
}: {
  apiBase: string;
  elderId: string;
  elderLabel: string; // "bà Hạnh"
  calleeAgent: string | null; // "chị Lan"
  flags: { sim: boolean; tts: boolean; typed: boolean; fast: boolean };
  onReply: (r: TurnReply) => void;
  onEnded: (e: TalkEnd) => void;
}) {
  const t = useT();
  const [phase, setPhase] = useState<CallPhase>("connecting");
  const [captions, setCaptions] = useState<Caption[]>([]);
  const [interim, setInterim] = useState("");
  const [typedMode, setTypedMode] = useState(flags.typed);
  const [concern, setConcern] = useState(false);
  const [draft, setDraft] = useState("");
  const avatarRef = useRef<HTMLDivElement>(null);
  const sessionRef = useRef<CallSession | null>(null);
  const disposeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const cb = useRef({ onReply, onEnded });
  useEffect(() => {
    cb.current = { onReply, onEnded };
  });

  useEffect(() => {
    // StrictMode runs effects twice in development: keep one session and cancel the pending dispose on re-run.
    if (disposeTimer.current) {
      clearTimeout(disposeTimer.current);
      disposeTimer.current = null;
    }
    if (!sessionRef.current) {
      const session = new CallSession(
        { apiBase, elderId, sim: flags.sim, tts: flags.tts, typed: flags.typed, fast: flags.fast },
        {
          phase: setPhase,
          caption: (c) => setCaptions((cs) => [...cs.slice(-5), c]),
          interim: setInterim,
          level: (v) => avatarRef.current?.style.setProperty("--lvl", v.toFixed(3)),
          reply: (r) => {
            if (r.tier === "non_acute") setConcern(true);
            cb.current.onReply(r);
          },
          typedMode: setTypedMode,
          ended: (e) => cb.current.onEnded(e),
        },
      );
      sessionRef.current = session;
      setTypedMode(session.typedMode);
      void session.start();
    }
    return () => {
      disposeTimer.current = setTimeout(() => {
        sessionRef.current?.dispose();
        sessionRef.current = null;
      }, 0);
    };
  }, [apiBase, elderId, flags.sim, flags.tts, flags.typed, flags.fast]);

  const avatarState: AvatarState =
    phase === "speaking" ? "speaking" : phase === "listening" || phase === "typing" ? "listening" : phase === "thinking" || phase === "connecting" || phase === "saving" ? "thinking" : "idle";

  const status: Record<CallPhase, string> = {
    connecting: t("Đang kết nối…", "Connecting…"),
    speaking: t("Út Thương đang nói…", "Út Thương is speaking…"),
    listening: t("Đang nghe…", "Listening…"),
    typing: t(`Mời ${elderLabel} gõ câu trả lời`, "Type your answer"),
    simulating: t("Giả lập người nói (diễn tập)", "Simulated speaker (rehearsal)"),
    thinking: t("Út Thương đang nghĩ…", "Út Thương is thinking…"),
    saving: t("Đang lưu… (không lưu ghi âm)", "Saving… (no audio is kept)"),
    ended: t("Đã kết thúc", "Call ended"),
    error: t("Có lỗi", "Error"),
  };

  const shown = captions.slice(-3);
  const send = () => {
    if (sessionRef.current?.submitTyped(draft)) setDraft("");
  };

  return (
    <div className={s.talk}>
      <header className={s.talkTop}>
        <p className={s.talkTitle}>{t("Trò chuyện với Út Thương", "Talking with Út Thương")}</p>
        {flags.sim && <span className={s.chip}>{t("Diễn tập · giả lập", "Rehearsal · simulated")}</span>}
      </header>

      <div className={s.talkStage}>
        <Avatar ref={avatarRef} state={avatarState} className={s.avatarBig} label={status[phase]} />
        <p className={s.status} data-phase={phase} role="status" data-testid="talk-status">
          {phase === "listening" && <Mic aria-hidden />}
          {status[phase]}
        </p>
      </div>

      {concern && calleeAgent && (
        <p className={s.concern} role="status">
          {t(`Út Thương đã nhắn ${calleeAgent} gọi hỏi thăm ${elderLabel} hôm nay.`, `Út Thương asked ${calleeAgent} to check in today.`)}
        </p>
      )}

      <div className={s.captions} aria-live="polite" data-testid="captions">
        {shown.map((c, i) => (
          <div key={c.id} className={s.cap} data-who={c.who} data-old={i < shown.length - 1 && shown.length > 1}>
            <span className={s.capWho}>{c.who === "agent" ? "Út Thương" : cap(elderLabel) + (c.sim ? t(" (giả lập)", " (simulated)") : "")}</span>
            <span className={s.capText}>{c.text}</span>
          </div>
        ))}
        {interim && (
          <div className={s.cap} data-who="elder" data-interim>
            <span className={s.capWho}>{cap(elderLabel)}</span>
            <span className={s.capText}>{interim}</span>
          </div>
        )}
      </div>

      {typedMode && !flags.sim && (
        <form
          className={s.typed}
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
        >
          <input
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
              sessionRef.current?.typingStarted();
            }}
            placeholder={t("Gõ câu trả lời…", "Type your answer…")}
            aria-label={t("Câu trả lời", "Your answer")}
            autoComplete="off"
            enterKeyHint="send"
            disabled={phase !== "typing"}
            data-testid="typed-input"
          />
          <button type="submit" className={s.btnSend} disabled={phase !== "typing" || !draft.trim()}>
            <Send aria-hidden /> {t("Gửi", "Send")}
          </button>
        </form>
      )}

      <div className={s.talkBtns}>
        {!flags.sim && (
          <button
            type="button"
            className={s.btnGhost}
            onClick={() => {
              const next = !typedMode;
              sessionRef.current?.setTyped(next);
              setTypedMode(sessionRef.current?.typedMode ?? next);
            }}
          >
            {typedMode ? <Mic aria-hidden /> : <Keyboard aria-hidden />}
            {typedMode ? t("Nói", "Speak") : t("Gõ chữ", "Type")}
          </button>
        )}
        <button
          type="button"
          className={s.btnEnd}
          onClick={() => void sessionRef.current?.end()}
          disabled={phase === "saving" || phase === "ended"}
          data-testid="btn-end"
        >
          <PhoneOff aria-hidden /> {t("Kết thúc", "End")}
        </button>
      </div>
    </div>
  );
}
