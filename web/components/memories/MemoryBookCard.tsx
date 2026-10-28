import Link from "next/link";
import { ArrowRight, BookHeart } from "lucide-react";
import { getMemories } from "@/lib/memories";
import { T } from "@/components/T";

/** Small Today-page link to the memory book (fetches its own counts; renders nothing while sharing is paused). */
export async function MemoryBookCard({ elderId }: { elderId: string }) {
  const { data: m } = await getMemories(elderId);
  if (m.sharing_paused) return null;
  const latest = [...m.stories].sort((a, b) => (b.day ?? 0) - (a.day ?? 0))[0];
  const h = m.honorific === "ông" ? "ông" : "bà";
  return (
    <Link
      href={`/memories?elder=${elderId}`}
      className="flex min-h-14 items-center justify-between gap-3 rounded-2xl border border-line bg-surface px-4 py-3 transition-colors duration-150 hover:border-line-strong"
    >
      <span className="flex min-w-0 items-center gap-3">
        <span className="grid size-10 shrink-0 place-items-center rounded-full bg-accent-tint text-accent">
          <BookHeart size={20} aria-hidden />
        </span>
        <span className="min-w-0">
          <span className="block font-semibold">
            <T vi={`Sổ ký ức · ${m.stories.length} chuyện ${h} kể`} en={`Memory book · ${m.stories.length} stories`} />
          </span>
          <span className="line-clamp-2 text-sm text-ink-3 wrap-anywhere" title={latest ? `${latest.title_vi} / ${latest.title_en}` : undefined}>
            {latest ? (
              <T vi={`Mới nhất: ${latest.title_vi}`} en={`Latest: ${latest.title_en}`} />
            ) : (
              <T vi="Chưa có chuyện nào được chia sẻ" en="No shared stories yet" />
            )}
          </span>
        </span>
      </span>
      <ArrowRight size={18} className="shrink-0 text-ink-3" aria-hidden />
    </Link>
  );
}
