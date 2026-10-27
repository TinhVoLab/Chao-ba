"use client";
import { useSyncExternalStore } from "react";

export type Lang = "vi" | "en";

function subscribe(cb: () => void) {
  const o = new MutationObserver(cb);
  o.observe(document.documentElement, { attributes: true, attributeFilter: ["data-lang"] });
  return () => o.disconnect();
}

/** Current UI language for client-only strings (attributes, chart tooltips). */
export function useLang(): Lang {
  return useSyncExternalStore(
    subscribe,
    () => (document.documentElement.dataset.lang === "en" ? "en" : "vi"),
    () => "vi",
  );
}

export function setLang(lang: Lang) {
  document.documentElement.dataset.lang = lang;
  document.documentElement.lang = lang;
  try {
    localStorage.setItem("cb-lang", lang);
  } catch {}
}

const LS_EVENT = "cb-local";
function lsSubscribe(cb: () => void) {
  window.addEventListener(LS_EVENT, cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener(LS_EVENT, cb);
    window.removeEventListener("storage", cb);
  };
}

/** Reads a localStorage value reactively (null on the server / when blocked). */
export function useLocal(key: string): string | null {
  return useSyncExternalStore(
    lsSubscribe,
    () => {
      try {
        return localStorage.getItem(key);
      } catch {
        return null;
      }
    },
    () => null,
  );
}

export function writeLocal(key: string, value: string | null) {
  try {
    if (value == null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {}
  window.dispatchEvent(new Event(LS_EVENT));
}
