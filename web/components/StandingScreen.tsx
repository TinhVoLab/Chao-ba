"use client";
// The elder's always-on 9:16 home screen (Gói màn hình đứng): idle clock + family photos + today's reminders,
// a real voice conversation with Út Thương, a simulated video call to the family, medication confirmation,
// a once-a-day mood check-in and a gentle ca dao memory game. See components/elder/*.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ElderProfile, FamilyMember, Note } from "@/lib/types";
import type { Kudos } from "@/lib/kudos";
import type { TurnReply } from "@/lib/voice/callSession";
import { stopSpeech } from "@/lib/voice/speech";
import { IdleView } from "./elder/IdleView";
import { TalkView, type TalkEnd } from "./elder/TalkView";
import { EmergencyView, GameView, HelpConfirmView, MoodView, NoticeView, VideoCallView } from "./elder/Panels";
import { KudosCard, type KudosAnswer } from "./elder/KudosCard";
import {
  fetchKudosInbox,
  fetchScreen,
  fetchTogether,
  flushElderOutbox,
  localDay,
  postElder,
  saveLocalDay,
  type MedToday,
  type Mood,
  type ScreenBundle,
  type ScreenMessage,
  type Together,
} from "./elder/data";
import { LangCtx, addressElder, agentCalls, callTarget, cap, elderCalls, type ScreenLang } from "./elder/util";
import s from "./elder/classes";

export interface ScreenFlags {
  lang: ScreenLang;
  sim: boolean;
  tts: boolean;
  typed: boolean;
  fast: boolean;
  engine?: "gemini" | "browser"; // ?engine= voice engine (default: server's CHAOBA_VOICE_ENGINE)
  mute?: boolean; // ?mute=1 tests: no sound at all
}

type Mode = "idle" | "talk" | "video" | "mood" | "game" | "notice" | "help";

function medsFromProfile(p: ElderProfile, local: Record<string, MedToday["status"]> | null): MedToday[] {
  return (p.medications ?? []).map((m) => ({
    name: m.name,
    time: m.time,
    timed: /^\d{1,2}:\d{2}$/.test(m.time),
    status: local?.[m.name] ?? null,
    answered_at: null,
  }));
}

export function StandingScreen({
  profile,
  notes,
  live,
  apiBase,
  flags,
}: {
  profile: ElderProfile;
  notes: Note[];
  live: boolean;
  apiBase: string;
  flags: ScreenFlags;
}) {
  const L = (vi: string, en: string) => (flags.lang === "en" ? en : vi);
  const elderId = profile.id;
  const callee = callTarget(profile);
  const elderLabel = addressElder(profile);
  const fallbackMessages: ScreenMessage[] = useMemo(
    () => notes.filter((n) => n.to_elder).slice(0, 3).map((n) => ({ id: n.id, author: n.author, text: n.text, date: n.date })),
    [notes],
  );

  const [mode, setMode] = useState<Mode>("idle");
  const [bundle, setBundle] = useState<ScreenBundle | null>(null);
  const [online, setOnline] = useState(live);
  const [meds, setMeds] = useState<MedToday[]>(() => medsFromProfile(profile, null));
  const [mood, setMood] = useState<Mood | null>(null);
  const [emergency, setEmergency] = useState<string | null>(null);
  const [emergencyTitle, setEmergencyTitle] = useState<string | undefined>(undefined);
  const [notice, setNotice] = useState<{ title: string; body?: string } | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [gameSeed, setGameSeed] = useState(0);
  // Family love notes ("Gửi yêu thương"): a queue shown one at a time on the idle screen, never during a conversation.
  const [inbox, setInbox] = useState<Kudos[]>([]);
  const [handled, setHandled] = useState<number[]>([]);
  const seenRef = useRef<Set<number>>(new Set());
  const queue = inbox.filter((k) => !handled.includes(k.id));
  const card = mode === "idle" && emergency === null ? queue[0] ?? null : null;
  // The card on screen stays until the elder is done with it, even once a refresh no longer lists it (answered,
  // then "Lưu vào Sổ ký ức?" can take longer than one poll).
  const shownRef = useRef<number | null>(null);
  useEffect(() => {
    shownRef.current = card?.id ?? null;
  }, [card]);

  // "Cả nhà ghé thăm": today's visitors, the family photo wall and the family moment, refreshed with the inbox.
  const [together, setTogether] = useState<Together | null>(null);
  const loadInbox = useCallback(async () => {
    const [items, tg] = await Promise.all([fetchKudosInbox(apiBase, elderId), fetchTogether(apiBase, elderId)]);
    if (items)
      setInbox((prev) => {
        const keep = prev.find((k) => k.id === shownRef.current && !items.some((i) => i.id === k.id));
        return keep ? [keep, ...items] : items;
      });
    if (tg) setTogether(tg);
  }, [apiBase, elderId]);

  useEffect(() => {
    const first = setTimeout(() => void loadInbox(), 0);
    const id = setInterval(() => void loadInbox(), flags.fast ? 3000 : 10_000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [loadInbox, flags.fast]);

  // The card on screen counts as seen ("Má đã xem" for the family), once.
  useEffect(() => {
    if (!card || seenRef.current.has(card.id) || card.status !== "sent") return;
    seenRef.current.add(card.id);
    void postElder(apiBase, elderId, `kudos/${card.id}/seen`, { via: "screen" });
  }, [card, apiBase, elderId]);

  const refresh = useCallback(async () => {
    await flushElderOutbox();
    const b = await fetchScreen(apiBase, elderId);
    if (b) {
      setBundle(b);
      setOnline(true);
      setMeds(b.medications.map((m) => ({ ...m, status: m.status as MedToday["status"] })));
      setMood(b.mood_today?.mood ?? null);
    } else {
      setOnline(false);
      setMeds(medsFromProfile(profile, localDay(elderId, "meds")));
      setMood(localDay<Mood>(elderId, "mood"));
    }
  }, [apiBase, elderId, profile]);

  useEffect(() => {
    // Initial load + a gentle refresh every 2 minutes (new family messages, the day rolling over).
    const first = setTimeout(() => void refresh(), 0);
    const id = setInterval(() => void refresh(), 120_000);
    const onOnline = () => void refresh();
    window.addEventListener("online", onOnline);
    return () => {
      clearTimeout(first);
      clearInterval(id);
      window.removeEventListener("online", onOnline);
    };
  }, [refresh]);

  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(null), 6000);
    return () => clearTimeout(id);
  }, [toast]);

  // Safety: nothing may keep talking once the page is hidden or left.
  useEffect(() => {
    const stop = () => stopSpeech();
    const vis = () => document.visibilityState === "hidden" && stopSpeech();
    window.addEventListener("pagehide", stop);
    document.addEventListener("visibilitychange", vis);
    return () => {
      stopSpeech();
      window.removeEventListener("pagehide", stop);
      document.removeEventListener("visibilitychange", vis);
    };
  }, []);

  const home = useCallback(() => {
    setMode("idle");
    setNotice(null);
    void refresh();
  }, [refresh]);

  // A panel left open (game, mood) slips back to the clock and family photos after 3 quiet minutes. Conversations,
  // calls, love cards and the emergency screen are never cut off this way.
  const screenRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (mode !== "mood" && mode !== "game") return;
    const el = screenRef.current;
    let id = setTimeout(home, 180_000);
    const poke = () => {
      clearTimeout(id);
      id = setTimeout(home, 180_000);
    };
    el?.addEventListener("pointerdown", poke);
    return () => {
      clearTimeout(id);
      el?.removeEventListener("pointerdown", poke);
    };
  }, [mode, home]);

  const saved = (r: "saved" | "queued" | "refused") =>
    r === "queued" ? L(" (lưu trên máy, sẽ gửi khi có mạng)", " (kept on this device; will send when online)") : "";

  async function onMed(m: MedToday, status: "taken" | "not_yet") {
    const at = new Date().toISOString();
    setMeds((xs) => xs.map((x) => (x.name === m.name ? { ...x, status, answered_at: at } : x)));
    const local = { ...(localDay<Record<string, MedToday["status"]>>(elderId, "meds") ?? {}), [m.name]: status };
    saveLocalDay(elderId, "meds", local);
    const r = await postElder(apiBase, elderId, "medication_log", { status, medication: m.name, time: m.time });
    setToast(
      (status === "taken"
        ? L(`Đã ghi: ${elderLabel} đã uống thuốc.`, "Noted: medicine taken.")
        : L("Út Thương sẽ nhắc lại sau nha.", "Út Thương will remind you later.")) + saved(r),
    );
  }

  async function onMood(m: Mood) {
    setMood(m);
    saveLocalDay(elderId, "mood", m);
    await postElder(apiBase, elderId, "mood_checkin", { mood: m });
  }

  async function onHelpSend() {
    setMode("idle");
    setEmergencyTitle(L("Đang báo cả nhà…", "Alerting the family…"));
    setEmergency(" ");
    const r = await postElder(apiBase, elderId, "help", { pressed_at: new Date().toISOString() });
    if (r === "saved") {
      setEmergencyTitle(undefined);
      setEmergency(L(`Út Thương đã báo cả nhà rồi. ${cap(elderLabel)} ngồi yên chờ nha, sẽ có người gọi liền.`, "The family has been alerted. Stay where you are; someone will call soon."));
    } else {
      setEmergencyTitle(L("Chưa báo được cả nhà", "Could not alert the family"));
      setEmergency(
        r === "queued"
          ? L("Đang mất mạng; Út Thương sẽ tự gửi khi có mạng lại. Hãy gọi 115 hoặc nhờ hàng xóm.", "No connection; it will send when the connection is back. Call 115 or ask a neighbour.")
          : L("Hãy gọi 115 hoặc nhờ hàng xóm.", "Call 115 or ask a neighbour."),
      );
    }
  }

  function onReply(r: TurnReply) {
    if (r.emergency || r.tier === "acute") setEmergency(r.reply_text || " ");
  }

  function onTalkEnded(e: TalkEnd) {
    if (e.error === "opted_out") {
      setNotice({
        title: L(`${cap(elderLabel)} đã tạm ngưng trò chuyện hằng ngày.`, "Daily calls are paused."),
        body: L("Gia đình có thể bật lại trong ứng dụng.", "The family can turn them back on in the app."),
      });
    } else if (e.error === "offline") {
      setNotice({
        title: L("Út Thương chưa kết nối được.", "Út Thương can't connect right now."),
        body: L(`${cap(elderLabel)} thử lại sau một chút nha.`, "Please try again in a little while."),
      });
    } else {
      setNotice({
        title: L(`Cảm ơn ${elderLabel} đã trò chuyện!`, "Thank you for the chat!"),
        body: L("Hẹn gặp lại sáng mai nha.", "Talk again tomorrow morning."),
      });
    }
    setMode("notice");
  }

  async function onVideoConnected() {
    if (!callee) return;
    await postElder(apiBase, elderId, "contacts", { kind: "call", member_id: callee.id, member_name: callee.name });
  }

  const flagsTalk = { sim: flags.sim, tts: flags.tts, typed: flags.typed, fast: flags.fast, engine: flags.engine, mute: flags.mute };

  function senderOf(k: Kudos): FamilyMember {
    const f = (profile.family ?? []).find((m) => m.id === k.sender_id);
    return f ?? ({ id: k.sender_id ?? k.sender_name, name: k.sender_name, relation: k.sender_relation ?? "daughter", role: "secondary" } as FamilyMember);
  }
  const doneWith = (id: number) => setHandled((h) => (h.includes(id) ? h : [...h, id]));
  async function kudosAnswer(k: Kudos, a: KudosAnswer) {
    await postElder(apiBase, elderId, `kudos/${k.id}/reply`, { ...a, via: "screen" });
  }

  return (
    <LangCtx.Provider value={flags.lang}>
      <div ref={screenRef} className={s.screen} lang={flags.lang} data-mode={mode} data-online={online} data-testid="elder-screen">
        {mode === "idle" && (
          <IdleView
            profile={profile}
            messages={bundle ? bundle.messages : fallbackMessages}
            meds={meds}
            mood={mood}
            callee={callee}
            toast={toast}
            together={together}
            onPhotoHeart={(id) => {
              const from = together?.photos.find((x) => x.id === id)?.sender_name;
              if (from) setToast(L(`Đã gửi thương cho ${from}`, `Love sent to ${from}`));
              setTogether((t) => (t ? { ...t, photos: t.photos.map((x) => (x.id === id ? { ...x, hearted: true } : x)) } : t));
              void postElder(apiBase, elderId, `photos/${id}/heart`, {});
            }}
            onFamilyHeart={() => {
              setTogether((t) => (t ? { ...t, moment: { ...t.moment, hearted: true } } : t));
              setToast(L("Đã gửi thương tới cả nhà", "Love sent to the whole family"));
              void postElder(apiBase, elderId, "together/heart", {});
            }}
            onMed={onMed}
            onTalk={() => setMode("talk")}
            onVideo={() => setMode("video")}
            onMood={() => setMode("mood")}
            onHelp={() => setMode("help")}
            onGame={() => {
              setGameSeed((x) => x + 1 + new Date().getDate());
              setMode("game");
            }}
          />
        )}
        {card && (
          <KudosCard
            key={card.id}
            card={card}
            member={senderOf(card)}
            index={0}
            total={queue.length}
            elderLabel={elderLabel}
            typed={flags.typed}
            onAnswer={(a) => kudosAnswer(card, a)}
            onLater={() => {
              doneWith(card.id);
              void postElder(apiBase, elderId, `kudos/${card.id}/seen`, { via: "screen", snooze_minutes: 120 });
            }}
            onClose={() => doneWith(card.id)}
            onSave={async (agree) => {
              await postElder(apiBase, elderId, `kudos/${card.id}/save`, agree ? {} : { decline: true });
            }}
            onDone={() => {
              doneWith(card.id);
              void loadInbox();
            }}
          />
        )}
        {mode === "talk" && (
          <TalkView
            apiBase={apiBase}
            elderId={elderId}
            elderLabel={elderLabel}
            calleeAgent={callee ? agentCalls(callee) : null}
            flags={flagsTalk}
            onReply={onReply}
            onEnded={onTalkEnded}
          />
        )}
        {mode === "video" && callee && (
          <VideoCallView
            callee={callee}
            elderLabel={elderLabel}
            fast={flags.fast}
            onConnected={onVideoConnected}
            onEnd={(secs) => {
              setToast(L(`Đã gọi ${elderCalls(callee)}${secs >= 60 ? ` · ${Math.round(secs / 60)} phút` : ""}.`, `Called ${callee.name}.`));
              home();
            }}
          />
        )}
        {mode === "mood" && (
          <MoodView
            elderLabel={elderLabel}
            calleeLabel={callee ? elderCalls(callee) : null}
            onPick={onMood}
            onTalk={() => setMode("talk")}
            onVideo={() => setMode("video")}
            onHome={home}
          />
        )}
        {mode === "game" && (
          <GameView
            elderLabel={elderLabel}
            seed={gameSeed}
            onPlay={(item_id, correct, choice) => void postElder(apiBase, elderId, "game_plays", { game: "ca_dao", item_id, correct, choice })}
            onHome={home}
          />
        )}
        {mode === "help" && <HelpConfirmView elderLabel={elderLabel} onSend={onHelpSend} onCancel={home} />}
        {mode === "notice" && notice && <NoticeView title={notice.title} body={notice.body} onHome={home} auto={20_000} />}
        {emergency !== null && (
          <EmergencyView
            reply={emergency.trim()}
            title={emergencyTitle}
            familyAgent={callee ? agentCalls(callee) : null}
            onClose={() => {
              setEmergency(null);
              setEmergencyTitle(undefined);
            }}
          />
        )}
        <p className={s.footer}>
          {L("Dữ liệu mô phỏng", "Simulated data")} · {L("Không lưu ghi âm", "No audio stored")}
          {!online && <> · {L("Đang ngoại tuyến", "Offline")}</>}
        </p>
      </div>
    </LangCtx.Provider>
  );
}
