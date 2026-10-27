import { Suspense } from "react";
import Link from "next/link";
import { ArrowRight, Bell, Headphones, MessageCircle, Pill, Smile } from "lucide-react";
import { getAlerts, getKudosCatalog, getKudosList, getMedicationLog, getMoodCheckin, getNotes, getProfile, getTimeline, getToday, loadElderContext } from "@/lib/api";
import { serverViewer } from "@/lib/viewer-server";
import { LIGHT_HINT, LIGHT_WORD, MOOD_WORD, SYMPTOM_WORD, kin, longDate, shortDate, vnTime } from "@/lib/format";
import { normNotes } from "@/lib/normalize";
import { PageHeader, Disclaimer } from "@/components/PageHeader";
import { PageSkeleton } from "@/components/Skeletons";
import { StatusShape, lightText, lightTint } from "@/components/StatusShape";
import { TodayActions } from "@/components/TodayActions";
import { T } from "@/components/T";
import { MemoryBookCard } from "@/components/memories/MemoryBookCard";
import { KudosTray } from "@/components/kudos/KudosTray";

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
  const [today, profile, notes, timeline, alerts, viewer] = await Promise.all([
    getToday(id),
    getProfile(id),
    getNotes(id),
    getTimeline(id, 90),
    getAlerts(id),
    serverViewer(id),
  ]);
  const [medLog, mood, kudosCatalog, kudosSent] = await Promise.all([
    getMedicationLog(id),
    getMoodCheckin(id),
    getKudosCatalog(id),
    getKudosList(id, "sent"),
  ]);
  // Self-reports from the elder's home screen: shown as-is, never scored.
  const medsToday = (medLog.data?.today ?? []).filter((m) => m.status);
  const moodToday = mood.data?.today ?? null;
  // Alerts live under "Thêm / More" in the nav, so unread ones are also surfaced here.
  const unread = (Array.isArray(alerts.data) ? alerts.data : []).filter((a) => !a.acknowledged);
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

      {unread.length > 0 && (
        <Link
          href={`/alerts?elder=${id}`}
          className="fade-in flex min-h-14 items-center gap-3 rounded-2xl border border-line bg-surface px-4 py-3 transition-colors duration-150 hover:border-line-strong"
        >
          <span
            className={`grid size-10 shrink-0 place-items-center rounded-full ${
              unread.some((a) => a.severity === "critical" || a.severity === "red") ? "bg-red-tint text-red-ink" : "bg-yellow-tint text-yellow-ink"
            }`}
          >
            <Bell size={20} aria-hidden />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block font-semibold">
              <T vi={`${unread.length} cảnh báo chưa xem`} en={`${unread.length} unread alert${unread.length > 1 ? "s" : ""}`} />
            </span>
            <span className="block truncate text-sm text-ink-3">
              <T vi={unread[0].explanation_vi} en={unread[0].explanation_en} />
            </span>
          </span>
          <ArrowRight size={18} className="shrink-0 text-ink-3" aria-hidden />
        </Link>
      )}

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

      {!paused && (medsToday.length > 0 || moodToday) && (
        <section aria-label="Tự báo / Self-report" className="flex flex-col gap-1.5 rounded-2xl bg-surface-2 px-4 py-3 text-[0.9375rem]">
          {medsToday.map((m) => (
            <p key={m.name} className="flex items-start gap-2">
              <Pill size={17} className="mt-0.5 shrink-0 text-ink-3" aria-hidden />
              <span>
                {m.status === "taken" ? (
                  <T
                    vi={`${k.vi[0].toUpperCase()}${k.vi.slice(1)} đã bấm “Đã uống thuốc” (${m.name}) lúc ${vnTime(m.answered_at ?? "")}.`}
                    en={`${k.en} tapped “Took my medicine” (${m.name}) at ${vnTime(m.answered_at ?? "")}.`}
                  />
                ) : (
                  <T
                    vi={`${k.vi[0].toUpperCase()}${k.vi.slice(1)} bấm “Chưa uống” (${m.name}) lúc ${vnTime(m.answered_at ?? "")}.`}
                    en={`${k.en} tapped “Not yet” (${m.name}) at ${vnTime(m.answered_at ?? "")}.`}
                  />
                )}
              </span>
            </p>
          ))}
          {moodToday && (
            <p className="flex items-start gap-2">
              <Smile size={17} className="mt-0.5 shrink-0 text-ink-3" aria-hidden />
              <span>
                <T
                  vi={`${k.vi[0].toUpperCase()}${k.vi.slice(1)} tự chọn tâm trạng hôm nay: ${moodToday.label_vi} (${vnTime(moodToday.created_at)}).`}
                  en={`${k.en} chose today's mood: ${moodToday.label_en} (${vnTime(moodToday.created_at)}).`}
                />
              </span>
            </p>
          )}
          <p className="text-xs text-ink-3">
            <T vi="Tự bấm trên màn hình ở nhà; chỉ để biết, không tính vào đèn." en="Tapped on the home screen; for information only, not counted in the light." />
          </p>
        </section>
      )}

      <TodayActions
        key={id}
        elderId={id}
        kinVi={k.vi}
        kinEn={k.en}
        phone={p.phone ?? "+84900000000"}
        author={viewer.name}
        initialNotes={noteList}
        contact={t.contact ?? null}
        todayDate={t.date}
        todayDay={t.day}
      >
        {/* "Gửi yêu thương": right under "Gọi má", never instead of it */}
        <KudosTray
          key={`${id}-${viewer.memberId}`}
          elderId={id}
          kinVi={k.vi}
          kinEn={k.en}
          catalog={kudosCatalog.data}
          initial={kudosSent.data}
          compact
        />
      </TodayActions>

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

      <MemoryBookCard elderId={id} />

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
