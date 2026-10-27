import { Suspense } from "react";
import type { Metadata } from "next";
import { getPrivacy, getProfile, loadElderContext } from "@/lib/api";
import { PageHeader, Disclaimer } from "@/components/PageHeader";
import { PageSkeleton } from "@/components/Skeletons";
import { PrivacyView } from "@/components/PrivacyView";
import { T } from "@/components/T";

export const metadata: Metadata = { title: "Quyền riêng tư / Privacy" };

export default function PrivacyPage({ searchParams }: PageProps<"/privacy">) {
  return (
    <Suspense fallback={<PageSkeleton rows={3} />}>
      <PrivacyContent searchParams={searchParams} />
    </Suspense>
  );
}

async function PrivacyContent({ searchParams }: { searchParams: PageProps<"/privacy">["searchParams"] }) {
  const sp = await searchParams;
  const ctx = await loadElderContext(sp.elder);
  const [pv, profile] = await Promise.all([getPrivacy(ctx.elder.id), getProfile(ctx.elder.id)]);
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={<T vi="Quyền riêng tư" en="Privacy" />}
        elders={ctx.elders}
        current={ctx.elder.id}
        path="/privacy"
        simulated={pv.data.simulated ?? ctx.elder.simulated !== false}
        live={ctx.live && pv.live}
      />
      <PrivacyView
        key={ctx.elder.id}
        privacy={pv.data}
        elderId={ctx.elder.id}
        elderVi={ctx.elder.display_name}
        elderEn={ctx.elder.name_en}
        family={profile.data.family ?? []}
        live={ctx.live && pv.live}
      />
      <Disclaimer />
    </div>
  );
}
