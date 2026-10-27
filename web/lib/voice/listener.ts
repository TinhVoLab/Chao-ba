"use client";
// Microphone turn capture for the elder screen, ported from chaoba/server/static/call.html:
//  - WebAudio energy VAD (analyser only, nothing is recorded or uploaded) gives utterance start/end and pauses;
//  - Web Speech API (vi-VN, continuous, interim results) gives the words.
// End of turn: >= 1.5 s of VAD silence after speech AND recognised text (or 4.5 s with any text); 20 s of nothing =
// an empty (silent) turn. Without a mic analyser, STT result timing alone ends the turn.

export interface CapturedTurn {
  text: string;
  start: number;
  end: number;
  pauses: number[];
  toTyped?: boolean;
}

type SRCtor = new () => SpeechRecognitionLike;
interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((ev: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null;
  onend: (() => void) | null;
  onerror: ((ev: { error: string }) => void) | null;
  start(): void;
  abort(): void;
}

export function speechRecognitionCtor(): SRCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: SRCtor; webkitSpeechRecognition?: SRCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

const FATAL = ["not-allowed", "service-not-allowed", "network", "audio-capture", "language-not-supported"];

export class Listener {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private an: AnalyserNode | null = null;
  private buf: Float32Array<ArrayBuffer> | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;
  private floor = 0.006;
  private listening = false;
  private uttStart: number | null = null;
  private lastVoice: number | null = null;
  private silenceStart: number | null = null;
  private pauses: number[] = [];
  private voicedFrames = 0;
  private onVadTick: ((t: number) => void) | null = null;
  private rec: SpeechRecognitionLike | null = null;
  private cancelFn: (() => void) | null = null;
  private toTypedFn: (() => void) | null = null;
  sttBroken = false;

  constructor(
    private readonly now: () => number,
    private readonly hooks: {
      onLevel?: (level: number) => void;
      onInterim?: (text: string) => void;
      onSttBroken?: () => void;
      isActive: () => boolean;
    },
  ) {}

  get hasMic(): boolean {
    return !!this.an;
  }

  async initMic(): Promise<boolean> {
    if (this.an) return true;
    try {
      if (!navigator.mediaDevices?.getUserMedia) return false;
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      this.ctx = new AC();
      const src = this.ctx.createMediaStreamSource(this.stream);
      this.an = this.ctx.createAnalyser();
      this.an.fftSize = 1024;
      this.buf = new Float32Array(new ArrayBuffer(this.an.fftSize * 4));
      src.connect(this.an); // analyser only: nothing is recorded or uploaded
      this.timer = setInterval(() => this.tick(), 30);
      if (this.ctx.state === "suspended") await this.ctx.resume().catch(() => undefined);
      return true;
    } catch (e) {
      console.warn("mic unavailable", e);
      return false;
    }
  }

  /** Releases the microphone (the browser's recording indicator turns off). */
  close(): void {
    this.listening = false;
    try {
      this.rec?.abort();
    } catch {
      /* ignore */
    }
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.ctx?.close().catch(() => undefined);
    this.ctx = null;
    this.an = null;
    this.hooks.onLevel?.(0);
  }

  private tick() {
    if (!this.an || !this.buf) return;
    this.an.getFloatTimeDomainData(this.buf);
    let s = 0;
    for (let i = 0; i < this.buf.length; i++) s += this.buf[i] * this.buf[i];
    const rms = Math.sqrt(s / this.buf.length);
    const thr = Math.max(0.012, this.floor * 2.8);
    const voiced = rms > thr;
    this.hooks.onLevel?.(Math.min(1, rms / 0.12));
    if (!voiced) this.floor = this.floor * 0.97 + rms * 0.03;
    if (!this.listening) return;
    const t = this.now();
    if (voiced) {
      this.voicedFrames++;
      if (this.uttStart === null && this.voicedFrames >= 3) this.uttStart = t - 0.09;
      if (this.silenceStart !== null && this.uttStart !== null) {
        const gap = t - this.silenceStart;
        if (gap >= 0.4) this.pauses.push(+gap.toFixed(2)); // server counts 0.4-3 s gaps as pauses
      }
      this.silenceStart = null;
      this.lastVoice = t;
    } else {
      this.voicedFrames = 0;
      if (this.uttStart !== null && this.silenceStart === null) this.silenceStart = t;
      this.onVadTick?.(t);
    }
  }

  cancel(): void {
    this.cancelFn?.();
  }

  /** Stop listening and hand the turn to the keyboard (the elder chose "Gõ chữ"). */
  cancelToTypedIfListening(): void {
    if (this.listening) this.toTypedFn?.();
  }

  /** Captures one elder turn. Resolves `{toTyped: true}` when speech recognition turns out to be unavailable. */
  listen(): Promise<CapturedTurn> {
    const SR = speechRecognitionCtor();
    return new Promise((resolve) => {
      let finalText = "";
      let interimText = "";
      let lastResultAt = 0;
      const listenStarted = this.now();
      this.uttStart = null;
      this.lastVoice = null;
      this.silenceStart = null;
      this.pauses = [];
      this.voicedFrames = 0;
      this.listening = true;

      let poll: ReturnType<typeof setInterval> | null = null;
      const settle = (turn: CapturedTurn) => {
        if (!this.listening) return;
        this.listening = false;
        this.onVadTick = null;
        if (poll) clearInterval(poll);
        try {
          this.rec?.abort();
        } catch {
          /* ignore */
        }
        this.hooks.onInterim?.("");
        resolve(turn);
      };
      const finish = (text: string, start: number, end: number, pauses: number[]) => settle({ text, start, end, pauses });
      this.cancelFn = () => finish("", this.now(), this.now(), []);
      this.toTypedFn = () => settle({ text: "", start: 0, end: 0, pauses: [], toTyped: true });

      const broken = () => {
        this.sttBroken = true;
        this.hooks.onSttBroken?.();
        this.toTypedFn?.();
      };

      if (!SR) {
        broken();
        return;
      }
      try {
        this.rec?.abort();
      } catch {
        /* ignore */
      }
      const rec = new SR();
      this.rec = rec;
      rec.lang = "vi-VN";
      rec.continuous = true;
      rec.interimResults = true;
      rec.onresult = (ev) => {
        interimText = "";
        for (let i = ev.resultIndex; i < ev.results.length; i++) {
          const r = ev.results[i];
          if (r.isFinal) finalText += (finalText ? " " : "") + r[0].transcript.trim();
          else interimText += r[0].transcript;
        }
        lastResultAt = this.now();
        this.hooks.onInterim?.((finalText + " " + interimText).trim());
      };
      rec.onend = () => {
        if (this.listening && this.hooks.isActive()) {
          try {
            rec.start();
          } catch {
            /* ignore */
          }
        }
      };
      rec.onerror = (e) => {
        if (FATAL.includes(e.error)) broken();
      };
      try {
        rec.start();
      } catch {
        broken();
        return;
      }

      this.onVadTick = (t) => {
        if (this.uttStart === null || this.silenceStart === null) return;
        const sil = t - this.silenceStart;
        const text = finalText.trim();
        if ((sil >= 1.5 && text && t - lastResultAt > 0.6) || (sil >= 4.5 && (text || interimText.trim()))) {
          finish((text || interimText).trim(), this.uttStart, this.lastVoice ?? t, this.pauses.slice());
        }
      };
      poll = setInterval(() => {
        const t = this.now();
        if (!this.an) {
          const text = finalText.trim();
          if (text && t - lastResultAt > 1.6) finish(text, listenStarted, lastResultAt, []);
        }
        if (t - listenStarted > 20 && this.uttStart === null && !finalText) finish("", t, t, []);
        if (!this.hooks.isActive()) finish("", t, t, []);
      }, 250);
    });
  }
}
