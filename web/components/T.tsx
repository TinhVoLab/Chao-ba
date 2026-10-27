import type { ReactNode } from "react";

/** Bilingual text. Both render; CSS keyed on html[data-lang] shows one (no flash, works in server components). */
export function T({ vi, en }: { vi: ReactNode; en: ReactNode }) {
  return (
    <>
      <span className="l-vi" lang="vi">
        {vi}
      </span>
      <span className="l-en" lang="en">
        {en}
      </span>
    </>
  );
}
