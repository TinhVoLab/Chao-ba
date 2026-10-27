import { CloudOff } from "lucide-react";
import { T } from "./T";

/** Shown whenever a write did not reach the server and is waiting in the outbox (lib/outbox.ts). */
export function NotSaved({ className = "" }: { className?: string }) {
  return (
    <p className={`flex items-start gap-2 rounded-xl bg-yellow-tint px-3 py-2 text-sm font-medium text-yellow-ink ${className}`} role="status">
      <CloudOff size={16} className="mt-0.5 shrink-0" aria-hidden />
      <span>
        <T
          vi="Chưa lưu được — đã giữ trên máy này. Sẽ tự gửi lại khi kết nối được máy chủ."
          en="Not saved — kept on this device. It will be sent again when the server is reachable."
        />
      </span>
    </p>
  );
}

/** A write the server refused (not kept, not retried). */
export function SaveRefused({ detail, className = "" }: { detail?: string; className?: string }) {
  return (
    <p className={`rounded-xl bg-red-tint px-3 py-2 text-sm font-medium text-red-ink ${className}`} role="alert">
      {detail === "storage" ? (
        <T
          vi="Không lưu được: trình duyệt chặn lưu trên máy nên không giữ lại được. Hãy thử lại."
          en="Not saved: this browser blocks local storage, so it could not be kept. Please try again."
        />
      ) : (
        <>
          <T vi="Không lưu được: máy chủ từ chối yêu cầu." en="Not saved: the server refused the request." />
          {detail && detail !== "network" ? <span className="block font-normal opacity-90">{detail}</span> : null}
        </>
      )}
    </p>
  );
}
