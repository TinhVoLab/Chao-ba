import { Suspense } from "react";
import type { Metadata } from "next";
import { ChartColumnStacked, ClipboardList, HousePlus, Link2, PhoneOff, UserRound } from "lucide-react";
import { getCommunity } from "@/lib/api";
import type { Community, Light, VisitRow } from "@/lib/types";
import { LIGHT_WORD, shortDate } from "@/lib/format";
import { DataBadges } from "@/components/Badges";
import { PageSkeleton } from "@/components/Skeletons";
import { StatusShape, lightText } from "@/components/StatusShape";
import { WardTrend } from "@/components/community/WardTrend";
import { ReviewQueue } from "@/components/community/ReviewQueue";
import { T } from "@/components/T";
import { STATION_ACTOR } from "@/lib/viewer";

export const metadata: Metadata = { title: "Cộng đồng / Community" };

export default function CommunityPage() {
  return (
    <Suspense fallback={<PageSkeleton rows={5} />}>
      <CommunityContent />
    </Suspense>
  );
}

const GROUP: Record<VisitRow["group"], { vi: string; en: string; hintVi: string; hintEn: string }> = {
  red: { vi: "Thăm trước", en: "Visit first", hintVi: "Đèn đỏ, lâu nhất trước", hintEn: "Red light, longest first" },
  yellow: { vi: "Thăm trong tuần", en: "Visit this week", hintVi: "Đèn vàng, lâu nhất trước", hintEn: "Yellow light, longest first" },
  check_in: {
    vi: "Gọi hỏi thăm",
    en: "Check in",
    hintVi: "Sống một mình, lâu không có người nhà liên lạc",
    hintEn: "Lives alone, no family contact for a while",
  },
};

async function CommunityContent() {
  const r = await getCommunity();
  const c: Community = r.data;
  const groups = (["red", "yellow", "check_in"] as const).map((g) => ({ g, rows: c.visit_list.filter((v) => v.group === g) }));

  return (
    <div className="flex flex-col gap-7">
      <header className="flex flex-col gap-3 pt-2">
        <p className="flex items-center gap-2 text-sm font-semibold text-ink-2">
          <HousePlus size={16} aria-hidden />
          <T vi={c.ward.name_vi} en={c.ward.name_en} />
        </p>
        <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
          <h1 className="text-[1.75rem] font-bold leading-tight tracking-tight">
            <T vi="Bảng trạm y tế" en="Health-station board" />
          </h1>
          <DataBadges simulated live={r.live} />
        </div>
        <p className="rounded-2xl border border-line bg-surface px-4 py-3 text-[0.9375rem] text-ink-2">
          <T
            vi={`Đang xem với vai trò: ${STATION_ACTOR.name} (mô phỏng). Tên đã được ẩn danh: chỉ có chữ cái đầu, tuổi và khu phố. Chỉ hiện người đã đồng ý chia sẻ với nhân viên y tế; mỗi lần xem được ghi vào nhật ký của từng người.`}
            en={`Viewing as: ${STATION_ACTOR.name} (simulated). Names are pseudonymised: initials, age and neighbourhood only. Only people who agreed to share with clinical staff appear; every view is written to each person's access log.`}
          />
        </p>
      </header>

      {/* Counts */}
      <section aria-labelledby="cnt-h" className="flex flex-col gap-3">
        <h2 id="cnt-h" className="text-sm font-bold uppercase tracking-wide text-ink-3">
          <T vi={`Hôm nay · ${c.ward.sharing} người`} en={`Today · ${c.ward.sharing} people`} />
        </h2>
        <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {(["red", "yellow", "green", "gray"] as Light[]).map((l) => (
            <li key={l} className="flex items-center gap-3 rounded-2xl border border-line bg-surface p-3">
              <StatusShape light={l} size={34} className="shrink-0" />
              <span>
                <span className={`block text-2xl font-extrabold leading-none tnum ${lightText(l)}`}>{c.counts[l]}</span>
                <span className="text-sm text-ink-2">
                  <T vi={LIGHT_WORD[l].vi} en={LIGHT_WORD[l].en} />
                </span>
              </span>
            </li>
          ))}
        </ul>
        <p className="text-sm text-ink-3">
          <T
            vi={`${c.lives_alone} người sống một mình · ${c.missed_contact} người ≥ ${c.method.missed_contact_days} ngày chưa có người nhà gọi/thăm · ${c.ward.not_sharing} người không chia sẻ với trạm (không hiện).`}
            en={`${c.lives_alone} live alone · ${c.missed_contact} with no family call/visit for ≥ ${c.method.missed_contact_days} days · ${c.ward.not_sharing} not sharing with the station (not shown).`}
          />
        </p>
      </section>

      {r.live && c.review_queue && <ReviewQueue initial={c.review_queue} />}

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)] lg:items-start">
        {/* Visit list */}
        <section aria-labelledby="visit-h" className="flex flex-col gap-4">
          <h2 id="visit-h" className="flex items-center gap-2 text-sm font-bold uppercase tracking-wide text-ink-3">
            <ClipboardList size={16} aria-hidden />
            <T vi="Danh sách thăm hỏi ưu tiên" en="Prioritised visit list" />
          </h2>
          {groups.map(({ g, rows }) =>
            rows.length ? (
              <div key={g} className="flex flex-col gap-2">
                <p className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <span className="font-bold">
                    <T vi={`${GROUP[g].vi} (${rows.length})`} en={`${GROUP[g].en} (${rows.length})`} />
                  </span>
                  <span className="text-sm text-ink-3">
                    <T vi={GROUP[g].hintVi} en={GROUP[g].hintEn} />
                  </span>
                </p>
                <ol className="divide-y divide-line rounded-2xl border border-line bg-surface">
                  {rows.map((v) => (
                    <VisitItem key={v.pid} v={v} />
                  ))}
                </ol>
              </div>
            ) : null,
          )}
        </section>

        <div className="flex flex-col gap-8">
          {/* Trend */}
          <section aria-labelledby="trend-h" className="flex flex-col gap-3">
            <h2 id="trend-h" className="flex items-center gap-2 text-sm font-bold uppercase tracking-wide text-ink-3">
              <ChartColumnStacked size={16} aria-hidden />
              <T vi={`Đèn của phường, ${c.method.trend_days} ngày`} en={`Ward lights, ${c.method.trend_days} days`} />
            </h2>
            <WardTrend rows={c.trend} />
          </section>

          {/* Interventions (association) */}
          <section aria-labelledby="iv-h" className="flex flex-col gap-3">
            <h2 id="iv-h" className="flex items-center gap-2 text-sm font-bold uppercase tracking-wide text-ink-3">
              <Link2 size={16} aria-hidden />
              <T vi="Can thiệp nào đi cùng lúc hồi phục?" en="Which actions coincided with recovery?" />
            </h2>
            <p className="text-[0.9375rem] text-ink-2">
              <T
                vi={`Mỗi đợt đèn vàng/đỏ (gộp, ẩn danh) và việc được ghi nhận trong đợt đó; "về xanh" = trong ${c.method.recovery_days} ngày.`}
                en={`Each yellow/red episode (pooled, anonymous) and the action recorded during it; "back to green" = within ${c.method.recovery_days} days.`}
              />
            </p>
            <div className="overflow-x-auto rounded-2xl border border-line bg-surface">
              <table className="w-full text-left text-[0.9375rem]">
                <thead className="text-sm text-ink-3">
                  <tr className="border-b border-line">
                    <th scope="col" className="px-3 py-2 font-semibold"><T vi="Việc đã làm" en="Action" /></th>
                    <th scope="col" className="px-3 py-2 text-right font-semibold"><T vi="Số đợt" en="Episodes" /></th>
                    <th scope="col" className="px-3 py-2 text-right font-semibold"><T vi="Về xanh" en="To green" /></th>
                    <th scope="col" className="px-3 py-2 text-right font-semibold"><T vi="Trung vị" en="Median" /></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line tnum">
                  {c.interventions.map((x) => (
                    <tr key={x.intervention}>
                      <th scope="row" className="px-3 py-2.5 font-medium">
                        <T vi={x.label_vi} en={x.label_en} />
                        {x.open > 0 && (
                          <span className="block text-xs font-normal text-ink-3">
                            <T vi={`+${x.open} đợt chưa đủ ${c.method.recovery_days} ngày`} en={`+${x.open} still within ${c.method.recovery_days} days`} />
                          </span>
                        )}
                      </th>
                      <td className="px-3 py-2.5 text-right">{x.episodes}</td>
                      <td className="px-3 py-2.5 text-right">
                        {x.enough && x.rate != null ? (
                          `${Math.round(x.rate * 100)}%`
                        ) : (
                          <span className="text-sm text-ink-3"><T vi="chưa đủ" en="too few" /></span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        {x.median_days_to_green != null ? <T vi={`${x.median_days_to_green} ngày`} en={`${x.median_days_to_green} d`} /> : "–"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="text-sm text-ink-3">
              <T vi={c.association_note_vi} en={c.association_note_en} />
            </p>
          </section>
        </div>
      </div>

      <p className="mt-4 border-t border-line pt-4 text-sm text-ink-3">
        <T vi={c.disclaimer_vi} en={c.disclaimer_en} />{" "}
        <T
          vi={`Phường mô phỏng: ${c.method.cohort.n} người tạo bởi chaoba.core.synth (${c.method.cohort.days} ngày) cùng ${c.ward.demo_personas} hồ sơ demo, không có bản đồ hay địa chỉ.`}
          en={`Simulated ward: ${c.method.cohort.n} people generated by chaoba.core.synth (${c.method.cohort.days} days) plus ${c.ward.demo_personas} demo personas; no map, no addresses.`}
        />{" "}
        <T vi={`Số liệu tới ngày ${shortDate(c.as_of)}.`} en={`Data up to ${shortDate(c.as_of)}.`} />
      </p>
    </div>
  );
}

function VisitItem({ v }: { v: VisitRow }) {
  const w = LIGHT_WORD[v.light];
  return (
    <li className="flex gap-3 px-3.5 py-3">
      <span className="w-6 shrink-0 pt-0.5 text-right text-sm font-semibold text-ink-3 tnum">{v.rank}</span>
      <StatusShape light={v.light} size={24} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-baseline gap-x-2 font-semibold">
          <span className="tnum">{v.initials}</span>
          <span className="text-[0.9375rem] font-normal text-ink-2">
            <T vi={`${v.age} tuổi · ${v.area}`} en={`${v.age} · ${v.area}`} />
          </span>
          {v.demo_persona && (
            <span className="rounded-full bg-surface-2 px-2 text-xs font-semibold text-ink-3">
              <T vi="hồ sơ demo" en="demo persona" />
            </span>
          )}
        </p>
        <p className="text-sm text-ink-2">
          <span className={`font-semibold ${lightText(v.light)}`}>
            <T vi={`${w.vi} ${v.days_in_state} ngày`} en={`${w.en} for ${v.days_in_state} d`} />
          </span>
          {v.reasons_vi.length > 0 && (
            <>
              {" · "}
              <T vi={v.reasons_vi.join("; ")} en={v.reasons_en.join("; ")} />
            </>
          )}
        </p>
        {(v.lives_alone || v.missed_contact) && (
          <p className="mt-1 flex flex-wrap gap-1.5">
            {v.lives_alone && (
              <span className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2 py-px text-xs font-semibold text-ink-2">
                <UserRound size={12} aria-hidden />
                <T vi="sống một mình" en="lives alone" />
              </span>
            )}
            {v.missed_contact && v.days_since_contact != null && (
              <span className="inline-flex items-center gap-1 rounded-full bg-yellow-tint px-2 py-px text-xs font-semibold text-yellow-ink">
                <PhoneOff size={12} aria-hidden />
                <T vi={`${v.days_since_contact} ngày chưa có người nhà liên lạc`} en={`no family contact for ${v.days_since_contact} d`} />
              </span>
            )}
          </p>
        )}
      </div>
    </li>
  );
}
