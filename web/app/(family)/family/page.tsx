import { Suspense } from "react";
import type { Metadata } from "next";
import { getFamily, getFamilyTimeline, getProfile, loadElderContext } from "@/lib/api";
import { kin } from "@/lib/format";
import { PageHeader, Disclaimer } from "@/components/PageHeader";
import { PageSkeleton } from "@/components/Skeletons";
import { AccessCard, SynthesisCard, ViewerNotice } from "@/components/family/FamilyCards";
import { SuggestionsCard } from "@/components/family/SuggestionsCard";
import { RotaCard } from "@/components/family/RotaCard";
import { TasksCard } from "@/components/family/TasksCard";
import { FamilyFeed } from "@/components/family/FamilyFeed";
import { T } from "@/components/T";

export const metadata: Metadata = { title: "Gia đình / Family" };

export default function FamilyPage({ searchParams }: PageProps<"/family">) {
  return (
    <Suspense fallback={<PageSkeleton rows={5} />}>
      <FamilyContent searchParams={searchParams} />
    </Suspense>
  );
}

async function FamilyContent({ searchParams }: { searchParams: PageProps<"/family">["searchParams"] }) {
  const sp = await searchParams;
  const ctx = await loadElderContext(sp.elder);
  const id = ctx.elder.id;
  const [fam, feed, profile] = await Promise.all([getFamily(id), getFamilyTimeline(id, 14), getProfile(id)]);
  const o = fam.data;
  const k = kin(profile.data.honorific);
  const live = ctx.live && fam.live && feed.live;
  const fromDate = feed.data.items.at(-1)?.date ?? null;
  // A fresh key per viewer + elder resets client state (drafts, optimistic ticks) when "Viewing as" changes.
  const key = `${id}-${o.viewer.member_id ?? o.viewer.name}`;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={<T vi="Gia đình" en="Family" />}
        elders={ctx.elders}
        current={id}
        path="/family"
        simulated={o.simulated !== false}
        live={live}
      />
      <ViewerNotice o={o} />
      {/* Phone: one column in reading order (columns use display:contents + order). Desktop: two columns. */}
      <div className="flex flex-col gap-8 lg:grid lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] lg:items-start">
        <div className="contents lg:flex lg:flex-col lg:gap-8">
          <div className="order-1 lg:order-none">
            <SynthesisCard s={o.synthesis} kinVi={k.vi} kinEn={k.en} />
          </div>
          <div className="order-2 lg:order-none">
            <SuggestionsCard key={`s-${key}`} elderId={id} data={o.suggestions} kinVi={k.vi} kinEn={k.en} />
          </div>
          <div className="order-5 lg:order-none">
            <FamilyFeed items={feed.data.items} fromDate={fromDate} />
          </div>
        </div>
        <div className="contents lg:flex lg:flex-col lg:gap-8">
          <div className="order-3 lg:order-none">
            <RotaCard key={`r-${key}`} elderId={id} rota={o.rota} members={o.members} viewer={o.viewer} kinVi={k.vi} kinEn={k.en} />
          </div>
          <div className="order-4 lg:order-none">
            <TasksCard key={`t-${key}`} elderId={id} tasks={o.tasks} members={o.members} viewer={o.viewer} todayIso={o.rota.today.date} />
          </div>
          <div className="order-6 lg:order-none">
            <AccessCard o={o} kinVi={k.vi} kinEn={k.en} />
          </div>
        </div>
      </div>
      <Disclaimer />
    </div>
  );
}
