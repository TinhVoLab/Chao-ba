import { Suspense } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { LangToggle } from "@/components/Controls";
import { StandingScreen } from "@/components/StandingScreen";
import { getProfile, loadElderContext } from "@/lib/api";
import { T } from "@/components/T";

export const metadata: Metadata = { title: "Màn hình đứng / Standing screen" };

const ELDERS = [
  ["hanh", "Bà Hạnh"],
  ["tu", "Ông Tư"],
  ["control", "Ông Bảy"],
];

async function ScreenContent({ searchParams }: { searchParams: PageProps<"/screen">["searchParams"] }) {
  const sp = await searchParams;
  const ctx = await loadElderContext(sp.elder);
  const profile = await getProfile(ctx.elder.id);
  return <StandingScreen key={ctx.elder.id} profile={profile.data} />;
}

export default function ScreenPage({ searchParams }: PageProps<"/screen">) {
  return (
    <div className="flex min-h-dvh flex-col items-center bg-[#15110e] text-[#f6efe2]">
      <div className="flex h-16 w-full max-w-3xl items-center justify-between gap-2 px-4">
        <Link href="/" className="inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-[#f6efe2]/80 hover:text-[#f6efe2]">
          <ArrowLeft size={18} aria-hidden />
          <T vi="Ứng dụng gia đình" en="Family app" />
        </Link>
        <nav aria-label="Người thân / Elder" className="hidden gap-1 text-sm sm:flex">
          {ELDERS.map(([id, name]) => (
            <Link key={id} href={`/screen?elder=${id}`} className="min-h-11 content-center rounded-full px-3 text-[#f6efe2]/75 hover:bg-white/10 hover:text-[#f6efe2]">
              {name}
            </Link>
          ))}
        </nav>
        <div style={{ ["--ink" as string]: "#f6efe2", ["--bg" as string]: "#15110e", ["--ink-2" as string]: "#f6efe2cc", ["--line-strong" as string]: "#ffffff40" }}>
          <LangToggle />
        </div>
      </div>
      <Suspense fallback={<div className="aspect-[9/16] h-[calc(100dvh-4rem)] max-w-full rounded-3xl bg-[#241b15]" />}>
        <ScreenContent searchParams={searchParams} />
      </Suspense>
    </div>
  );
}
