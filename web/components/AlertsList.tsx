"use client";
import { useEffect, useState } from "react";
import { Check, CheckCheck, Info, OctagonAlert, TriangleAlert } from "lucide-react";
import type { Alert } from "@/lib/types";
import { SENT_EVENT, postWrite, useOutbox, type PendingWrite } from "@/lib/outbox";
import { NotSaved, SaveRefused } from "./SaveState";
import { longDate } from "@/lib/format";
import { T } from "./T";

const SEV: Record<string, { vi: string; en: string; Icon: typeof Info; cls: string }> = {
  critical: { vi: "Khẩn", en: "Urgent", Icon: OctagonAlert, cls: "bg-red-tint text-red-ink" },
  warning: { vi: "Lưu ý", en: "Heads-up", Icon: TriangleAlert, cls: "bg-yellow-tint text-yellow-ink" },
  info: { vi: "Thông tin", en: "Info", Icon: Info, cls: "bg-surface-2 text-ink-2" },
};

// Alert types the API emits (CONTRACT.md "Alert types"): light rises carry the first reason code of that day.
const TYPE: Record<string, { vi: string; en: string }> = {
  metric_trend: { vi: "Thay đổi so với thường ngày", en: "Change from usual" },
  metric_shift: { vi: "Thay đổi rõ so với thường ngày", en: "Clear change from usual" },
  multi_metric: { vi: "Nhiều chỉ số cùng thay đổi", en: "Several signals changed" },
  fall: { vi: "Kể chuyện té ngã", en: "Mentioned a fall" },
  multi_symptom: { vi: "Nhiều than phiền sức khoẻ", en: "Several health complaints" },
  symptom_repeat: { vi: "Nhắc triệu chứng nhiều lần", en: "Repeated symptom mentions" },
  unanswered: { vi: "Nhiều ngày không bắt máy", en: "Calls not answered" },
  low_mood: { vi: "Nghe buồn, mệt nhiều ngày", en: "Sounded low for several days" },
  light_red: { vi: "Đèn chuyển đỏ", en: "Light turned red" },
  light_yellow: { vi: "Đèn chuyển vàng", en: "Light turned yellow" },
  emergency: { vi: "Có thể khẩn cấp", en: "Possible emergency" },
  opt_out: { vi: "Người thân muốn tạm dừng", en: "Paused by your parent" },
  scam_topic: { vi: "Nhắc chuyện tiền, mã OTP", en: "Mentioned money or OTP codes" },
};

export function AlertsList({ elderId, initial }: { elderId: string; initial: Alert[] }) {
  const [alerts, setAlerts] = useState(initial);
  const [pending, setPending] = useState<string | number | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const outbox = useOutbox(elderId);
  // Acks still waiting in the outbox: shown as "not saved", never as "seen".
  const queued = new Set(outbox.filter((p) => p.kind === "ack").map((p) => String(p.meta?.alertId)));
  const unread = alerts.filter((a) => !a.acknowledged).length;

  // A queued ack reached the server later: now it is really "seen".
  useEffect(() => {
    function sent(e: Event) {
      const { item } = (e as CustomEvent<{ item: PendingWrite }>).detail;
      if (item.kind !== "ack" || item.elderId !== elderId) return;
      setAlerts((list) => list.map((a) => (String(a.id) === String(item.meta?.alertId) ? { ...a, acknowledged: true } : a)));
    }
    window.addEventListener(SENT_EVENT, sent);
    return () => window.removeEventListener(SENT_EVENT, sent);
  }, [elderId]);

  async function ack(id: string | number) {
    setPending(id);
    setRefused(null);
    const r = await postWrite(
      "ack",
      elderId,
      `/api/elders/${encodeURIComponent(elderId)}/alerts/${encodeURIComponent(String(id))}/ack`,
      undefined,
      { meta: { alertId: String(id) } },
    );
    if (r.state === "saved") {
      setAlerts((list) => list.map((a) => (a.id === id ? { ...a, acknowledged: true } : a)));
      window.dispatchEvent(new Event("cb-alerts-changed")); // refresh the unread badge in the nav
    }
    if (r.state === "rejected") setRefused(r.detail);
    setPending(null);
  }

  if (!alerts.length) {
    return (
      <div className="rounded-2xl bg-surface-2 p-6">
        <p className="text-lg font-semibold">
          <T vi="Chưa có cảnh báo nào." en="No alerts yet." />
        </p>
        <p className="mt-1 text-ink-2">
          <T
            vi="Khi đèn chuyển vàng hoặc đỏ, hay người thân không bắt máy 2 ngày liền, bạn sẽ thấy ở đây kèm lời giải thích."
            en="When the light turns yellow or red, or calls go unanswered two days running, it shows here with a plain explanation."
          />
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-ink-2" aria-live="polite">
        {unread > 0 ? (
          <T vi={`${unread} cảnh báo chưa xem`} en={`${unread} unread alert${unread > 1 ? "s" : ""}`} />
        ) : (
          <span className="inline-flex items-center gap-1.5">
            <CheckCheck size={18} aria-hidden />
            <T vi="Bạn đã xem hết" en="You're all caught up" />
          </span>
        )}
      </p>
      {refused != null && <SaveRefused detail={refused} />}
      <ol className="flex flex-col gap-3">
        {alerts.map((a) => {
          const s = SEV[a.severity] ?? SEV.info;
          const ty = TYPE[a.type] ?? { vi: a.type, en: a.type };
          const d = longDate(a.date ?? "");
          return (
            <li
              key={a.id}
              className={`rounded-2xl border p-4 transition-colors duration-200 ${
                a.acknowledged ? "border-line bg-transparent" : "border-line-strong bg-surface shadow-soft"
              }`}
            >
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-sm font-bold ${s.cls}`}>
                  <s.Icon size={15} aria-hidden />
                  <T vi={s.vi} en={s.en} />
                </span>
                <h2 className="font-bold">
                  <T vi={ty.vi} en={ty.en} />
                </h2>
                <span className="ml-auto text-sm text-ink-3 tnum">
                  <T vi={d.vi} en={d.en} />
                </span>
              </div>
              <p className={`mt-2 max-w-[65ch] ${a.acknowledged ? "text-ink-2" : "text-ink"}`}>
                <T vi={a.explanation_vi} en={a.explanation_en} />
              </p>
              <div className="mt-3">
                {!a.acknowledged && queued.has(String(a.id)) ? (
                  <NotSaved />
                ) : a.acknowledged ? (
                  <span className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-3">
                    <Check size={16} aria-hidden />
                    <T vi="Đã xem" en="Seen" />
                  </span>
                ) : (
                  <button
                    type="button"
                    onClick={() => ack(a.id)}
                    disabled={pending === a.id}
                    className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-ink px-4 font-semibold text-bg transition-opacity duration-150 disabled:opacity-50"
                  >
                    <Check size={18} aria-hidden />
                    <T vi="Đã xem, tôi sẽ lo" en="Seen, I'm on it" />
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
