"use client";
// Optional Gemini Live voice engine for the elder screen (same protocol as chaoba/server/static/call.html):
//   browser <-> Chào Bà server WebSocket /ws/voice/{call_id} <-> Gemini Live (server-side proxy; no key in the browser)
// Up:   16 kHz 16-bit PCM mic frames (AudioWorklet, no audio output) + {"type":"vad"} events from the existing WebAudio
//       VAD + {"type":"text"} typed / simulated lines + {"type":"playback"} / {"type":"end"}.
// Down: 24 kHz 16-bit PCM audio frames + {"type": ready | transcript | turn | interrupt | agent_done | say | ended |
//       fallback | error} (CONTRACT.md, "Voice WebSocket").
// The server runs our safety checks on the transcripts and stores no audio. `muted` (?mute=1, tests) never creates an
// audio output: playback is only timed, so a test can never make a sound.

export interface VoiceInfo {
  engine: "gemini-live" | "browser";
  ws?: string;
  model?: string;
  voice?: string;
  output_rate?: number;
  note_vi?: string;
  note_en?: string;
}

export type LiveMsg =
  | { type: "ready"; model: string; voice: string; input_rate: number; output_rate: number }
  | { type: "transcript"; who: "agent" | "elder"; text: string; final: boolean; greeting?: boolean }
  | { type: "turn"; reply_text: string; phase: string; emergency: boolean; end_call: boolean; event: string | null; tier: "acute" | "non_acute" | "third_party" | null }
  | { type: "interrupt"; reason: "barge_in" | "safety" | "correction" }
  | { type: "agent_done" }
  | { type: "say"; text: string; reason: string }
  | { type: "ended"; reason: string; end_reason: string }
  | { type: "fallback"; reason: string; note_vi?: string; note_en?: string }
  | { type: "error"; error: string };

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/** Plays 24 kHz PCM frames back to back; `flush()` stops at once (barge-in, safety). */
export class PcmPlayer {
  private ctx: AudioContext | null = null;
  private next = 0;
  private vEnd = 0;
  private readonly srcs = new Set<AudioBufferSourceNode>();

  constructor(
    private readonly rate: number,
    private readonly muted: boolean,
    private readonly speed = 1,
  ) {}

  push(buf: ArrayBuffer): void {
    const n = buf.byteLength >> 1;
    const dur = n / this.rate;
    if (this.muted) {
      const t = performance.now() / 1000;
      this.vEnd = Math.max(this.vEnd, t) + dur / this.speed;
      return;
    }
    if (!this.ctx) {
      const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      this.ctx = new AC({ sampleRate: this.rate });
    }
    const i16 = new Int16Array(buf, 0, n);
    const ab = this.ctx.createBuffer(1, n, this.rate);
    const ch = ab.getChannelData(0);
    for (let i = 0; i < n; i++) ch[i] = i16[i] / 32768;
    const s = this.ctx.createBufferSource();
    s.buffer = ab;
    s.connect(this.ctx.destination);
    const st = Math.max(this.ctx.currentTime + 0.04, this.next);
    s.start(st);
    this.next = st + dur;
    this.srcs.add(s);
    s.onended = () => this.srcs.delete(s);
  }

  remaining(): number {
    if (this.muted) return Math.max(0, this.vEnd - performance.now() / 1000);
    return this.ctx ? Math.max(0, this.next - this.ctx.currentTime) : 0;
  }

  flush(): void {
    this.srcs.forEach((s) => {
      try {
        s.stop();
      } catch {
        /* ignore */
      }
    });
    this.srcs.clear();
    this.next = 0;
    this.vEnd = 0;
  }

  async drained(maxMs: number): Promise<void> {
    const t0 = performance.now();
    while (this.remaining() > 0.05 && performance.now() - t0 < maxMs) await sleep(100);
  }

  close(): void {
    this.flush();
    this.ctx?.close().catch(() => undefined);
    this.ctx = null;
  }
}

// Downsamples the mic to 16 kHz (box filter) and posts 100 ms Int16 frames. No outputs: nothing reaches the speakers.
const WORKLET = `class P extends AudioWorkletProcessor{constructor(){super();this.r=sampleRate/16000;this.t=0;this.s=0;this.c=0;this.b=new Int16Array(1600);this.n=0}
process(i){const x=i[0]&&i[0][0];if(!x)return true;for(let k=0;k<x.length;k++){this.s+=x[k];this.c++;this.t+=1;if(this.t>=this.r){this.t-=this.r;
let v=this.s/this.c;v=v<-1?-1:v>1?1:v;this.b[this.n++]=v<0?v*32768:v*32767;this.s=0;this.c=0;if(this.n===1600){this.port.postMessage(this.b.buffer,[this.b.buffer]);
this.b=new Int16Array(1600);this.n=0}}}return true}}registerProcessor("chaoba-pcm16",P);`;

export async function startPcmCapture(
  audio: { ctx: AudioContext; source: MediaStreamAudioSourceNode },
  onFrame: (frame: ArrayBuffer) => void,
): Promise<(() => void) | null> {
  if (!audio.ctx.audioWorklet) return null;
  try {
    const url = URL.createObjectURL(new Blob([WORKLET], { type: "application/javascript" }));
    await audio.ctx.audioWorklet.addModule(url);
    const node = new AudioWorkletNode(audio.ctx, "chaoba-pcm16", { numberOfInputs: 1, numberOfOutputs: 0 });
    node.port.onmessage = (e: MessageEvent<ArrayBuffer>) => onFrame(e.data);
    audio.source.connect(node);
    return () => {
      try {
        audio.source.disconnect(node);
        node.port.onmessage = null;
      } catch {
        /* ignore */
      }
    };
  } catch (e) {
    console.warn("mic stream unavailable", e);
    return null;
  }
}

export function voiceWsUrl(apiBase: string, path: string): string {
  const base = apiBase ? new URL(apiBase, window.location.href) : new URL(window.location.href);
  return (base.protocol === "https:" ? "wss://" : "ws://") + base.host + path;
}
