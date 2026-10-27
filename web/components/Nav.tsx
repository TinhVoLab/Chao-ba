"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import {
  Bell,
  BookHeart,
  ChartLine,
  ChevronRight,
  Ellipsis,
  HousePlus,
  RefreshCw,
  ShieldCheck,
  Sunrise,
  UsersRound,
  X,
} from "lucide-react";
import { API_BASE } from "@/lib/config";
import { actorHeaders } from "@/lib/viewer";
import { SENT_EVENT } from "@/lib/outbox";

type Item = { href: string; vi: string; en: string; Icon: typeof Bell; descVi?: string; descEn?: string; prefetch?: boolean };

// Four everyday places on the phone bar, everything else one tap away under "Thêm / More".
const PRIMARY: Item[] = [
  { href: "/", vi: "Hôm nay", en: "Today", Icon: Sunrise },
  { href: "/trends", vi: "Xu hướng", en: "Trends", Icon: ChartLine },
  { href: "/family", vi: "Gia đình", en: "Family", Icon: UsersRound },
  { href: "/dmaic", vi: "DMAIC", en: "DMAIC", Icon: RefreshCw },
];
const MORE: Item[] = [
  { href: "/alerts", vi: "Cảnh báo", en: "Alerts", Icon: Bell, descVi: "Những lần đèn đổi màu, cần gọi hỏi thăm", descEn: "When the light changed and a call is due" },
  // Built by the memory-book workstream; not prefetched so a build without it does not log 404s.
  { href: "/memories", prefetch: false, vi: "Sổ ký ức", en: "Memory book", Icon: BookHeart, descVi: "Chuyện xưa người thân kể với Út Thương", descEn: "Stories your parent shared with Út Thương" },
  { href: "/privacy", vi: "Riêng tư", en: "Privacy", Icon: ShieldCheck, descVi: "Đồng ý, ai đã xem, lưu giữ dữ liệu", descEn: "Consent, who looked, data retention" },
  { href: "/community", vi: "Cộng đồng", en: "Community", Icon: HousePlus, descVi: "Bảng của trạm y tế phường (mô phỏng)", descEn: "Ward health-station board (simulated)" },
];

const isActive = (path: string, href: string) => (href === "/" ? path === "/" : path.startsWith(href));

/** Unread alerts for the selected elder (shown on "Thêm" and on the Alerts row). Silent when the API is down. */
function useUnread(elder: string, path: string) {
  const [n, setN] = useState(0);
  const load = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/elders/${encodeURIComponent(elder)}/alerts`, {
        headers: actorHeaders(elder),
        signal: AbortSignal.timeout(4000),
      });
      if (!res.ok) return;
      const list = (await res.json()) as { acknowledged?: boolean }[];
      setN(Array.isArray(list) ? list.filter((a) => !a.acknowledged).length : 0);
    } catch {
      /* offline: no badge */
    }
  }, [elder]);
  useEffect(() => {
    const t = setTimeout(load, 0);
    window.addEventListener(SENT_EVENT, load);
    window.addEventListener("cb-alerts-changed", load);
    return () => {
      clearTimeout(t);
      window.removeEventListener(SENT_EVENT, load);
      window.removeEventListener("cb-alerts-changed", load);
    };
  }, [load, path]);
  return n;
}

function Badge({ n, className = "" }: { n: number; className?: string }) {
  if (!n) return null;
  return (
    <span
      className={`inline-grid min-w-5 place-items-center rounded-full bg-red px-1.5 text-[0.6875rem] font-bold leading-5 text-on-red tnum ${className}`}
    >
      {n > 9 ? "9+" : n}
      <span className="sr-only">
        <span className="l-vi"> cảnh báo chưa xem</span>
        <span className="l-en"> unread alerts</span>
      </span>
    </span>
  );
}

/** Bottom tab bar on phones (4 places + "More" sheet), side rail on desktop (everything listed). */
export function Nav() {
  const path = usePathname();
  const sp = useSearchParams();
  const elder = sp.get("elder");
  const q = elder ? `?elder=${encodeURIComponent(elder)}` : "";
  const unread = useUnread(elder ?? "hanh", path);
  const [open, setOpen] = useState(false);
  const [openedAt, setOpenedAt] = useState(path);
  const sheetRef = useRef<HTMLDivElement>(null);
  const moreActive = MORE.some((m) => isActive(path, m.href));
  // Close the sheet when the route changes (state adjusted during render, no effect needed).
  if (openedAt !== path) {
    setOpenedAt(path);
    if (open) setOpen(false);
  }

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    sheetRef.current?.querySelector<HTMLElement>("a")?.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const tabCls = (active: boolean) =>
    `group flex min-h-16 w-full flex-col items-center justify-center gap-1 text-[0.75rem] font-semibold transition-colors duration-150 lg:min-h-12 lg:flex-row lg:justify-start lg:gap-3 lg:rounded-xl lg:px-3 lg:text-base ${
      active ? "text-accent lg:bg-accent-tint" : "text-ink-3 hover:text-ink"
    }`;
  const pill = (active: boolean) =>
    `relative grid h-8 w-14 place-items-center rounded-full transition-colors duration-200 lg:h-auto lg:w-auto ${
      active ? "bg-accent-tint lg:bg-transparent" : ""
    }`;

  return (
    <>
      {/* Phone: "More" sheet */}
      {open && (
        <div className="fixed inset-0 z-30 lg:hidden" onClick={() => setOpen(false)}>
          <div className="absolute inset-0 bg-ink/25" aria-hidden />
          <div
            id="more-sheet"
            ref={sheetRef}
            role="dialog"
            aria-modal="true"
            aria-label="Thêm / More"
            onClick={(e) => e.stopPropagation()}
            className="sheet-in absolute inset-x-0 bottom-0 mx-auto max-w-xl rounded-t-[28px] border border-line bg-surface px-3 pb-[calc(5.5rem+env(safe-area-inset-bottom))] pt-3 shadow-soft"
          >
            <div className="mb-1 flex items-center justify-between px-2">
              <p className="text-sm font-bold uppercase tracking-wide text-ink-3">
                <span className="l-vi">Thêm</span>
                <span className="l-en">More</span>
              </p>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="grid size-11 place-items-center rounded-full text-ink-2 hover:text-ink"
              >
                <X size={20} aria-hidden />
                <span className="sr-only">Đóng / Close</span>
              </button>
            </div>
            <ul className="flex flex-col">
              {MORE.map(({ href, vi, en, Icon, descVi, descEn, prefetch }) => {
                const active = isActive(path, href);
                return (
                  <li key={href}>
                    <Link
                      href={`${href}${q}`}
                      prefetch={prefetch}
                      aria-current={active ? "page" : undefined}
                      onClick={() => setOpen(false)}
                      className={`flex min-h-16 items-center gap-3 rounded-2xl px-3 py-2 transition-colors duration-150 ${
                        active ? "bg-accent-tint text-accent" : "hover:bg-surface-2"
                      }`}
                    >
                      <span className={`grid size-10 shrink-0 place-items-center rounded-full ${active ? "bg-surface" : "bg-surface-2"}`}>
                        <Icon size={20} aria-hidden />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="flex items-center gap-2 font-semibold text-ink">
                          <span className="l-vi">{vi}</span>
                          <span className="l-en">{en}</span>
                          {href === "/alerts" && <Badge n={unread} />}
                        </span>
                        <span className="block text-sm text-ink-3">
                          <span className="l-vi">{descVi}</span>
                          <span className="l-en">{descEn}</span>
                        </span>
                      </span>
                      <ChevronRight size={18} className="shrink-0 text-ink-3" aria-hidden />
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
      )}

      <nav
        aria-label="Chính / Main"
        className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-surface/95 backdrop-blur-sm pb-safe lg:inset-y-0 lg:left-0 lg:right-auto lg:w-56 lg:overflow-y-auto lg:border-r lg:border-t-0 lg:bg-surface lg:pt-24"
      >
        <ul className="mx-auto grid max-w-xl grid-cols-5 lg:flex lg:flex-col lg:gap-1 lg:px-3">
          {PRIMARY.map(({ href, vi, en, Icon }) => {
            const active = isActive(path, href);
            return (
              <li key={href}>
                <Link href={`${href}${q}`} aria-current={active ? "page" : undefined} className={tabCls(active)}>
                  <span className={pill(active)}>
                    <Icon size={22} strokeWidth={active ? 2.4 : 2} aria-hidden />
                  </span>
                  <span className="l-vi">{vi}</span>
                  <span className="l-en">{en}</span>
                </Link>
              </li>
            );
          })}
          {/* Phone only: the "More" tab */}
          <li className="lg:hidden">
            <button
              type="button"
              onClick={() => setOpen((o) => !o)}
              aria-expanded={open}
              aria-controls="more-sheet"
              aria-haspopup="dialog"
              className={tabCls(moreActive || open)}
            >
              <span className={pill(moreActive || open)}>
                <Ellipsis size={22} strokeWidth={moreActive || open ? 2.4 : 2} aria-hidden />
                <Badge n={unread} className="absolute -right-0.5 -top-1.5" />
              </span>
              <span className="l-vi">Thêm</span>
              <span className="l-en">More</span>
            </button>
          </li>
          {/* Desktop rail: the "More" places listed directly */}
          <li className="hidden px-3 pb-1 pt-5 text-xs font-bold uppercase tracking-wide text-ink-3 lg:block" aria-hidden>
            <span className="l-vi">Thêm</span>
            <span className="l-en">More</span>
          </li>
          {MORE.map(({ href, vi, en, Icon, prefetch }) => {
            const active = isActive(path, href);
            return (
              <li key={href} className="hidden lg:block">
                <Link href={`${href}${q}`} prefetch={prefetch} aria-current={active ? "page" : undefined} className={tabCls(active)}>
                  <Icon size={22} strokeWidth={active ? 2.4 : 2} aria-hidden />
                  <span className="l-vi">{vi}</span>
                  <span className="l-en">{en}</span>
                  {href === "/alerts" && <Badge n={unread} className="ml-auto" />}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </>
  );
}
