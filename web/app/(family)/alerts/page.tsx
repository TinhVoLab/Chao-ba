import { Suspense } from "react";
import type { Metadata } from "next";
import { getAlerts, loadElderContext } from "@/lib/api";
import { PageHeader, Disclaimer } from "@/components/PageHeader";
import { PageSkeleton } from "@/components/Skeletons";
import { AlertsList } from "@/components/AlertsList";
import { T } from "@/components/T";

export const metadata: Metadata = { title: "Cảnh báo / Alerts" };

export default function AlertsPage({ searchParams }: PageProps<"/alerts">) {
  return (
    <Suspense fallback={<PageSkeleton rows={4} />}>
      <AlertsContent searchParams={searchParams} />
    </Suspense>
  );
}

async function AlertsContent({ searchParams }: { searchParams: PageProps<"/alerts">["searchParams"] }) {
  const sp = await searchParams;
  const ctx = await loadElderContext(sp.elder);
  const alerts = await getAlerts(ctx.elder.id);
  const list = Array.isArray(alerts.data) ? alerts.data : [];
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={<T vi="Cảnh báo" en="Alerts" />}
        elders={ctx.elders}
        current={ctx.elder.id}
        path="/alerts"
        simulated={ctx.elder.simulated !== false}
        live={ctx.live && alerts.live}
      />
      <AlertsList key={ctx.elder.id} elderId={ctx.elder.id} initial={list} />
      <Disclaimer />
    </div>
  );
}
