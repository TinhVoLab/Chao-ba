import { Suspense } from "react";
import Link from "next/link";
import { ArrowRight, Headphones, MessageCircle } from "lucide-react";
import { getNotes, getProfile, getTimeline, getToday, loadElderContext } from "@/lib/api";
import { LIGHT_HINT, LIGHT_WORD, MOOD_WORD, SYMPTOM_WORD, kin, longDate, shortDate } from "@/lib/format";
import { normNotes } from "@/lib/normalize";
import { PageHeader, Disclaimer } from "@/components/PageHeader";
import { PageSkeleton } from "@/components/Skeletons";
import { StatusShape, lightText, lightTint } from "@/components/StatusShape";
import { TodayActions } from "@/components/TodayActions";
import { T } from "@/components/T";

export default function TodayPage({ searchParams }: PageProps<"/">) {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <TodayContent searchParams={searchParams} />
    </Suspense>
  );
}

async function TodayContent({ searchParams }: { searchParams: PageProps<"/">["searchParams"] }) {
  const sp = await searchParams;
  const ctx = await loadElderContext(sp.elder);
  const id = ctx.elder.id;
  const [today, profile, notes, timeline] = await Promise.all([getToday(id), getProfile(id), getNotes(id), getTimeline(id, 90)]);
  const live = ctx.live && today.live && profile.live && notes.live && timeline.live;
  const t = today.data;
  const p = profile.data;
  const light = t.light ?? "gray";
  const paused = t.sharing_paused === true;
  const word = paused ? { vi: "Đang tạm dừng", en: "Paused" } : (LIGHT_WORD[light] ?? LIGHT_WORD.gray);
  const hint = paused
    ? { vi: "Chia sẻ với gia đình đã được rút lại", en: "Sharing with the family was withdrawn" }
    : (LIGHT_HINT[light] ?? LIGHT_HINT.gray);
  const k = kin(p.honorific);
  const date = longDate(t.date);
  const primary = p.family?.find((f) => f.role === "primary") ?? p.family?.[0];
  const records = timeline.data.records ?? [];
  const noteList = normNotes(notes.data, records);
  const lights = (timeline.data.lights ?? []).slice(-14);
  const rec = records.find((r) => r.day === t.day) ?? records.at(-1);
  // Is the latest record this morning's call? Prefer the API's flag; otherwise compare with today's date in Vietnam.
  const todayVn = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Ho_Chi_Minh" }).format(new Date());
  const isToday = typeof t.is_today === "boolean" ? t.is_today : t.date === todayVn;
  const callLabel = isToday
    ? { vi: t.label_vi || "Cuộc gọi sáng nay với Út Thương", en: t.label_en || "This morning's call with Út Thương" }
    : { vi: t.label_vi || `Cuộc gọi gần nhất với Út Thương · ${date.vi}`, en: t.label_en || `Latest call with Út Thương · ${date.en}` };
  const symptoms = Object.entries(rec?.symptoms ?? {}).filter(([, v]) => v > 0).map(([s]) => SYMPTOM_WORD[s] ?? { vi: s, en: s });

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={<T vi="Hôm nay" en="Today" />}
        elders={ctx.elders}
        current={id}
        path="/"
        simulated={t.simulated !== false || records.some((r) => r.simulated !== false)}
        live={live}
      />

      {/* The light */}
      <section aria-labelledby="light-word" className={`fade-in rounded-[28px] ${lightTint(light)} p-5 sm:p-7`}>
        <div className="flex items-center gap-5">
          <StatusShape light={light} size={104} className="shrink-0 drop-shadow-sm" />
          <div className="min-w-0">
            <p className={`text-sm font-semibold ${lightText(light)}`}>
              {p.display_name} · <T vi={date.vi} en={date.en} />
            </p>
            <h2 id="light-word" className={`text-[2.375rem] font-extrabold leading-[1.05] tracking-tight ${lightText(light)}`}>
              <T vi={word.vi} en={word.en} />
            </h2>
            <p className={`mt-1 text-[0.9375rem] font-medium ${lightText(light)} opacity-90`}>
              <T vi={hint.vi} en={hint.en} />
            </p>
          </div>
        </div>
        <p className="mt-5 max-w-[60ch] text-[1.0625rem] leading-relaxed text-ink">
          <T vi={t.explanation_vi} en={t.explanation_en} />
        </p>
      </section>

      {/* This morning's call */}
      <section aria-labelledby="call-h" className="flex flex-col gap-2">
        <h2 id="call-h" className="flex flex-wrap items-center gap-2 text-sm font-bold uppercase tracking-wide text-ink-3">
          <MessageCircle size={16} aria-hidden />
          <T vi={callLabel.vi} en={callLabel.en} />
          {t.simulated === false && (
            <span className="rounded-full bg-accent-tint px-2 py-0.5 text-xs font-semibold normal-case tracking-normal text-accent">
              <T vi={`Cuộc gọi thật · ngày ${t.day}`} en={`Live call · day ${t.day}`} />
            </span>
          )}
        </h2>
        {paused ? (
          <p className="text-lg font-medium">
            <T vi="Tóm tắt cuộc gọi đang ẩn vì chia sẻ đã tạm dừng." en="Call summaries are hidden while sharing is paused." />{" "}
            <Link href={`/privacy?elder=${id}`} className="font-semibold text-accent underline underline-offset-2">
              <T vi="Quyền riêng tư" en="Privacy" />
            </Link>
          </p>
        ) : t.answered ? (
          <>
            <p className="text-lg leading-snug font-medium">
              <T vi={t.summary_vi} en={t.summary_en} />
            </p>
            <dl className="flex flex-wrap gap-x-5 gap-y-1 text-[0.9375rem] text-ink-2">
              {t.mood != null && MOOD_WORD[t.mood] && (
                <div className="flex gap-1.5">
                  <dt><T vi="Tâm trạng:" en="Mood:" /></dt>
                  <dd className="font-semibold text-ink"><T vi={MOOD_WORD[t.mood].vi} en={MOOD_WORD[t.mood].en} /></dd>
                </div>
              )}
              <div className="flex gap-1.5">
                <dt><T vi="Tự kể:" en="Mentioned:" /></dt>
                <dd className="font-semibold text-ink">
                  {symptoms.length ? (
                    <T vi={symptoms.map((s) => s.vi).join(", ")} en={symptoms.map((s) => s.en).join(", ")} />
                  ) : (
                    <T vi="không có gì bất thường" en="nothing unusual" />
                  )}
                </dd>
              </div>
            </dl>
          </>
        ) : (
          <p className="text-lg font-medium">
            {isToday ? (
              <T vi={`${k.vi[0].toUpperCase()}${k.vi.slice(1)} chưa bắt máy sáng nay. Út Thương sẽ gọi lại.`} en={`${k.en} hasn't picked up this morning. Út Thương will try again.`} />
            ) : (
              <T vi={`${k.vi[0].toUpperCase()}${k.vi.slice(1)} không bắt máy cuộc gọi ${date.vi}.`} en={`${k.en} didn't pick up the call on ${date.en}.`} />
            )}
          </p>
        )}
      </section>

      <TodayActions
        key={id}
        elderId={id}
        kinVi={k.vi}
        kinEn={k.en}
        phone={p.phone ?? "+84900000000"}
        author={primary?.name ?? "Gia đình"}
        initialNotes={noteList}
        contact={t.contact ?? null}
        todayDate={t.date}
        todayDay={t.day}
      />

      {/* Last 14 days */}
      {lights.length > 0 && (
        <section aria-labelledby="days-h" className="flex flex-col gap-3">
          <div className="flex items-baseline justify-between">
            <h2 id="days-h" className="text-sm font-bold uppercase tracking-wide text-ink-3">
              <T vi="14 ngày qua" en="Last 14 days" />
            </h2>
            <Link href={`/trends?elder=${id}`} className="inline-flex min-h-11 items-center gap-1 font-semibold text-accent">
              <T vi="Xem xu hướng" en="See trends" />
              <ArrowRight size={16} aria-hidden />
            </Link>
          </div>
          <ol className="grid grid-cols-14 gap-1" style={{ gridTemplateColumns: `repeat(${lights.length}, minmax(0, 1fr))` }}>
            {lights.map((l) => {
              const w = LIGHT_WORD[l.light] ?? LIGHT_WORD.gray;
              return (
                <li key={l.day} className="flex flex-col items-center gap-1" title={`${shortDate(l.date)}: ${w.vi} / ${w.en}`}>
                  <StatusShape light={l.light} size={20} />
                  <span className="sr-only">{`${shortDate(l.date)}: ${w.vi} / ${w.en}`}</span>
                </li>
              );
            })}
          </ol>
          <div className="flex justify-between text-xs text-ink-3 tnum">
            <span>{shortDate(lights[0].date)}</span>
            <span>{isToday && lights.at(-1)?.date === t.date ? <T vi="hôm nay" en="today" /> : shortDate(lights.at(-1)?.date ?? "")}</span>
          </div>
        </section>
      )}

      <Link
        href={`/call?elder=${id}`}
        className="flex min-h-14 items-center justify-between gap-3 rounded-2xl border border-line bg-surface px-4 py-3 transition-colors duration-150 hover:border-line-strong"
      >
        <span className="flex items-center gap-3">
          <span className="grid size-10 place-items-center rounded-full bg-accent-tint text-accent">
            <Headphones size={20} aria-hidden />
          </span>
          <span>
            <span className="block font-semibold"><T vi="Thử một cuộc gọi web với Út Thương" en="Try a web call with Út Thương" /></span>
            <span className="block text-sm text-ink-3"><T vi="Nghe trợ lý giọng nói như người thân sẽ nghe" en="Hear the voice companion as your parent does" /></span>
          </span>
        </span>
        <ArrowRight size={18} className="text-ink-3" aria-hidden />
      </Link>

      <Disclaimer />
    </div>
  );
}
