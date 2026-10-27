import { Suspense } from "react";
import type { Metadata } from "next";
import { getTimeline, loadElderContext } from "@/lib/api";
import { PageHeader, Disclaimer } from "@/components/PageHeader";
import { PageSkeleton } from "@/components/Skeletons";
import { TrendsView } from "@/components/TrendsView";
import { T } from "@/components/T";

export const metadata: Metadata = { title: "Xu hướng / Trends" };

export default function TrendsPage({ searchParams }: PageProps<"/trends">) {
  return (
    <Suspense fallback={<PageSkeleton rows={4} />}>
      <TrendsContent searchParams={searchParams} />
    </Suspense>
  );
}

async function TrendsContent({ searchParams }: { searchParams: PageProps<"/trends">["searchParams"] }) {
  const sp = await searchParams;
  const ctx = await loadElderContext(sp.elder);
  const tl = await getTimeline(ctx.elder.id, 90);
  const simulated = tl.data.simulated ?? (tl.data.records ?? []).some((r) => r.simulated !== false);
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={<T vi="Xu hướng" en="Trends" />}
        elders={ctx.elders}
        current={ctx.elder.id}
        path="/trends"
        simulated={simulated}
        live={ctx.live && tl.live}
      />
      <p className="max-w-[65ch] text-ink-2">
        <T
          vi={`Mỗi chỉ số của ${ctx.elder.display_name} được so với chính ${ctx.elder.display_name.split(" ")[0].toLowerCase()}, không so với người khác. Vạch dưới mỗi biểu đồ là đèn từng ngày.`}
          en={`Each signal for ${ctx.elder.name_en} is compared with their own usual level, never with other people. The strip under each chart is the daily light.`}
        />
      </p>
      <TrendsView timeline={tl.data} />
      <Disclaimer />
    </div>
  );
}
