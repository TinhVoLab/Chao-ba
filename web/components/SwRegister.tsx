"use client";
import { useEffect } from "react";

export function SwRegister() {
  useEffect(() => {
    if (process.env.NODE_ENV === "production" && "serviceWorker" in navigator) {
      // Offline caching is optional: the app works without it, so a failed registration is only logged.
      navigator.serviceWorker.register("/sw.js").catch((e: unknown) => console.warn("service worker not registered", e));
    }
  }, []);
  return null;
}
