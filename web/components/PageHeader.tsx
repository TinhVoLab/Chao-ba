import type { ReactNode } from "react";
import type { ElderSummary } from "@/lib/types";
import { ElderSwitcher } from "./ElderSwitcher";
import { DataBadges } from "./Badges";

export function PageHeader({
  title,
  elders,
  current,
  path,
  simulated,
  live,
}: {
  title: ReactNode;
  elders: ElderSummary[];
  current: string;
  path: string;
  simulated: boolean;
  live: boolean;
}) {
  return (
    <header className="flex flex-col gap-4 pt-2">
      <ElderSwitcher elders={elders} current={current} path={path} />
      <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
        <h1 className="text-[1.75rem] font-bold leading-tight tracking-tight">{title}</h1>
        <DataBadges simulated={simulated} live={live} />
      </div>
    </header>
  );
}

export function Disclaimer() {
  return (
    <p className="mt-10 border-t border-line pt-4 text-sm text-ink-3">
      <span className="l-vi">
        Chào Bà so sánh mỗi người với chính họ, không đưa ra chẩn đoán y khoa. Khi lo lắng, hãy hỏi bác sĩ.
      </span>
      <span className="l-en">
        Chào Bà compares each person with their own baseline and does not make medical diagnoses. When worried, ask a doctor.
      </span>
    </p>
  );
}
