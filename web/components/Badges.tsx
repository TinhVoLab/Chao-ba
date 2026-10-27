import { FlaskConical, CloudOff } from "lucide-react";
import { T } from "./T";

/** "Dữ liệu mô phỏng / Simulated data" and "offline demo data" flags. */
export function DataBadges({ simulated, live }: { simulated: boolean; live: boolean }) {
  if (!simulated && live) return null;
  return (
    <div className="flex flex-wrap items-center gap-2 text-[0.8125rem] font-medium">
      {simulated && (
        <span className="inline-flex items-center gap-1.5 rounded-full border border-line-strong px-2.5 py-0.5 text-ink-2">
          <FlaskConical size={14} aria-hidden />
          <span>Dữ liệu mô phỏng</span>
          <span className="text-ink-3" aria-hidden>
            /
          </span>
          <span lang="en">Simulated data</span>
        </span>
      )}
      {!live && (
        <span
          className="inline-flex items-center gap-1.5 rounded-full bg-surface-2 px-2.5 py-0.5 text-ink-2"
          title="API không kết nối được; đang dùng dữ liệu demo đóng gói sẵn / API unreachable; using bundled demo data"
        >
          <CloudOff size={14} aria-hidden />
          <T vi="Dữ liệu demo ngoại tuyến" en="Offline demo data" />
        </span>
      )}
    </div>
  );
}
