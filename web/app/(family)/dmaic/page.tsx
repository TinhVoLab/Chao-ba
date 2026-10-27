import { Suspense } from "react";
import type { Metadata } from "next";
import { getDmaic, getTimeline, loadElderContext } from "@/lib/api";
import { PageHeader, Disclaimer } from "@/components/PageHeader";
import { PageSkeleton } from "@/components/Skeletons";
import { DmaicView } from "@/components/DmaicView";
import { T } from "@/components/T";

export const metadata: Metadata = { title: "DMAIC" };

export default function DmaicPage({ searchParams }: PageProps<"/dmaic">) {
  return (
    <Suspense fallback={<PageSkeleton rows={3} />}>
      <DmaicContent searchParams={searchParams} />
    </Suspense>
  );
}

async function DmaicContent({ searchParams }: { searchParams: PageProps<"/dmaic">["searchParams"] }) {
  const sp = await searchParams;
  const ctx = await loadElderContext(sp.elder);
  const [dmaic, tl] = await Promise.all([getDmaic(ctx.elder.id), getTimeline(ctx.elder.id, 90)]);
  const dates: Record<number, string> = {};
  for (const r of tl.data.records ?? []) dates[r.day] = r.date;
  for (const l of tl.data.lights ?? []) dates[l.day] ??= l.date;
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={<T vi="Chu trình chăm sóc" en="Care cycle" />}
        elders={ctx.elders}
        current={ctx.elder.id}
        path="/dmaic"
        simulated={dmaic.data.simulated ?? ctx.elder.simulated !== false}
        live={ctx.live && dmaic.live && tl.live}
      />
      <p className="max-w-[65ch] text-ink-2">
        <T
          vi="DMAIC là vòng cải tiến 5 bước: Xác định, Đo lường, Phân tích, Cải thiện, Kiểm soát. Mỗi thay đổi kéo dài được xử lý như một vòng, có ngày tháng và kết quả đo được."
          en="DMAIC is a five-step improvement loop: Define, Measure, Analyze, Improve, Control. Each lasting change is handled as one loop, with dates and a measured result."
        />
      </p>
      <DmaicView
        key={ctx.elder.id}
        dmaic={dmaic.data}
        lights={tl.data.lights ?? []}
        dates={dates}
        elderVi={ctx.elder.display_name}
        elderEn={ctx.elder.name_en}
      />
      <Disclaimer />
    </div>
  );
}
