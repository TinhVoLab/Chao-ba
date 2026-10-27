"use client";
import { BookDown } from "lucide-react";
import { useLang } from "@/lib/useLang";
import { exportUrl } from "@/lib/memories-shared";

/** Opens the printable memoir (shared stories only) in the current UI language. */
export function ExportButton({ elderId, disabled }: { elderId: string; disabled?: boolean }) {
  const lang = useLang();
  const label = lang === "en" ? "Export memory book" : "Xuất sổ ký ức";
  if (disabled) {
    return (
      <span className="inline-flex min-h-12 items-center gap-2 rounded-full bg-surface-2 px-5 font-semibold text-ink-3" aria-disabled>
        <BookDown size={18} aria-hidden />
        {label}
      </span>
    );
  }
  return (
    <a
      href={exportUrl(elderId, lang)}
      target="_blank"
      rel="noopener"
      className="inline-flex min-h-12 items-center gap-2 rounded-full bg-accent px-5 font-semibold text-accent-ink transition-colors duration-150 hover:bg-accent-hover"
    >
      <BookDown size={18} aria-hidden />
      {label}
    </a>
  );
}
