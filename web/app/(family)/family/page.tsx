import { Suspense } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { Lock } from "lucide-react";
import { getFamily, getFamilyTimeline, getKudosCatalog, getKudosList, getProfile, loadElderContext } from "@/lib/api";
import { kin } from "@/lib/format";
import type { Suggestion, Synthesis, Suggestions } from "@/lib/types";
import { PageHeader, Disclaimer } from "@/components/PageHeader";
import { PageSkeleton } from "@/components/Skeletons";
import { SynthesisCard, ViewerNotice } from "@/components/family/FamilyCards";
import { AskedButton, SuggestionsCard } from "@/components/family/SuggestionsCard";
import { RotaCard } from "@/components/family/RotaCard";
import { TasksCard } from "@/components/family/TasksCard";
import { FamilyFeed } from "@/components/family/FamilyFeed";
import { FamilyTabNav, TodayStrip, familyHref, familyTab } from "@/components/family/FamilyTabs";
import { T } from "@/components/T";
import { KudosTray } from "@/components/kudos/KudosTray";

export const metadata: Metadata = { title: "Gia đình / Family" };

export default function FamilyPage({ searchParams }: PageProps<"/family">) {
  return (
    <Suspense fallback={<PageSkeleton rows={5} />}>
      <FamilyContent searchParams={searchParams} />
    </Suspense>
  );
}

/** The suggestion that repeats the weekly synthesis: the backend adds the synthesis' top topic as `care:<topic>` with
 *  `source: "synthesis"` (family.py `suggestions`). It may be fresh or already asked this week. */
function synthesisTopic(syn: Synthesis, sug: Suggestions): Suggestion | null {
  const top = syn.items[0];
  if (!top) return null;
  const key = `care:${top.topic}`;
  return [...sug.suggestions, ...sug.already_asked].find((s) => s.source === "synthesis" && s.key === key) ?? null;
}

async function FamilyContent({ searchParams }: { searchParams: PageProps<"/family">["searchParams"] }) {
  const sp = await searchParams;
  const tab = familyTab(sp.tab);
  const ctx = await loadElderContext(sp.elder);
  const id = ctx.elder.id;
  // Overview (rota, tasks: the strip) and the family's love notes (new replies: the strip) are always needed;
  // the catalog only for the tray (Check in), the 14-day timeline only for its tab.
  const [fam, profile, kudosFamily, kudosCatalog, feed] = await Promise.all([
    getFamily(id),
    getProfile(id),
    getKudosList(id, "family"),
    tab === "checkin" ? getKudosCatalog(id) : null,
    tab === "timeline" ? getFamilyTimeline(id, 14) : null,
  ]);
  const o = fam.data;
  const k = kin(profile.data.honorific);
  const live = ctx.live && fam.live && (feed?.live ?? true);
  // A fresh key per viewer + elder resets client state (drafts, optimistic ticks) when "Viewing as" changes.
  const key = `${id}-${o.viewer.member_id ?? o.viewer.name}`;
  const dup = synthesisTopic(o.synthesis, o.suggestions);

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
      <div className="flex flex-col gap-3">
        <TodayStrip sp={sp} rota={o.rota} tasks={o.tasks} kudos={kudosFamily.data} kinVi={k.vi} kinEn={k.en} />
        <FamilyTabNav sp={sp} active={tab} />
      </div>

      {tab === "checkin" && (
        <div className="flex flex-col gap-8 lg:grid lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] lg:items-start">
          <div className="flex flex-col gap-8">
            <SynthesisCard
              s={o.synthesis}
              kinVi={k.vi}
              kinEn={k.en}
              action={dup && <AskedButton key={`a-${key}`} elderId={id} topicKey={dup.key} askedBy={dup.asked_by} />}
            />
            <SuggestionsCard key={`s-${key}`} elderId={id} data={o.suggestions} kinVi={k.vi} kinEn={k.en} omitKey={dup?.key} />
          </div>
          <KudosTray
            key={`k-${key}`}
            elderId={id}
            kinVi={k.vi}
            kinEn={k.en}
            catalog={kudosCatalog?.data ?? null}
            initial={kudosFamily.data}
            box="family"
            historyHref={familyHref(sp, "timeline")}
          />
        </div>
      )}

      {tab === "care" && (
        <div className="flex flex-col gap-8 lg:grid lg:grid-cols-2 lg:items-start">
          <RotaCard key={`r-${key}`} elderId={id} rota={o.rota} members={o.members} viewer={o.viewer} kinVi={k.vi} kinEn={k.en} />
          <TasksCard key={`t-${key}`} elderId={id} tasks={o.tasks} members={o.members} viewer={o.viewer} todayIso={o.rota.today.date} />
        </div>
      )}

      {tab === "timeline" && feed && (
        <div className="lg:max-w-3xl">
          <FamilyFeed items={feed.data.items} fromDate={feed.data.items.at(-1)?.date ?? null} kinVi={k.vi} kinEn={k.en} />
        </div>
      )}

      <p className="text-sm text-ink-3">
        <Link
          href={`/privacy?elder=${encodeURIComponent(id)}`}
          className="inline-flex min-h-11 items-center gap-1.5 font-semibold text-ink-2 underline decoration-line-strong underline-offset-4 hover:text-ink"
        >
          <Lock size={14} aria-hidden />
          <T vi={`Ai đã xem thông tin của ${k.vi}? Xem ở mục Quyền riêng tư`} en={`Who looked at ${k.en}'s information? See Privacy`} />
        </Link>
      </p>
      <Disclaimer />
    </div>
  );
}
