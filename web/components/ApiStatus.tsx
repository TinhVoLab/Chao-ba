"use client";
import { useEffect, useState } from "react";
import { API_BASE } from "@/lib/config";
import { T } from "./T";

export function ApiStatus() {
  const [state, setState] = useState<"checking" | "up" | "down">("checking");
  const [llm, setLlm] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    fetch(`${API_BASE}/api/health`, { signal: AbortSignal.timeout(3000) })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((j: { llm?: string }) => {
        if (!alive) return;
        setState("up");
        setLlm(j.llm ?? null);
      })
      .catch(() => alive && setState("down"));
    return () => {
      alive = false;
    };
  }, []);
  const dot = state === "up" ? "bg-green" : state === "down" ? "bg-red" : "bg-gray";
  return (
    <p className="flex items-center gap-2 text-[0.9375rem] text-ink-2" role="status">
      <span className={`size-2.5 rounded-full ${dot}`} aria-hidden />
      {state === "checking" && <T vi="Đang kiểm tra máy chủ…" en="Checking the server…" />}
      {state === "up" && (
        <T
          vi={`Máy chủ đang chạy (${API_BASE})${llm ? `, hội thoại: ${llm === "claude" ? "Claude" : "chế độ dự phòng"}` : ""}`}
          en={`Server is up (${API_BASE})${llm ? `, conversation: ${llm === "claude" ? "Claude" : "fallback mode"}` : ""}`}
        />
      )}
      {state === "down" && (
        <T
          vi={`Chưa kết nối được máy chủ ${API_BASE}. Hãy chạy API rồi thử lại.`}
          en={`Can't reach ${API_BASE}. Start the API and try again.`}
        />
      )}
    </p>
  );
}
