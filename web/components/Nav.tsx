"use client";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Bell, ChartLine, RefreshCw, ShieldCheck, Sunrise } from "lucide-react";

const TABS = [
  { href: "/", vi: "Hôm nay", en: "Today", Icon: Sunrise },
  { href: "/trends", vi: "Xu hướng", en: "Trends", Icon: ChartLine },
  { href: "/alerts", vi: "Cảnh báo", en: "Alerts", Icon: Bell },
  { href: "/dmaic", vi: "DMAIC", en: "DMAIC", Icon: RefreshCw },
  { href: "/privacy", vi: "Riêng tư", en: "Privacy", Icon: ShieldCheck },
];

/** Bottom tab bar on phones, side rail on desktop. Keeps the selected elder across tabs. */
export function Nav() {
  const path = usePathname();
  const sp = useSearchParams();
  const elder = sp.get("elder");
  const q = elder ? `?elder=${encodeURIComponent(elder)}` : "";
  return (
    <nav
      aria-label="Chính / Main"
      className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-surface/95 backdrop-blur-sm pb-safe lg:inset-y-0 lg:left-0 lg:right-auto lg:w-56 lg:border-r lg:border-t-0 lg:bg-surface lg:pt-24"
    >
      <ul className="mx-auto grid max-w-xl grid-cols-5 lg:flex lg:flex-col lg:gap-1 lg:px-3">
        {TABS.map(({ href, vi, en, Icon }) => {
          const active = href === "/" ? path === "/" : path.startsWith(href);
          return (
            <li key={href}>
              <Link
                href={`${href}${q}`}
                aria-current={active ? "page" : undefined}
                className={`group flex min-h-16 flex-col items-center justify-center gap-1 text-[0.75rem] font-semibold transition-colors duration-150 lg:min-h-12 lg:flex-row lg:justify-start lg:gap-3 lg:rounded-xl lg:px-3 lg:text-base ${
                  active ? "text-accent lg:bg-accent-tint" : "text-ink-3 hover:text-ink"
                }`}
              >
                <span
                  className={`grid h-8 w-14 place-items-center rounded-full transition-colors duration-200 lg:h-auto lg:w-auto ${
                    active ? "bg-accent-tint lg:bg-transparent" : ""
                  }`}
                >
                  <Icon size={22} strokeWidth={active ? 2.4 : 2} aria-hidden />
                </span>
                <span className="l-vi">{vi}</span>
                <span className="l-en">{en}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
