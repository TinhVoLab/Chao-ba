"use client";
// One conversation with Út Thương from the elder screen, on the same call API as chaoba/server/static/call.html:
//   POST /api/calls -> loop { elder turn (mic | typed | simulated) -> POST /turns -> speak reply } -> POST /end
// The Chào Bà server only ever receives text and timings (start/end/pauses), never audio.
// Turn sources: `sim` (GET /simulate: hands-free rehearsal, stored as simulated, not scored), `typed` (keyboard), or
// the microphone (Web Speech STT + WebAudio VAD). If the mic or speech recognition is unavailable the session
// switches itself to typed mode and tells the UI.
// Optional voice engine: `engine: "gemini"` asks the server for the Gemini Live engine (server-side proxy, see
// geminiVoice.ts). If the server has no credentials, or the connection fails, the same call continues seamlessly on
// this browser pipeline and the UI shows a status note.
import { Listener, speechRecognitionCtor, type CapturedTurn } from "./listener";
import { Speaker, stopSpeech, wordCount } from "./speech";
import { PcmPlayer, startPcmCapture, voiceWsUrl, type LiveMsg, type VoiceInfo } from "./geminiVoice";

export type CallPhase =
  | "connecting"
  | "speaking" // Út Thương talking (TTS or caption pause)
  | "listening" // waiting for the elder's voice
  | "typing" // waiting for a typed answer
  | "simulating" // demo: scripted elder line
  | "thinking" // waiting for the server reply
  | "saving"
  | "ended"
  | "error";

export type Tier = "acute" | "non_acute" | "third_party" | null;

export interface Caption {
  id: number; // a caption with a known id is updated in place (live transcripts)
  who: "agent" | "elder";
  text: string;
  sim?: boolean;
  interim?: boolean;
}

export interface EngineState {
  engine: "gemini" | "browser";
  state: "idle" | "connecting" | "live" | "fallback";
  note?: string;
  model?: string;
}

export interface TurnReply {
  reply_text: string;
  phase: string;
  emergency: boolean;
  end_call: boolean;
  event: string | null;
  tier: Tier;
}

export interface EndResult {
  day?: number;
  rehearsal?: boolean;
  simulated?: boolean;
  today?: { date?: string; day?: number; calls?: number; label_vi?: string; label_en?: string };
  [k: string]: unknown;
}

export interface CallOptions {
  apiBase: string;
  elderId: string;
  sim?: boolean;
  tts?: boolean;
  typed?: boolean;
  fast?: boolean;
  engine?: "gemini" | "browser"; // voice engine requested (default: the server's CHAOBA_VOICE_ENGINE)
  mute?: boolean; // tests: never produce any sound (no TTS, no audio output; playback is only timed)
}

export interface CallEvents {
  phase: (p: CallPhase) => void;
  caption: (c: Caption) => void;
  interim: (text: string) => void;
  level: (v: number) => void;
  reply: (r: TurnReply) => void;
  typedMode: (on: boolean) => void;
  engine?: (e: EngineState) => void;
  ended: (r: { result: EndResult | null; error?: "opted_out" | "offline" | "save_failed"; emergency: boolean }) => void;
}

export class CallSession {
  private callId: string | null = null;
  private active = false;
  private ending = false;
  private t0 = 0;
  private clockOffset = 0;
  private captionId = 0;
  private emergency = false;
  private typed: boolean;
  private readonly speaker: Speaker;
  private readonly listener: Listener;
  private typedResolve: ((t: CapturedTurn) => void) | null = null;
  private typingStart: number | null = null;
  private liveAbort: (() => void) | null = null;
  private liveNext: (() => void) | null = null;
  private readonly onHide = () => {
    // Leaving or hiding the page silences Út Thương at once and ends the call.
    if (document.visibilityState !== "hidden") return;
    stopSpeech();
    void this.end({ beacon: true });
  };
  private readonly onPageHide = () => {
    stopSpeech();
    void this.end({ beacon: true });
  };

  constructor(
    private readonly opts: CallOptions,
    private readonly on: CallEvents,
  ) {
    const now = () => this.now();
    this.speaker = new Speaker({ enabled: opts.tts !== false && !opts.mute, fast: opts.fast, now });
    this.typed = !!opts.typed || !speechRecognitionCtor();
    this.listener = new Listener(now, {
      onLevel: (v) => this.on.level(v),
      onInterim: (t) => this.on.interim(t),
      onSttBroken: () => this.setTypedInternal(true),
      isActive: () => this.active && !this.ending,
    });
  }

  get isActive(): boolean {
    return this.active;
  }
  get typedMode(): boolean {
    return this.typed;
  }

  private now(): number {
    return (performance.now() - this.t0) / 1000 + this.clockOffset;
  }

  private async api<T>(path: string, init?: RequestInit): Promise<T> {
    const r = await fetch(this.opts.apiBase + path, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        "X-Actor": encodeURIComponent("elder:" + this.opts.elderId),
        "X-Role": "elder_self",
      },
    });
    if (!r.ok) throw Object.assign(new Error(`${path} ${r.status}`), { status: r.status });
    return (await r.json()) as T;
  }

  private caption(who: Caption["who"], text: string, sim?: boolean) {
    this.on.caption({ id: ++this.captionId, who, text, sim });
  }

  private setTypedInternal(on: boolean) {
    if (this.typed === on) return;
    this.typed = on;
    this.on.typedMode(on);
  }

  /** Switch between voice and typed answers (ignored while speech recognition is unavailable). */
  setTyped(on: boolean) {
    if (!on && (this.listener.sttBroken || !speechRecognitionCtor())) return;
    this.setTypedInternal(on);
    if (on) this.listener.cancelToTypedIfListening();
    else this.typedResolve?.({ text: "", start: 0, end: 0, pauses: [], toTyped: true });
    if (on) this.liveNext?.();
  }

  /** The elder started typing (start time of the typed turn). */
  typingStarted() {
    if (this.typingStart === null) this.typingStart = this.now();
  }

  submitTyped(text: string): boolean {
    const t = text.trim();
    if (!t || !this.typedResolve) return false;
    const end = this.now();
    const resolve = this.typedResolve;
    this.typedResolve = null;
    resolve({ text: t, start: this.typingStart ?? end - 2, end, pauses: [] });
    return true;
  }

  private typedTurn(): Promise<CapturedTurn> {
    this.typingStart = null;
    return new Promise((resolve) => {
      this.typedResolve = resolve;
    });
  }

  private async simulatedTurn(): Promise<CapturedTurn> {
    const line = await this.api<{ text: string; pauses: number[]; duration_sec?: number }>(
      `/api/calls/${this.callId}/simulate`,
    );
    this.caption("elder", line.text, true);
    const t = await this.speaker.speak(line.text, { rate: 0.85, pitch: 0.75 });
    const pauses = line.pauses ?? [];
    // Timings follow the server's calibration (the persona's own baseline), not the TTS voice.
    const dur = line.duration_sec || wordCount(line.text) / 3.8 + pauses.reduce((a, b) => a + b, 0);
    const start = t.spoken ? t.start : this.now() + 0.6;
    const end = start + dur;
    if (end > this.now()) this.clockOffset += end - this.now();
    return { text: line.text, start, end, pauses };
  }

  async start(): Promise<void> {
    if (this.active) return;
    this.active = true;
    this.ending = false;
    this.emergency = false;
    window.addEventListener("pagehide", this.onPageHide);
    document.addEventListener("visibilitychange", this.onHide);
    this.on.phase("connecting");
    stopSpeech();
    if (!this.opts.sim && !this.typed) {
      const ok = await this.listener.initMic();
      if (!ok) this.setTypedInternal(true);
    }
    this.t0 = performance.now();
    this.clockOffset = 0;
    let res: { call_id: string; greeting_text: string; voice?: VoiceInfo };
    try {
      res = await this.api("/api/calls", {
        method: "POST",
        body: JSON.stringify({
          elder_id: this.opts.elderId,
          channel: "web",
          simulated: !!this.opts.sim,
          ...(this.opts.engine ? { engine: this.opts.engine } : {}),
        }),
      });
    } catch (e) {
      const status = (e as { status?: number }).status;
      this.cleanup();
      this.on.ended({ result: null, error: status === 409 ? "opted_out" : "offline", emergency: false });
      return;
    }
    if (!this.active) return;
    this.callId = res.call_id;
    let greeted = false;
    if (res.voice?.engine === "gemini-live" && res.voice.ws) {
      const how = await this.runGemini(res.voice);
      if (how === "ended" || !this.active || this.ending) {
        await this.end();
        return;
      }
      greeted = how === "fallback-after-greeting";
    } else {
      this.on.engine?.({ engine: "browser", state: "idle", note: res.voice?.note_vi });
    }
    if (!greeted) {
      this.caption("agent", res.greeting_text);
      this.on.phase("speaking");
      await this.speaker.speak(res.greeting_text);
    }

    while (this.active && !this.ending) {
      let turn: CapturedTurn;
      try {
        if (this.opts.sim) {
          this.on.phase("simulating");
          turn = await this.simulatedTurn();
        } else if (this.typed) {
          this.on.phase("typing");
          turn = await this.typedTurn();
        } else {
          this.on.phase("listening");
          turn = await this.listener.listen();
        }
      } catch {
        break;
      }
      if (!this.active || this.ending) break;
      if (turn.toTyped) continue;
      if (!this.opts.sim && turn.text) this.caption("elder", turn.text);
      this.on.phase("thinking");
      let r: TurnReply;
      try {
        r = await this.api<TurnReply>(`/api/calls/${this.callId}/turns`, {
          method: "POST",
          body: JSON.stringify({
            text: turn.text,
            start: +(turn.start ?? 0).toFixed(2),
            end: +(turn.end ?? 0).toFixed(2),
            pauses: turn.pauses ?? [],
          }),
        });
      } catch {
        break;
      }
      if (!this.active || this.ending) break;
      if (r.emergency) this.emergency = true;
      this.on.reply(r);
      if (r.reply_text) {
        this.caption("agent", r.reply_text);
        this.on.phase("speaking");
        await this.speaker.speak(r.reply_text);
      }
      if (r.end_call) break;
    }
    await this.end();
  }

  /** Gemini Live engine: resolves "ended" (save via /end), "fallback" (browser voice from the greeting on) or
   *  "fallback-after-greeting" (continue the same call on the browser pipeline). */
  private runGemini(voice: VoiceInfo): Promise<"ended" | "fallback" | "fallback-after-greeting"> {
    this.on.engine?.({ engine: "gemini", state: "connecting", model: voice.model });
    this.on.phase("connecting");
    const muted = !!this.opts.mute || this.opts.tts === false;
    const player = new PcmPlayer(voice.output_rate ?? 24000, muted, this.opts.fast ? 8 : 1);
    const ws = new WebSocket(voiceWsUrl(this.opts.apiBase, voice.ws ?? ""));
    ws.binaryType = "arraybuffer";
    const send = (d: object | ArrayBuffer) => {
      if (ws.readyState !== WebSocket.OPEN) return;
      ws.send(d instanceof ArrayBuffer ? d : JSON.stringify(d));
    };
    const cap: Record<"agent" | "elder", number | null> = { agent: null, elder: null };
    let stopCapture: (() => void) | null = null;

    return new Promise((resolve) => {
      let ready = false;
      let greeted = false;
      let done = false;
      let busy = false;
      const finish = async (how: "ended" | "fallback", note?: string) => {
        if (done) return;
        done = true;
        this.liveAbort = null;
        this.liveNext = null;
        if (how === "fallback" && this.active && !this.ending) {
          this.on.engine?.({ engine: "browser", state: "fallback", note: note ?? "Mất kết nối Gemini Live – chuyển sang giọng trình duyệt" });
        }
        if (how === "ended") await player.drained(20000);
        stopCapture?.();
        this.listener.setVoiceMonitor(null);
        try {
          ws.close();
        } catch {
          /* ignore */
        }
        player.close();
        resolve(how === "ended" ? "ended" : greeted ? "fallback-after-greeting" : "fallback");
      };
      this.liveAbort = () => void finish("fallback");

      // After Út Thương has finished talking (playback drained): the elder's turn.
      const elderTurn = async () => {
        if (busy || done) return;
        busy = true;
        await player.drained(30000);
        busy = false;
        if (done || !this.active || this.ending) return;
        send({ type: "playback", state: "idle" });
        if (this.opts.sim) {
          this.on.phase("simulating");
          const line = await this.api<{ text: string; pauses: number[]; duration_sec?: number }>(`/api/calls/${this.callId}/simulate`);
          const t = await this.speaker.speak(line.text, { rate: 0.85, pitch: 0.75 });
          const pauses = line.pauses ?? [];
          const dur = line.duration_sec || wordCount(line.text) / 3.8 + pauses.reduce((a, b) => a + b, 0);
          const start = t.spoken ? t.start : this.now() + 0.6;
          const end = start + dur;
          if (end > this.now()) this.clockOffset += end - this.now();
          if (!done) send({ type: "text", text: line.text, start: +start.toFixed(2), end: +end.toFixed(2), pauses });
        } else if (this.typed) {
          this.on.phase("typing");
          const turn = await this.typedTurn();
          if (turn.text && !done) send({ type: "text", text: turn.text, start: +turn.start.toFixed(2), end: +turn.end.toFixed(2), pauses: [] });
          else if (turn.toTyped && !done) this.on.phase("listening");
        } else {
          this.on.phase("listening");
        }
      };
      this.liveNext = () => void elderTurn();

      ws.onmessage = async (ev: MessageEvent<string | ArrayBuffer>) => {
        if (typeof ev.data !== "string") {
          player.push(ev.data);
          if (!done) this.on.phase("speaking");
          return;
        }
        let m: LiveMsg;
        try {
          m = JSON.parse(ev.data) as LiveMsg;
        } catch {
          return;
        }
        switch (m.type) {
          case "ready": {
            ready = true;
            this.on.engine?.({ engine: "gemini", state: "live", model: m.model });
            const audio = this.listener.audio;
            if (!this.opts.sim && !this.typed && audio) {
              stopCapture = await startPcmCapture(audio, (f) => {
                if (!done) send(f);
              });
              if (stopCapture) this.listener.setVoiceMonitor((state, t) => send({ type: "vad", state, t }));
              else this.setTypedInternal(true);
            }
            break;
          }
          case "transcript": {
            if (!m.text) break;
            if (m.who === "agent") greeted = true;
            const id = cap[m.who] ?? ++this.captionId;
            this.on.caption({ id, who: m.who, text: m.text, sim: m.who === "elder" && !!this.opts.sim, interim: !m.final });
            cap[m.who] = m.final ? null : id;
            break;
          }
          case "interrupt":
            player.flush(); // barge-in or safety: Út Thương stops at once
            break;
          case "turn":
            if (m.emergency) this.emergency = true;
            this.on.reply({ reply_text: m.reply_text, phase: m.phase, emergency: m.emergency, end_call: m.end_call, event: m.event, tier: m.tier });
            break;
          case "agent_done":
            void elderTurn();
            break;
          case "say": // safety message in the browser's own voice (Gemini did not start it in time)
            this.on.caption({ id: ++this.captionId, who: "agent", text: m.text });
            await this.speaker.speak(m.text);
            break;
          case "ended":
            void finish("ended");
            break;
          case "fallback":
            void finish("fallback", m.note_vi);
            break;
          case "error":
            void finish("fallback");
            break;
        }
      };
      ws.onerror = () => void finish("fallback");
      ws.onclose = () => {
        if (!done) void finish("fallback", ready ? undefined : "Không kết nối được Gemini Live – dùng giọng trình duyệt");
      };
    });
  }

  /** Ends the call: speech stops at once, the mic is released, and the server computes the day's metrics. */
  async end(opts: { beacon?: boolean } = {}): Promise<void> {
    if (this.ending || !this.active) return;
    this.ending = true;
    this.liveAbort?.();
    stopSpeech();
    this.listener.cancel();
    this.listener.close();
    this.typedResolve?.({ text: "", start: 0, end: 0, pauses: [] });
    this.typedResolve = null;
    const id = this.callId;
    if (!id) {
      this.cleanup();
      this.on.ended({ result: null, emergency: this.emergency });
      return;
    }
    if (opts.beacon) {
      try {
        navigator.sendBeacon(`${this.opts.apiBase}/api/calls/${id}/end`);
      } catch {
        /* ignore */
      }
      this.cleanup();
      this.on.ended({ result: null, emergency: this.emergency });
      return;
    }
    this.on.phase("saving");
    let result: EndResult | null = null;
    let error: "save_failed" | undefined;
    try {
      result = await this.api<EndResult>(`/api/calls/${id}/end`, { method: "POST" });
    } catch {
      error = "save_failed";
    }
    this.cleanup();
    this.on.ended({ result, error, emergency: this.emergency });
  }

  private cleanup() {
    this.active = false;
    this.callId = null;
    stopSpeech();
    this.listener.close();
    window.removeEventListener("pagehide", this.onPageHide);
    document.removeEventListener("visibilitychange", this.onHide);
    this.on.phase("ended");
  }

  /** Hard stop without saving (component unmount). */
  dispose() {
    this.liveAbort?.();
    if (this.active && this.callId) {
      try {
        navigator.sendBeacon(`${this.opts.apiBase}/api/calls/${this.callId}/end`);
      } catch {
        /* ignore */
      }
    }
    this.ending = true;
    this.cleanup();
  }
}
