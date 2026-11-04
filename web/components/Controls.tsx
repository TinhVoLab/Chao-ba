"use client";
import { Moon, Sun } from "lucide-react";
import { setLang } from "@/lib/useLang";

export function LangToggle() {
  return (
    <div role="group" aria-label="Ngôn ngữ / Language" className="flex rounded-full border border-line-strong p-0.5 text-sm font-semibold">
      {(["vi", "en"] as const).map((l) => (
        <button
          key={l}
          type="button"
          data-lang-opt={l}
          onClick={() => setLang(l)}
          className="min-h-11 min-w-11 rounded-full px-2.5 text-ink-2 transition-colors duration-150"
        >
          {l.toUpperCase()}
        </button>
      ))}
    </div>
  );
}

export function ThemeToggle() {
  function toggle() {
    const d = document.documentElement;
    const current = d.dataset.theme ?? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const next = current === "dark" ? "light" : "dark";
    d.dataset.theme = next;
    try {
      localStorage.setItem("cb-theme", next);
    } catch {}
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", next === "dark" ? "#22201c" : "#f7f3ec");
  }
  return (
    <button
      type="button"
      onClick={toggle}
      className="grid size-11 place-items-center rounded-full border border-line-strong text-ink-2 transition-colors duration-150 hover:text-ink"
    >
      <span className="only-light" aria-hidden>
        <Moon size={18} />
      </span>
      <span className="only-dark" aria-hidden>
        <Sun size={18} />
      </span>
      <span className="sr-only">Đổi giao diện sáng/tối / Toggle light/dark</span>
    </button>
  );
}
