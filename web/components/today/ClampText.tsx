"use client";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { useLang } from "@/lib/useLang";
import { T } from "../T";

const CLAMP = { 2: "line-clamp-2", 3: "line-clamp-3", 4: "line-clamp-4", 5: "line-clamp-5", 6: "line-clamp-6" } as const;

/**
 * Long text clamped to a few lines, with "Xem thêm / Show more" only when it actually overflows (re-measured on
 * resize and on a language switch, since both languages render and CSS shows one).
 */
export function ClampText({
  children,
  lines = 4,
  className = "",
  as: Tag = "p",
}: {
  children: ReactNode;
  lines?: keyof typeof CLAMP;
  className?: string;
  as?: "p" | "div";
}) {
  const lang = useLang();
  const ref = useRef<HTMLElement>(null);
  const id = useId();
  const [open, setOpen] = useState(false);
  const [overflows, setOverflows] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el || open) return;
    const check = () => setOverflows(el.scrollHeight > el.clientHeight + 2);
    check();
    const ro = new ResizeObserver(check);
    ro.observe(el);
    return () => ro.disconnect();
  }, [lang, open]);

  return (
    <div className="flex min-w-0 flex-col items-start">
      <Tag ref={ref as never} id={id} className={`min-w-0 wrap-anywhere ${open ? "" : CLAMP[lines]} ${className}`}>
        {children}
      </Tag>
      {(overflows || open) && (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-controls={id}
          className="-ml-1 mt-0.5 inline-flex min-h-11 items-center gap-1 rounded-full px-1 text-sm font-semibold text-accent"
        >
          {open ? <ChevronUp size={16} aria-hidden /> : <ChevronDown size={16} aria-hidden />}
          {open ? <T vi="Thu gọn" en="Show less" /> : <T vi="Xem thêm" en="Show more" />}
        </button>
      )}
    </div>
  );
}
