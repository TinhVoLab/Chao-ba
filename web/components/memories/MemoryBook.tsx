import { Noto_Serif } from "next/font/google";
import { FlaskConical, Lock, MapPin, MicOff, Users } from "lucide-react";
import type { Memories, Story } from "@/lib/memories";
import { shortDate } from "@/lib/format";
import { T } from "@/components/T";

const serif = Noto_Serif({ subsets: ["latin", "vietnamese"], weight: ["400", "600"], style: ["normal", "italic"], display: "swap" });

/** Chapters by theme (the API's theme order); inside a chapter, oldest era first. */
function chapters(m: Memories) {
  const byTheme = new Map<string, Story[]>();
  for (const s of m.stories) byTheme.set(s.theme, [...(byTheme.get(s.theme) ?? []), s]);
  return m.themes
    .filter((t) => byTheme.has(t.theme))
    .map((t) => ({
      ...t,
      stories: [...(byTheme.get(t.theme) ?? [])].sort(
        (a, b) => (a.era.decade ?? 9999) - (b.era.decade ?? 9999) || (a.day ?? 0) - (b.day ?? 0),
      ),
    }));
}

export function PrivateCount({ n, honorific }: { n: number; honorific: string }) {
  const h = honorific === "ông" ? "ông" : "bà";
  const he = honorific === "ông" ? "he" : "she";
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-line bg-surface px-4 py-3">
      <span className="grid size-10 shrink-0 place-items-center rounded-full bg-surface-2 text-ink-2">
        <Lock size={18} aria-hidden />
      </span>
      <p className="text-[0.9375rem] leading-snug">
        <span className="block font-semibold">
          <T vi={`${n} chuyện ${h} giữ riêng`} en={`${n} ${n === 1 ? "story" : "stories"} kept private`} />
        </span>
        <span className="block text-ink-3">
          <T
            vi={`Chỉ ${h} xem được. Út Thương hỏi ${h} trước khi kể lại bất kỳ chuyện nào.`}
            en={`Only ${he} can see ${n === 1 ? "it" : "them"}. Út Thương asks before retelling any story.`}
          />
        </span>
      </p>
    </div>
  );
}

function StoryCard({ s }: { s: Story }) {
  const gist = s.translation === "gist";
  return (
    <article className="flex flex-col gap-3 rounded-[22px] border border-line bg-surface p-5 shadow-[var(--shadow)]">
      <header className="flex flex-col gap-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.8125rem] font-medium text-ink-3">
          {(s.era.label_vi || s.era.label_en) && (
            <span className="rounded-full bg-accent-tint px-2.5 py-0.5 text-accent">
              <T vi={s.era.label_vi ?? ""} en={s.era.label_en ?? ""} />
            </span>
          )}
          {s.date && (
            <span>
              <T vi={`Kể ngày ${shortDate(s.date)}`} en={`Told ${shortDate(s.date)}`} />
            </span>
          )}
          {s.simulated && (
            <span className="inline-flex items-center gap-1" title="Dữ liệu mô phỏng / Simulated data">
              <FlaskConical size={13} aria-hidden />
              <T vi="mô phỏng" en="simulated" />
            </span>
          )}
        </div>
        <h3 className={`${serif.className} text-[1.3125rem] font-semibold leading-snug`}>
          <T vi={s.title_vi} en={s.title_en} />
        </h3>
      </header>
      <blockquote className={`${serif.className} text-[1.0625rem] leading-[1.75] text-ink`}>
        <T
          vi={<>“{s.text_vi}”</>}
          en={
            gist ? (
              <>
                <span className="block">“{s.text_vi}”</span>
                <span className="mt-2 block text-[0.9375rem] italic text-ink-2">{s.text_en}</span>
              </>
            ) : (
              <>“{s.text_en}”</>
            )
          }
        />
      </blockquote>
      {(s.people.length > 0 || s.places.length > 0) && (
        <ul className="flex flex-wrap gap-1.5 text-[0.8125rem] text-ink-2" aria-label="Người và nơi chốn / People and places">
          {s.people.map((p) => (
            <li key={`p-${p.vi}`} className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2.5 py-1">
              <Users size={13} aria-hidden />
              <T vi={p.vi} en={p.en} />
            </li>
          ))}
          {s.places.map((p) => (
            <li key={`l-${p}`} className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2.5 py-1">
              <MapPin size={13} aria-hidden />
              {p}
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}

export function MemoryBook({ m }: { m: Memories }) {
  const chs = chapters(m);
  return (
    <div className="flex flex-col gap-8">
      {chs.length === 0 ? (
        <p className="rounded-2xl border border-dashed border-line-strong p-5 text-ink-2">
          <T
            vi="Chưa có câu chuyện nào được chia sẻ. Mỗi sáng Út Thương hỏi một chuyện xưa; chuyện nào được đồng ý kể lại sẽ hiện ở đây."
            en="No shared stories yet. Each morning Út Thương asks about one memory; stories the teller agrees to share appear here."
          />
        </p>
      ) : (
        chs.map((c, i) => (
          <section key={c.theme} aria-labelledby={`ch-${c.theme}`} className="flex flex-col gap-3">
            <div className="flex items-baseline gap-3 border-b border-line pb-2">
              <span className="text-xs font-bold uppercase tracking-[0.16em] text-accent tnum">
                <T vi={`Chương ${i + 1}`} en={`Chapter ${i + 1}`} />
              </span>
              <h2 id={`ch-${c.theme}`} className={`${serif.className} text-[1.5rem] font-semibold leading-tight`}>
                <T vi={c.label_vi} en={c.label_en} />
              </h2>
              <span className="ml-auto text-sm text-ink-3 tnum">{c.count}</span>
            </div>
            <div className="grid gap-3 lg:grid-cols-2">
              {c.stories.map((s) => (
                <StoryCard key={s.id} s={s} />
              ))}
            </div>
          </section>
        ))
      )}
      <p className="flex items-start gap-2 text-sm text-ink-3">
        <MicOff size={16} className="mt-0.5 shrink-0" aria-hidden />
        <T vi={m.audio.note_vi} en={m.audio.note_en} />
      </p>
    </div>
  );
}
