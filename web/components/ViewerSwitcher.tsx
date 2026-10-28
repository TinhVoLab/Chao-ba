"use client";
import { useEffect, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Check, ChevronDown, Eye, UserRound } from "lucide-react";
import { circleFor, setClientViewer } from "@/lib/viewer";
import { T } from "./T";

const ROLE = {
  primary: { vi: "người chăm sóc chính · xem đầy đủ", en: "primary carer · full view" },
  viewer: { vi: "người nhà · xem tóm tắt", en: "family · summary view" },
};

/**
 * "Đang xem với tư cách / Viewing as": picks which care-circle member is using the app (no login in the prototype).
 * The choice is a cookie, so server reads and writes carry the same X-Actor / X-Role and the access log shows it.
 */
export function ViewerSwitcher({ elderId, memberId }: { elderId: string; memberId: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, start] = useTransition();
  const ref = useRef<HTMLDivElement>(null);
  const circle = circleFor(elderId);
  const me = circle.find((m) => m.id === memberId) ?? circle[0];

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const key = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    window.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", close);
      window.removeEventListener("keydown", key);
    };
  }, [open]);

  function pick(id: string) {
    setOpen(false);
    if (id === me.id) return;
    setClientViewer(elderId, id);
    start(() => router.refresh());
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-controls="viewer-list"
        title={me.name}
        className={`flex min-h-11 w-full items-center gap-2.5 rounded-2xl border border-line bg-surface px-3 py-1.5 text-left transition-colors duration-150 hover:border-line-strong sm:w-auto ${
          pending ? "opacity-60" : ""
        }`}
      >
        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-accent-tint text-sm font-bold text-accent">
          {me.name.replace(/^Bà /, "").charAt(0)}
        </span>
        <span className="min-w-0 flex-1 leading-tight">
          <span className="block truncate text-[0.9375rem]">
            <span className="text-ink-2">
              <T vi="Đang xem với tư cách" en="Viewing as" />
            </span>{" "}
            <span className="font-semibold">{me.name}</span>
          </span>
          <span className="block truncate text-sm text-ink-3">
            <T vi={ROLE[me.role].vi} en={ROLE[me.role].en} />
          </span>
        </span>
        <ChevronDown size={18} className={`shrink-0 text-ink-3 transition-transform duration-150 ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>
      {open && (
        <ul
          id="viewer-list"
          role="listbox"
          aria-label="Đang xem với tư cách / Viewing as"
          className="fade-in absolute left-0 right-0 top-full z-40 mt-1.5 overflow-hidden rounded-2xl border border-line bg-surface p-1 shadow-soft sm:right-auto sm:min-w-80"
        >
          {circle.map((m) => {
            const sel = m.id === me.id;
            return (
              <li key={m.id} role="option" aria-selected={sel}>
                <button
                  type="button"
                  onClick={() => pick(m.id)}
                  className={`flex min-h-14 w-full items-center gap-3 rounded-xl px-3 py-2 text-left transition-colors duration-150 ${
                    sel ? "bg-accent-tint" : "hover:bg-surface-2"
                  }`}
                >
                  <span className="grid size-8 shrink-0 place-items-center rounded-full bg-surface-2 text-ink-2">
                    {m.role === "primary" ? <UserRound size={16} aria-hidden /> : <Eye size={16} aria-hidden />}
                  </span>
                  <span className="min-w-0 flex-1 leading-tight">
                    <span className="block font-semibold wrap-anywhere">
                      {m.name}{" "}
                      <span className="font-normal text-ink-3">
                        · <T vi={`${m.relVi}, ${m.city}`} en={`${m.relEn}, ${m.city}`} />
                      </span>
                    </span>
                    <span className="block text-sm text-ink-2">
                      <T vi={ROLE[m.role].vi} en={ROLE[m.role].en} />
                    </span>
                  </span>
                  {sel && <Check size={18} className="shrink-0 text-accent" aria-hidden />}
                </button>
              </li>
            );
          })}
          <li className="px-3 pb-2 pt-1 text-xs text-ink-3">
            <T
              vi="Bản mẫu chưa có đăng nhập: chọn người để thấy quyền xem khác nhau. Mỗi lần xem đều được ghi lại."
              en="The prototype has no login: pick a person to see how permissions differ. Every view is logged."
            />
          </li>
        </ul>
      )}
    </div>
  );
}
