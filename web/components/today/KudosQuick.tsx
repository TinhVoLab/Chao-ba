"use client";
// Today page: a one-row "Gửi thương" strip (the four love cards), the latest reply from the elder, and a link to the
// full "Gửi yêu thương" tray on the Family page. Sends go through the outbox (lib/kudos.ts → postWrite): the tap is
// acknowledged at once (optimistic quota + check mark), rolled back if the server refuses, kept on the device if offline.
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, Check, HandHeart } from "lucide-react";
import { fetchKudos, sendKudos, type Kudos, type KudosCatalog, type KudosList } from "@/lib/kudos";
import { NotSaved } from "../SaveState";
import { T } from "../T";
import { KudosIcon } from "../kudos/KudosIcon";

type Flash = { kind: "sent"; vi: string; en: string } | { kind: "queued" } | { kind: "refused"; vi: string; en: string } | null;

export function KudosQuick({
  elderId,
  kinVi,
  kinEn,
  catalog,
  initial,
}: {
  elderId: string;
  kinVi: string;
  kinEn: string;
  catalog: KudosCatalog | null;
  initial: KudosList | null;
}) {
  const [list, setList] = useState<Kudos[]>(initial?.items ?? []);
  const [remaining, setRemaining] = useState<number>(catalog?.remaining_today ?? initial?.remaining_today ?? 0);
  const [sending, setSending] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [flash, setFlash] = useState<Flash>(null);

  const refresh = useCallback(async () => {
    const r = await fetchKudos(elderId, "sent");
    if (r) {
      setList(r.items);
      setRemaining(r.remaining_today);
    }
  }, [elderId]);

  // Replies arrive from the home screen or the morning call.
  useEffect(() => {
    const id = setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, 30_000);
    return () => clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    if (!done) return;
    const id = setTimeout(() => setDone(null), 2600);
    return () => clearTimeout(id);
  }, [done]);

  const loves = (catalog?.templates ?? []).filter((t) => t.kind === "love").slice(0, 4);
  const canSend = !!catalog?.can_send;
  const limitReached = remaining <= 0;
  const latestReply = list.find((k) => k.status === "replied" && (k.reply_vi || k.reply_hidden));
  const allHref = `/family?elder=${encodeURIComponent(elderId)}&tab=checkin`;

  async function send(templateId: string) {
    if (sending || limitReached) return;
    setSending(templateId);
    setDone(templateId); // optimistic: the tap is acknowledged right away
    setFlash(null);
    setRemaining((n) => Math.max(0, n - 1));
    const r = await sendKudos(elderId, { kind: "love", template_id: templateId });
    setSending(null);
    if (r.state === "saved") {
      setList((l) => [r.kudos, ...l.filter((x) => x.id !== r.kudos.id)]);
      setRemaining(r.remaining);
      setFlash({ kind: "sent", vi: `Đã gửi cho ${kinVi}: “${r.kudos.text_vi}”`, en: `Sent to ${kinEn}: “${r.kudos.text_en}”` });
    } else if (r.state === "queued") {
      setFlash({ kind: "queued" }); // waits in the outbox; the quota stays spent
    } else {
      setDone(null);
      setRemaining((n) => n + 1);
      setFlash({
        kind: "refused",
        vi: r.message?.vi ?? "Chưa gửi được: máy chủ từ chối.",
        en: r.message?.en ?? "Not sent: the server refused it.",
      });
    }
  }

  return (
    <section aria-labelledby="kudos-quick-h" className="flex flex-col gap-3 rounded-3xl border border-line bg-surface p-4" data-testid="kudos-quick">
      <div className="flex items-center justify-between gap-3">
        <h2 id="kudos-quick-h" className="flex min-w-0 items-center gap-2 text-base font-extrabold tracking-tight">
          <span className="grid size-8 shrink-0 place-items-center rounded-full bg-rose-tint text-rose-ink">
            <HandHeart size={18} aria-hidden />
          </span>
          <T vi="Gửi thương" en="Send some love" />
        </h2>
        {canSend && (
          <span className="shrink-0 rounded-full bg-surface-2 px-2.5 py-1 text-xs font-semibold text-ink-2 tnum" data-testid="kudos-quick-remaining">
            <T vi={`Còn ${remaining} lượt`} en={`${remaining} left today`} />
          </span>
        )}
      </div>

      {canSend && loves.length > 0 ? (
        <div className="grid grid-cols-4 gap-2">
          {loves.map((t) => (
            <button
              key={t.id}
              type="button"
              disabled={limitReached || sending !== null}
              onClick={() => send(t.id)}
              data-testid={`kudos-quick-${t.id}`}
              className="flex min-h-[4.5rem] min-w-0 flex-col items-center justify-center gap-1 rounded-2xl bg-rose-tint px-1 py-2 text-center text-rose-ink transition-[transform,filter] duration-150 hover:brightness-[0.97] active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-55"
            >
              {done === t.id ? <Check size={20} aria-hidden /> : <KudosIcon name={t.icon} size={20} />}
              <span className="w-full text-sm font-semibold leading-tight wrap-break-word">
                <T vi={t.label_vi} en={t.label_en} />
              </span>
            </button>
          ))}
        </div>
      ) : (
        <p className="text-[0.9375rem] text-ink-2">
          <T vi="Chưa kết nối được máy chủ, nên chưa gửi được lời thương lúc này." en="The server can't be reached, so love notes can't be sent right now." />
        </p>
      )}

      <div aria-live="polite" className="empty:hidden">
        {flash?.kind === "sent" && (
          <p className="fade-in flex items-start gap-2 text-sm font-medium text-green-ink" data-testid="kudos-quick-flash">
            <Check size={16} className="mt-0.5 shrink-0" aria-hidden />
            <span className="min-w-0 wrap-anywhere">
              <T vi={flash.vi} en={flash.en} />
            </span>
          </p>
        )}
        {flash?.kind === "queued" && <NotSaved className="fade-in" />}
        {flash?.kind === "refused" && (
          <p className="fade-in rounded-xl bg-yellow-tint px-3 py-2 text-sm font-medium text-yellow-ink wrap-anywhere" role="alert">
            <T vi={flash.vi} en={flash.en} />
          </p>
        )}
        {canSend && limitReached && flash?.kind !== "refused" && (
          <p className="text-sm text-ink-2">
            <T
              vi={`Hôm nay bạn đã gửi đủ ${catalog?.limit_per_day ?? ""} lời thương. Gọi ${kinVi} một cuộc nha.`}
              en={`You've sent ${catalog?.limit_per_day ?? ""} notes today. Give ${kinEn} a call.`}
            />
          </p>
        )}
      </div>

      {latestReply && (
        <div className="min-w-0 rounded-2xl bg-green-tint px-3 py-2 text-green-ink" data-testid="kudos-quick-reply">
          <p className="truncate text-xs font-semibold opacity-80" title={latestReply.text_vi}>
            {latestReply.text_lang === "vi" ? (
              <span lang="vi">“{latestReply.text_vi}”</span>
            ) : (
              <T vi={`“${latestReply.text_vi}”`} en={`“${latestReply.text_en}”`} />
            )}
          </p>
          <p className="line-clamp-2 text-[0.9375rem] leading-snug wrap-anywhere">
            <T vi={latestReply.reply_vi} en={latestReply.reply_en} />
          </p>
        </div>
      )}

      <Link href={allHref} className="inline-flex min-h-11 items-center gap-1 self-start font-semibold text-accent" data-testid="kudos-quick-all">
        <T vi="Gửi thêm / xem tất cả" en="Send more / see all" />
        <ArrowRight size={16} aria-hidden />
      </Link>
    </section>
  );
}
