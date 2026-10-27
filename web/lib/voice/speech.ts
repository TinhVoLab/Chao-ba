"use client";
// Text-to-speech for Út Thương (browser speechSynthesis, vi-VN, rate 0.9), ported from chaoba/server/static/call.html.
// Safety rules for the elder screen:
//  - `enabled: false` (?tts=0) never touches speechSynthesis.speak: captions only, with a short reading pause.
//  - stopSpeech() cancels at once; the call session calls it on end, pagehide and when the page is hidden.
//  - When the engine silently does nothing (headless browsers, no voices) we fall back to captions for the session.

export interface SpokenSpan {
  start: number;
  end: number;
  spoken: boolean;
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));
export const wordCount = (t: string) => (t || "").trim().split(/\s+/).filter(Boolean).length;

export function hasTts(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window && typeof window.SpeechSynthesisUtterance === "function";
}

export function stopSpeech(): void {
  try {
    if (hasTts()) window.speechSynthesis.cancel();
  } catch {
    /* ignore */
  }
}

export class Speaker {
  private broken: boolean;
  private voice: SpeechSynthesisVoice | null = null;
  private readonly fast: boolean;
  private readonly now: () => number;

  constructor(opts: { enabled: boolean; fast?: boolean; now: () => number }) {
    this.broken = !opts.enabled || !hasTts();
    this.fast = !!opts.fast;
    this.now = opts.now;
    if (!this.broken) {
      this.pickVoice();
      try {
        window.speechSynthesis.onvoiceschanged = () => this.pickVoice();
      } catch {
        /* ignore */
      }
    }
  }

  get speaking(): boolean {
    return !this.broken;
  }

  private pickVoice() {
    try {
      this.voice = window.speechSynthesis.getVoices().find((v) => /^vi/i.test(v.lang)) ?? null;
    } catch {
      this.voice = null;
    }
  }

  /** Reading pause used instead of speech (captions-only mode). */
  async captionPause(text: string): Promise<void> {
    if (this.fast) return sleep(180);
    await sleep(Math.min(4000, Math.max(900, wordCount(text) * 130)));
  }

  disable(): void {
    this.broken = true;
    stopSpeech();
  }

  speak(text: string, opt: { rate?: number; pitch?: number } = {}): Promise<SpokenSpan> {
    const clean = text.replace(/^\([^)]*\)\s*/, "");
    if (this.broken) {
      const s0 = this.now();
      return this.captionPause(text).then(() => ({ start: s0, end: this.now(), spoken: false }));
    }
    return new Promise((resolve) => {
      let start: number | null = null;
      let done = false;
      const finish = (spoken: boolean) => {
        if (done) return;
        done = true;
        resolve({ start: start ?? this.now(), end: this.now(), spoken });
      };
      try {
        const u = new SpeechSynthesisUtterance(clean);
        u.lang = "vi-VN";
        if (this.voice) u.voice = this.voice;
        u.rate = opt.rate ?? 0.9;
        u.pitch = opt.pitch ?? 1.0;
        u.onstart = () => {
          start = this.now();
        };
        u.onend = () => finish(true);
        u.onerror = () => finish(start !== null);
        window.speechSynthesis.cancel();
        window.speechSynthesis.speak(u);
      } catch {
        this.broken = true;
        finish(false);
        return;
      }
      setTimeout(() => {
        if (start === null && !done) {
          this.disable();
          const s0 = this.now();
          this.captionPause(text).then(() => {
            start = s0;
            finish(false);
          });
        }
      }, 1500);
      // onend sometimes never fires
      setTimeout(() => finish(true), Math.max(2, wordCount(text) / 2.6) * 1000 + 2500);
    });
  }
}
