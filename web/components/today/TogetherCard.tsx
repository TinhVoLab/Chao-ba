"use client";
// Today page: "Cả nhà ghé thăm" (chaoba/server/together.py). The same faces strip the elder sees on the home screen,
// a gentle nudge for the viewer if they have not dropped by yet, and "Gửi ảnh cho má": a photo of your day, resized
// here to at most 900 px JPEG before upload, shown on the big screen as a slow slideshow. Photos are not queued
// offline (too large for the device outbox): a failed send says so and keeps the picture for another try.
import { useCallback, useEffect, useRef, useState } from "react";
import { Camera, Check, Heart, Users } from "lucide-react";
import { API_BASE } from "@/lib/config";
import { refusalMessage } from "@/lib/kudos";
import { postWrite } from "@/lib/outbox";
import { actorHeaders } from "@/lib/viewer";
import { T } from "../T";

interface Member {
  member_id: string;
  name: string;
  visited: boolean;
  first_time: string | null;
}
interface Together {
  members: Member[];
  all_here: boolean;
  line_vi: string;
  line_en: string;
  moment: { hearted: boolean };
  me: { visited: boolean } | null;
  photos: { id: number; sender_id: string | null; hearted: boolean; caption: string }[];
}

const MAX_SIDE = 900;

async function shrink(file: File): Promise<string> {
  const bmp = await createImageBitmap(file);
  const scale = Math.min(1, MAX_SIDE / Math.max(bmp.width, bmp.height));
  const c = document.createElement("canvas");
  c.width = Math.round(bmp.width * scale);
  c.height = Math.round(bmp.height * scale);
  c.getContext("2d")!.drawImage(bmp, 0, 0, c.width, c.height);
  bmp.close();
  for (const q of [0.82, 0.7, 0.55]) {
    const url = c.toDataURL("image/jpeg", q);
    if (url.length < 440_000) return url;
  }
  return c.toDataURL("image/jpeg", 0.4);
}

export function TogetherCard({ elderId, memberId, kinVi, kinEn }: { elderId: string; memberId: string | null; kinVi: string; kinEn: string }) {
  const [tg, setTg] = useState<Together | null>(null);
  const [image, setImage] = useState<string | null>(null);
  const [caption, setCaption] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "sent" | { vi: string; en: string }>("idle");
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/api/elders/${encodeURIComponent(elderId)}/together`, {
        headers: actorHeaders(elderId, memberId),
        cache: "no-store",
        signal: AbortSignal.timeout(4000),
      });
      if (r.ok) setTg((await r.json()) as Together);
    } catch {
      /* offline: the card stays hidden */
    }
  }, [elderId, memberId]);

  useEffect(() => {
    const first = setTimeout(() => void load(), 0);
    const id = setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, 30_000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [load]);

  async function pick(f: File | undefined) {
    if (!f) return;
    setState("idle");
    try {
      setImage(await shrink(f));
    } catch {
      setState({ vi: "Không đọc được ảnh này. Thử ảnh khác nha.", en: "Couldn't read this picture. Try another one." });
    }
  }

  async function send() {
    if (!image) return;
    setState("sending");
    const r = await postWrite("photo", elderId, `/api/elders/${encodeURIComponent(elderId)}/photos`, { image, caption: caption.trim() || null }, { queue: false });
    if (r.state === "saved") {
      setState("sent");
      setImage(null);
      setCaption("");
      void load();
      return;
    }
    let msg = { vi: "Chưa gửi được ảnh. Kiểm tra mạng rồi thử lại.", en: "The photo wasn't sent. Check the connection and try again." };
    if (r.state === "rejected") msg = refusalMessage(r.detail) ?? msg;
    setState(msg);
  }

  if (!tg || tg.members.length === 0) return null;
  const mine = tg.photos.filter((x) => x.sender_id === memberId);
  const hearted = mine.find((x) => x.hearted);

  return (
    <section aria-labelledby="together-h" className="flex flex-col gap-3 rounded-3xl border border-line bg-surface p-4" data-testid="together">
      <h2 id="together-h" className="flex items-center gap-2 text-base font-extrabold tracking-tight">
        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-accent-tint text-accent-ink">
          <Users size={18} aria-hidden />
        </span>
        <T vi="Cả nhà ghé thăm" en="Family drop-ins" />
      </h2>

      <div className="flex items-center gap-3">
        <ul className="flex shrink-0">
          {tg.members.map((m, i) => (
            <li
              key={m.member_id}
              title={m.name}
              className={`relative grid size-10 place-items-center rounded-full border-2 border-surface text-sm font-extrabold ${i ? "-ml-2" : ""} ${m.visited ? "bg-green-tint text-green-ink" : "bg-surface-2 text-ink-3"}`}
            >
              {m.name.slice(0, 1)}
              {m.visited && <Check size={12} strokeWidth={3.5} className="absolute -bottom-0.5 -right-0.5 rounded-full bg-green-ink p-0.5 text-surface" aria-hidden />}
            </li>
          ))}
        </ul>
        <p className="min-w-0 text-[0.9375rem] leading-snug text-ink-2" data-testid="together-line">
          <T vi={tg.line_vi} en={tg.line_en} />
          {tg.moment.hearted && (
            <span className="ml-1 inline-flex items-center gap-1 font-semibold text-rose-ink">
              <Heart size={14} className="fill-current" aria-hidden />
              <T vi={`${kinVi[0].toUpperCase()}${kinVi.slice(1)} đã gửi thương cả nhà`} en={`${kinEn} sent love to everyone`} />
            </span>
          )}
        </p>
      </div>

      {tg.me && !tg.me.visited && (
        <p className="rounded-xl bg-yellow-tint px-3 py-2 text-sm font-medium text-yellow-ink" data-testid="together-nudge">
          <T
            vi={tg.members.filter((m) => m.visited).length === tg.members.length - 1 ? `Chỉ còn bạn nữa là cả nhà đã ghé thăm ${kinVi} hôm nay.` : `Hôm nay bạn chưa ghé thăm ${kinVi}. Một tấm ảnh hay một lời thương là đủ.`}
            en={tg.members.filter((m) => m.visited).length === tg.members.length - 1 ? `You're the last one: then the whole family has dropped by ${kinEn} today.` : `You haven't dropped by ${kinEn} today. A photo or a love note is enough.`}
          />
        </p>
      )}

      <input ref={fileRef} type="file" accept="image/*" className="sr-only" tabIndex={-1} aria-hidden onChange={(e) => void pick(e.target.files?.[0])} />
      {image ? (
        <div className="flex flex-col gap-2">
          {/* eslint-disable-next-line @next/next/no-img-element -- local preview */}
          <img src={image} alt="" className="max-h-56 w-full rounded-2xl object-cover" />
          <label className="flex flex-col gap-1 text-sm font-semibold text-ink-2">
            <T vi={`Vài chữ cho ${kinVi} (không bắt buộc)`} en={`A few words for ${kinEn} (optional)`} />
            <input
              value={caption}
              maxLength={80}
              onChange={(e) => setCaption(e.target.value)}
              className="min-h-11 rounded-xl border border-line bg-surface-2 px-3 text-base font-normal text-ink"
              data-testid="together-caption"
            />
          </label>
          <div className="flex gap-2">
            <button type="button" onClick={() => void send()} disabled={state === "sending"} className="min-h-11 flex-1 rounded-xl bg-accent px-4 font-bold text-accent-ink disabled:opacity-60" data-testid="together-send">
              <T vi={`Gửi lên màn hình của ${kinVi}`} en={`Send to ${kinEn}'s screen`} />
            </button>
            <button type="button" onClick={() => setImage(null)} className="min-h-11 rounded-xl bg-surface-2 px-4 font-semibold text-ink-2">
              <T vi="Thôi" en="Cancel" />
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          className="inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-accent px-4 font-bold text-accent-ink shadow-soft hover:bg-accent-hover"
          data-testid="together-photo"
        >
          <Camera size={18} aria-hidden />
          <T vi={`Gửi ảnh cho ${kinVi}`} en={`Send ${kinEn} a photo`} />
        </button>
      )}

      <div aria-live="polite" className="empty:hidden">
        {state === "sent" && (
          <p className="fade-in flex items-center gap-2 text-sm font-medium text-green-ink">
            <Check size={16} aria-hidden />
            <T vi={`Ảnh đang hiện trên màn hình của ${kinVi}.`} en={`The photo is now on ${kinEn}'s screen.`} />
          </p>
        )}
        {typeof state === "object" && (
          <p className="fade-in rounded-xl bg-yellow-tint px-3 py-2 text-sm font-medium text-yellow-ink" role="alert">
            <T vi={state.vi} en={state.en} />
          </p>
        )}
        {state !== "sent" && hearted && (
          <p className="flex items-center gap-2 text-sm font-medium text-rose-ink">
            <Heart size={14} className="fill-current" aria-hidden />
            <T vi={`${kinVi[0].toUpperCase()}${kinVi.slice(1)} đã thả tim ảnh của bạn${hearted.caption ? `: “${hearted.caption}”` : ""}`} en={`${kinEn} hearted your photo${hearted.caption ? `: “${hearted.caption}”` : ""}`} />
          </p>
        )}
      </div>
    </section>
  );
}
