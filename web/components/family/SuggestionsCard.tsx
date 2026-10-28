"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Bot, BookHeart, Check, Lightbulb, Puzzle } from "lucide-react";
import type { AskedBy, Suggestions } from "@/lib/types";
import { postWrite, useOutbox } from "@/lib/outbox";
import { shortDate } from "@/lib/format";
import { NotSaved, SaveRefused } from "../SaveState";
import { T } from "../T";

const SOURCE = {
  call: { vi: "Từ cuộc gọi", en: "From the call", Icon: Bot },
  memory: { vi: "Kỷ niệm", en: "Memory", Icon: BookHeart },
  synthesis: { vi: "Cả nhà cùng nghe", en: "Heard by several", Icon: Puzzle },
};

/** “Mình hỏi rồi”: marks a topic as asked for the whole family this week. Shared by the suggestions and the synthesis. */
export function AskedButton({ elderId, topicKey, askedBy = [] }: { elderId: string; topicKey: string; askedBy?: AskedBy[] }) {
  const router = useRouter();
  const [done, setDone] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);
  const queued = useOutbox(elderId).some((p) => p.kind === "asked" && String(p.meta?.key) === topicKey);

  async function asked() {
    setRefused(null);
    setDone(true);
    const r = await postWrite("asked", elderId, `/api/elders/${encodeURIComponent(elderId)}/family/suggestions/asked`, { topic_key: topicKey }, { meta: { key: topicKey } });
    if (r.state === "rejected") {
      setRefused(r.detail);
      setDone(false);
    } else if (r.state === "saved") router.refresh();
  }

  if (askedBy.length > 0 && !done) {
    return (
      <p className="mt-2 flex items-start gap-1.5 text-sm font-semibold text-green-ink">
        <Check size={16} className="mt-0.5 shrink-0" aria-hidden />
        <AskedByLine by={askedBy} />
      </p>
    );
  }
  return (
    <>
      {queued && <NotSaved className="mt-2" />}
      <button
        type="button"
        disabled={done}
        onClick={asked}
        className="mt-2 flex min-h-11 items-center gap-1.5 rounded-full border border-line-strong bg-surface px-3.5 text-sm font-semibold transition-colors duration-150 hover:border-accent hover:text-accent disabled:border-green-tint disabled:bg-green-tint disabled:text-green-ink"
      >
        <Check size={16} aria-hidden />
        {done ? <T vi="Đã hỏi" en="Asked" /> : <T vi="Mình hỏi rồi" en="I asked" />}
      </button>
      {refused && <SaveRefused detail={refused} />}
    </>
  );
}

function AskedByLine({ by }: { by: AskedBy[] }) {
  return (
    <span>
      {by.map((b, i) => (
        <span key={i}>
          {i > 0 && " · "}
          {b.you ? (
            <T vi={`Bạn đã hỏi ${shortDate(b.date ?? "")}`} en={`You asked ${shortDate(b.date ?? "")}`} />
          ) : b.how === "asked" ? (
            <T vi={`${b.name} đã hỏi ${shortDate(b.date ?? "")}`} en={`${b.name} asked ${shortDate(b.date ?? "")}`} />
          ) : (
            <T vi={`${b.name} đã nhắc trong ghi chú ${shortDate(b.date ?? "")}`} en={`${b.name} mentioned it in a note ${shortDate(b.date ?? "")}`} />
          )}
        </span>
      ))}
    </span>
  );
}

/** "Gợi ý chủ đề trước khi gọi": fresh topics first; what a sibling already asked this week is set aside.
 *  `omitKey`: a topic already shown elsewhere (the weekly synthesis carries its own “Mình hỏi rồi”). */
export function SuggestionsCard({
  elderId,
  data,
  kinVi,
  kinEn,
  omitKey,
}: {
  elderId: string;
  data: Suggestions;
  kinVi: string;
  kinEn: string;
  omitKey?: string | null;
}) {
  const fresh = data.suggestions.filter((s) => s.key !== omitKey);
  const already = data.already_asked.filter((s) => s.key !== omitKey);

  return (
    <section aria-labelledby="sug-h" className="flex flex-col gap-3">
      <h2 id="sug-h" className="flex items-center gap-2 text-sm font-bold uppercase tracking-wide text-ink-3">
        <Lightbulb size={16} aria-hidden />
        <T vi="Trước khi gọi, hỏi thử" en="Before you call, try asking" />
      </h2>
      {fresh.length === 0 ? (
        <p className="text-ink-2">
          <T vi={`Chưa có gợi ý mới. Hỏi ${kinVi} hôm nay thế nào là đủ.`} en={`No new topics. Asking ${kinEn} how today went is enough.`} />
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {fresh.map((s) => {
            const src = SOURCE[s.source] ?? SOURCE.call;
            return (
              <li key={s.key} className="flex items-start gap-3 rounded-2xl border border-line bg-surface p-3.5">
                <span className="grid size-9 shrink-0 place-items-center rounded-full bg-surface-2 text-ink-2">
                  <src.Icon size={18} aria-hidden />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-semibold uppercase tracking-wide text-ink-3">
                    <T vi={src.vi} en={src.en} />
                  </p>
                  <p className="font-medium leading-snug">
                    <T vi={s.text_vi} en={s.text_en} />
                  </p>
                  <AskedButton elderId={elderId} topicKey={s.key} />
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {already.length > 0 && (
        <details className="group rounded-2xl bg-surface-2 px-4 py-2">
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between font-semibold text-ink-2">
            <T vi={`Tuần này đã có người hỏi (${already.length})`} en={`Already covered this week (${already.length})`} />
            <span className="text-sm font-normal text-ink-3 group-open:hidden">
              <T vi="Xem" en="Show" />
            </span>
          </summary>
          <ul className="flex flex-col gap-2 pb-2">
            {already.map((s) => (
              <li key={s.key} className="text-[0.9375rem] text-ink-2">
                <span className="line-through decoration-ink-3/50">
                  <T vi={s.text_vi} en={s.text_en} />
                </span>
                <span className="block text-sm text-ink-3">
                  <AskedByLine by={s.asked_by} />
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
