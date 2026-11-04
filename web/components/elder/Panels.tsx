"use client";
import { useEffect, useRef, useState } from "react";
import { ArrowLeft, Check, HeartHandshake, Mic, Phone, PhoneOff, RotateCcw } from "lucide-react";
import type { FamilyMember } from "@/lib/types";
import { Avatar } from "./Avatar";
import { Face } from "./Faces";
import { Portrait } from "./Portrait";
import type { Mood } from "./data";
import { pickRound, shuffledChoices } from "./games";
import { cap, elderCalls, useT } from "./util";
import s from "./classes";

function BackButton({ onClick }: { onClick: () => void }) {
  const t = useT();
  return (
    <button type="button" className={s.btnBack} onClick={onClick} data-testid="btn-home">
      <ArrowLeft aria-hidden /> {t("Về màn hình chính", "Back to home")}
    </button>
  );
}

/* ------------------------------------------------------------------ simulated video call */
export function VideoCallView({
  callee,
  elderLabel,
  fast,
  onConnected,
  onEnd,
}: {
  callee: FamilyMember;
  elderLabel: string;
  fast: boolean;
  onConnected: () => void;
  onEnd: (seconds: number) => void;
}) {
  const t = useT();
  const [connectedAt, setConnectedAt] = useState<number | null>(null);
  const [now, setNow] = useState(0);
  const connected = useRef(onConnected);
  useEffect(() => {
    connected.current = onConnected;
  });
  useEffect(() => {
    const id = setTimeout(() => {
      setConnectedAt(Date.now());
      connected.current();
    }, fast ? 300 : 2600);
    return () => clearTimeout(id);
  }, [fast]);
  useEffect(() => {
    if (connectedAt === null) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [connectedAt]);
  const secs = connectedAt && now ? Math.max(0, Math.round((now - connectedAt) / 1000)) : 0;
  const mmss = `${String(Math.floor(secs / 60)).padStart(2, "0")}:${String(secs % 60).padStart(2, "0")}`;
  return (
    <div className={s.video} data-testid="video-call">
      <div className={s.videoFeed}>
        <Portrait member={callee} id="vc" fit="meet" />
      </div>
      <div className={s.videoTop}>
        <span className={s.chipSolid}>{t("Mô phỏng cuộc gọi video", "Simulated video call")}</span>
        <p className={s.videoName}>{cap(elderCalls(callee))}</p>
        <p className={s.videoState} role="status" data-testid="video-state">
          {connectedAt ? t(`Đã kết nối · ${mmss}`, `Connected · ${mmss}`) : t("Đang gọi…", "Calling…")}
        </p>
      </div>
      <div className={s.videoSelf} aria-hidden>
        <span>{cap(elderLabel)}</span>
      </div>
      <button type="button" className={`${s.btnEnd} ${s.videoEnd}`} onClick={() => onEnd(secs)} data-testid="btn-video-end">
        <PhoneOff aria-hidden /> {t("Kết thúc", "End")}
      </button>
    </div>
  );
}

/* ------------------------------------------------------------------ mood check-in */
export function MoodView({
  elderLabel,
  calleeLabel,
  onPick,
  onTalk,
  onVideo,
  onHome,
}: {
  elderLabel: string;
  calleeLabel: string | null;
  onPick: (m: Mood) => void;
  onTalk: () => void;
  onVideo: () => void;
  onHome: () => void;
}) {
  const t = useT();
  const [picked, setPicked] = useState<Mood | null>(null);
  useEffect(() => {
    if (!picked || picked === "sad") return;
    const id = setTimeout(onHome, 3500);
    return () => clearTimeout(id);
  }, [picked, onHome]);
  const opts: [Mood, string, string][] = [
    ["happy", "Vui", "Happy"],
    ["neutral", "Bình thường", "Okay"],
    ["sad", "Buồn", "Sad"],
  ];
  if (picked) {
    return (
      <div className={s.panel}>
        <div className={s.panelCenter}>
          <span className={s.faceBig}>
            <Face mood={picked} />
          </span>
          <p className={s.panelTitle} role="status">
            {t(`Cảm ơn ${elderLabel}. Con đã ghi lại rồi.`, "Thank you. Noted.")}
          </p>
          {picked === "sad" && (
            <>
              <p className={s.panelBody}>{t(`${cap(elderLabel)} muốn nói chuyện một chút không?`, "Would you like to talk to someone?")}</p>
              <div className={s.stack}>
                <button type="button" className={s.btnTalk} onClick={onTalk}>
                  <Mic aria-hidden /> <span>{t("Nói chuyện với Út Thương", "Talk to Út Thương")}</span>
                </button>
                {calleeLabel && (
                  <button type="button" className={s.btnCall} onClick={onVideo}>
                    <Phone aria-hidden /> <span>{t(`Gọi ${calleeLabel}`, `Call ${calleeLabel}`)}</span>
                  </button>
                )}
              </div>
            </>
          )}
        </div>
        <BackButton onClick={onHome} />
      </div>
    );
  }
  return (
    <div className={s.panel}>
      <p className={s.panelTitle}>{t(`Hôm nay ${elderLabel} thấy trong người thế nào?`, "How are you feeling today?")}</p>
      <div className={s.moods}>
        {opts.map(([m, vi, en]) => (
          <button
            key={m}
            type="button"
            className={s.moodBtn}
            data-testid={`mood-${m}`}
            onClick={() => {
              setPicked(m);
              onPick(m);
            }}
          >
            <span className={s.moodFace}>
              <Face mood={m} />
            </span>
            <span>{t(vi, en)}</span>
          </button>
        ))}
      </div>
      <p className={s.panelNote}>{t("Chỉ để gia đình biết, không phải khám bệnh.", "Just for the family to know; not a medical test.")}</p>
      <BackButton onClick={onHome} />
    </div>
  );
}

/* ------------------------------------------------------------------ memory game: finish the ca dao */
export function GameView({
  elderLabel,
  seed,
  onPlay,
  onHome,
}: {
  elderLabel: string;
  seed: number;
  onPlay: (itemId: string, correct: boolean, choice: string) => void;
  onHome: () => void;
}) {
  const t = useT();
  const [round, setRound] = useState(0);
  const items = pickRound(seed + round);
  const [i, setI] = useState(0);
  const [choice, setChoice] = useState<string | null>(null);
  const done = i >= items.length;
  const item = items[Math.min(i, items.length - 1)];
  const choices = shuffledChoices(item, seed + i + round);

  if (done) {
    return (
      <div className={s.panel}>
        <div className={s.panelCenter}>
          <HeartHandshake className={s.bigIco} aria-hidden />
          <p className={s.panelTitle} role="status" data-testid="game-done">
            {t(`Hôm nay mình ôn được ${items.length} câu ca dao. Mai chơi tiếp nha ${elderLabel}!`, `We went through ${items.length} verses today. More tomorrow!`)}
          </p>
          <button
            type="button"
            className={s.btnTalk}
            onClick={() => {
              setRound((r) => r + 1);
              setI(0);
              setChoice(null);
            }}
          >
            <RotateCcw aria-hidden /> <span>{t("Chơi thêm", "Play more")}</span>
          </button>
        </div>
        <BackButton onClick={onHome} />
      </div>
    );
  }

  const right = choice === item.answer;
  return (
    <div className={s.panel}>
      <p className={s.panelKicker}>
        {t("Nhớ ca dao", "Finish the folk verse")} · {i + 1}/{items.length}
      </p>
      <div className={s.verse}>
        <p>{item.lead}</p>
        <p>
          {item.stem} <span className={s.blank}>{choice ? item.answer : "…"}</span>
        </p>
        {t("", item.en) && <p className={s.verseEn}>{item.en}</p>}
      </div>
      <div className={s.choices}>
        {choices.map((c) => (
          <button
            key={c}
            type="button"
            className={s.choice}
            data-state={choice ? (c === item.answer ? "answer" : c === choice ? "picked" : "dim") : undefined}
            disabled={!!choice}
            onClick={() => {
              setChoice(c);
              onPlay(item.id, c === item.answer, c);
            }}
            data-testid="game-choice"
          >
            {choice && c === item.answer && <Check aria-hidden />}
            {c}
          </button>
        ))}
      </div>
      <p className={s.feedback} role="status" data-testid="game-feedback">
        {choice
          ? right
            ? t(`Đúng rồi! ${cap(elderLabel)} nhớ giỏi quá.`, "That's it! Well remembered.")
            : t(`Câu đó là “${item.answer}”. ${cap(elderLabel)} nghe quen không?`, `It goes “${item.answer}”. Sound familiar?`)
          : " "}
      </p>
      {choice ? (
        <button
          type="button"
          className={s.btnTalk}
          onClick={() => {
            setI((x) => x + 1);
            setChoice(null);
          }}
          data-testid="game-next"
        >
          <span>{i + 1 < items.length ? t("Câu tiếp theo", "Next verse") : t("Xong", "Done")}</span>
        </button>
      ) : (
        <BackButton onClick={onHome} />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ emergency (acute tier) */
export function EmergencyView({
  reply,
  familyAgent,
  onClose,
  title,
}: {
  reply: string;
  familyAgent: string | null;
  onClose: () => void;
  /** Overrides the "family alerted" title (e.g. the Help button while sending or offline). */
  title?: string;
}) {
  const t = useT();
  return (
    <div className={s.emergency} role="alertdialog" aria-labelledby="em-title" data-testid="emergency">
      <p id="em-title" className={s.emTitle}>
        {title ?? (familyAgent ? t(`Đã báo cho ${familyAgent}`, `${cap(familyAgent)} has been alerted`) : t("Đã báo cho gia đình", "Family alerted"))}
      </p>
      <p className={s.emBody}>{t("Nếu thấy nguy cấp, hãy gọi 115 ngay.", "If this is urgent, call 115 now.")}</p>
      <a className={s.btn115} href="tel:115" data-testid="call-115">
        <Phone aria-hidden /> {t("Gọi 115", "Call 115")}
      </a>
      {reply && (
        <div className={s.emReply}>
          <Avatar state="idle" className={s.avatarSmall} />
          <p>{reply}</p>
        </div>
      )}
      <button type="button" className={s.btnEmClose} onClick={onClose}>
        {t("Đóng", "Close")}
      </button>
    </div>
  );
}

/* ------------------------------------------------------------------ help button: confirm with a countdown */
export const HELP_COUNTDOWN = 10;

/** "Cần giúp": sends on its own after the countdown, so a person who cannot tap again is still heard;
 * one tap on "bấm nhầm" cancels a stray press. */
export function HelpConfirmView({ elderLabel, onSend, onCancel }: { elderLabel: string; onSend: () => void; onCancel: () => void }) {
  const t = useT();
  const [left, setLeft] = useState(HELP_COUNTDOWN);
  const sent = useRef(false);
  useEffect(() => {
    const id = setInterval(() => setLeft((n) => Math.max(0, n - 1)), 1000);
    return () => clearInterval(id);
  }, []);
  useEffect(() => {
    if (left === 0 && !sent.current) {
      sent.current = true;
      onSend();
    }
  }, [left, onSend]);
  const send = () => {
    if (sent.current) return;
    sent.current = true;
    onSend();
  };
  return (
    <div className={s.emergency} role="alertdialog" aria-labelledby="help-title" aria-describedby="help-body" data-testid="help-confirm">
      <p id="help-title" className={s.emTitle}>
        {t(`${cap(elderLabel)} cần giúp phải không?`, "Do you need help?")}
      </p>
      <p id="help-body" className={s.emBody} aria-live="polite">
        {t(`Út Thương sẽ báo cả nhà sau ${left} giây.`, `Út Thương will alert the family in ${left} seconds.`)}
      </p>
      <button type="button" className={s.btn115} onClick={send} data-testid="help-send">
        {t("Báo cả nhà ngay", "Alert the family now")}
      </button>
      <button type="button" className={s.btnEmClose} onClick={onCancel} data-testid="help-cancel">
        {t("Không, bấm nhầm", "No, pressed by mistake")}
      </button>
    </div>
  );
}

/* ------------------------------------------------------------------ after-call / notices */
export function NoticeView({ title, body, onHome, auto }: { title: string; body?: string; onHome: () => void; auto?: number }) {
  useEffect(() => {
    if (!auto) return;
    const id = setTimeout(onHome, auto);
    return () => clearTimeout(id);
  }, [auto, onHome]);
  return (
    <div className={s.panel}>
      <div className={s.panelCenter}>
        <Avatar state="idle" className={s.avatarMid} />
        <p className={s.panelTitle} role="status" data-testid="notice">
          {title}
        </p>
        {body && <p className={s.panelBody}>{body}</p>}
      </div>
      <BackButton onClick={onHome} />
    </div>
  );
}
