import { Suspense } from "react";
import type { Metadata } from "next";
import { loadElderContext } from "@/lib/api";
import { getMemories } from "@/lib/memories";
import { PageHeader, Disclaimer } from "@/components/PageHeader";
import { PageSkeleton } from "@/components/Skeletons";
import { MemoryBook, PrivateCount } from "@/components/memories/MemoryBook";
import { ExportButton } from "@/components/memories/ExportButton";
import { T } from "@/components/T";

export const metadata: Metadata = { title: "Sổ ký ức / Memory book" };

export default function MemoriesPage({ searchParams }: PageProps<"/memories">) {
  return (
    <Suspense fallback={<PageSkeleton rows={4} />}>
      <MemoriesContent searchParams={searchParams} />
    </Suspense>
  );
}

async function MemoriesContent({ searchParams }: { searchParams: PageProps<"/memories">["searchParams"] }) {
  const sp = await searchParams;
  const ctx = await loadElderContext(sp.elder);
  const id = ctx.elder.id;
  const mem = await getMemories(id);
  const m = mem.data;
  const h = m.honorific === "ông" ? "ông" : "bà";
  const nameEn = ctx.elder.name_en;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={<T vi="Sổ ký ức" en="Memory book" />}
        elders={ctx.elders}
        current={id}
        path="/memories"
        simulated={m.simulated !== false}
        live={ctx.live && mem.live}
      />
      <p className="max-w-[65ch] text-[1.0625rem] leading-relaxed text-ink-2">
        <T
          vi={`Mỗi sáng Út Thương hỏi ${h} một chuyện xưa: thời nhỏ, ngày cưới, món ăn, quê nhà… Chuyện nào ${h} đồng ý kể lại thì được ghi vào sổ cho con cháu. Nhớ lại chuyện cũ cũng là cách giữ trí nhớ dẻo dai.`}
          en={`Each morning Út Thương asks ${nameEn} about one memory: childhood, the wedding, food, home… Stories ${m.honorific === "ông" ? "he" : "she"} agrees to share are written into this book for the family. Remembering old stories is good exercise for the mind, too.`}
        />
      </p>

      {m.sharing_paused ? (
        <p className="rounded-2xl border border-line bg-surface p-4 font-medium">
          <T vi="Sổ ký ức đang ẩn vì chia sẻ với gia đình đã tạm dừng." en="The memory book is hidden while sharing with the family is paused." />
        </p>
      ) : (
        <>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-sm font-semibold text-ink-2 tnum">
              <T
                vi={`${m.stories.length} chuyện được chia sẻ · ${m.themes.length} chủ đề`}
                en={`${m.stories.length} shared ${m.stories.length === 1 ? "story" : "stories"} · ${m.themes.length} themes`}
              />
            </p>
            <ExportButton elderId={id} disabled={m.stories.length === 0} />
          </div>
          {m.private_count > 0 && <PrivateCount n={m.private_count} honorific={h} />}
          <MemoryBook m={m} />
        </>
      )}
      <Disclaimer />
    </div>
  );
}
