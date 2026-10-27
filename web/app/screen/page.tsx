import { Suspense } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { StandingScreen, type ScreenFlags } from "@/components/StandingScreen";
import { API_BASE, serverApiBase } from "@/lib/config";
import { fixtureFor } from "@/lib/fixtures";
import type { ElderProfile, Note } from "@/lib/types";
import s from "@/components/elder/classes";
import "@/components/elder/elder.css";

export const metadata: Metadata = { title: "Màn hình đứng / Standing screen" };

const ELDERS: [string, string, string][] = [
  ["hanh", "Bà Hạnh", "Mrs Hanh"],
  ["tu", "Ông Tư", "Mr Tu"],
  ["control", "Ông Bảy", "Mr Bay"],
];

type SP = Record<string, string | string[] | undefined>;
const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

/** Reads as the elder's own screen (X-Role elder_self) so the access log shows who looked; fixtures when offline. */
async function elderGet<T>(path: string, elderId: string, fallback: () => T): Promise<{ data: T; live: boolean }> {
  try {
    const r = await fetch(`${serverApiBase()}${path}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
      headers: { "X-Actor": encodeURIComponent(`elder:${elderId}`), "X-Role": "elder_self" },
    });
    if (!r.ok) throw new Error(String(r.status));
    return { data: (await r.json()) as T, live: true };
  } catch {
    return { data: fallback(), live: false };
  }
}

function href(sp: SP, patch: Record<string, string | null>) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(sp)) {
    const x = one(v);
    if (x !== undefined) q.set(k, x);
  }
  for (const [k, v] of Object.entries(patch)) {
    if (v === null) q.delete(k);
    else q.set(k, v);
  }
  const str = q.toString();
  return `/screen${str ? `?${str}` : ""}`;
}

async function ScreenContent({ searchParams }: { searchParams: Promise<SP> }) {
  const sp = await searchParams;
  const requested = one(sp.elder) ?? "hanh";
  const elderId = ELDERS.some(([id]) => id === requested) ? requested : /^[a-z0-9_-]{1,40}$/i.test(requested) ? requested : "hanh";
  const [profile, notes] = await Promise.all([
    elderGet<ElderProfile>(`/api/elders/${encodeURIComponent(elderId)}`, elderId, () => fixtureFor(elderId).profile),
    elderGet<Note[]>(`/api/elders/${encodeURIComponent(elderId)}/notes`, elderId, () => fixtureFor(elderId).notes),
  ]);
  const p = profile.data;
  const apiParam = one(sp.api);
  const apiBase = apiParam && /^https?:\/\/[^\s]+$/.test(apiParam) ? apiParam.replace(/\/$/, "") : API_BASE;
  const flags: ScreenFlags = {
    lang: one(sp.lang) === "en" ? "en" : "vi",
    sim: one(sp.sim) === "1",
    tts: one(sp.tts) !== "0",
    typed: one(sp.typed) === "1",
    fast: one(sp.fast) === "1",
  };
  const kiosk = one(sp.kiosk) === "1";
  const en = flags.lang === "en";
  const L = (vi: string, e: string) => (en ? e : vi);
  const fam = (p.family ?? []).find((f) => f.role === "primary") ?? p.family?.[0];
  const calleeVi = fam ? (fam.relation === "son" || fam.relation === "daughter" ? `con ${fam.name}` : fam.name) : "";

  return (
    <div className={`${s.stage} ${kiosk ? s.kiosk : ""}`}>
      <div className={s.device}>
        <StandingScreen key={p.id} profile={p} notes={Array.isArray(notes.data) ? notes.data : []} live={profile.live} apiBase={apiBase} flags={flags} />
      </div>
      <aside className={s.guide} lang={flags.lang} aria-label={L("Hướng dẫn demo", "Demo guide")}>
        <p className={s.guideKicker}>{L("Gói màn hình đứng · bản web tương tác", "Standing screen · interactive web prototype")}</p>
        <h1>{L("Hướng dẫn demo", "Demo guide")}</h1>
        <p className={s.guideMuted}>
          {L(
            "Màn hình 9:16 đặt trong nhà người cao tuổi, đọc được từ 1–1,5 m. Phần cứng là giai đoạn 2; giao diện này chạy thật trên API.",
            "A 9:16 screen in the older adult's home, readable from 1–1.5 m. Hardware is phase 2; this interface runs on the real API.",
          )}
        </p>
        <ol className={s.guideSteps}>
          <li>
            <b>{L("Nói chuyện với Út Thương", "Talk to Út Thương")}</b>{" "}
            {L("Bấm nút vàng và nói tiếng Việt (Chrome/Edge, cho phép micro).", "Press the yellow button and speak Vietnamese (Chrome/Edge, allow the mic).")}{" "}
            <Link href={href(sp, { sim: "1", typed: null })}>{L("Giả lập rảnh tay", "Hands-free simulation")}</Link>
            {" · "}
            <Link href={href(sp, { typed: "1", sim: null })}>{L("Gõ chữ", "Typed answers")}</Link>
            {(flags.sim || flags.typed) && (
              <>
                {" · "}
                <Link href={href(sp, { typed: null, sim: null })}>{L("Giọng nói", "Voice")}</Link>
              </>
            )}
          </li>
          <li>
            <b>{L("Tình huống khẩn cấp", "Emergency")}</b>{" "}
            {L("Ở chế độ gõ chữ, gõ “tôi bị tức ngực”: màn hình đỏ, nút Gọi 115, gia đình được báo.", "In typed mode, type “tôi bị tức ngực” (chest tightness): calm red screen, Call 115, family alerted.")}
          </li>
          <li>
            <b>{fam ? L(`Gọi ${calleeVi}`, `Call ${fam.name}`) : L("Gọi người nhà", "Call family")}</b>{" "}
            {L("Cuộc gọi video mô phỏng; ghi vào nhật ký liên lạc trong ứng dụng gia đình.", "Simulated video call; logged in the family app's contact log.")}
          </li>
          <li>
            <b>{L("Lời thương từ gia đình", "Love notes from the family")}</b>{" "}
            {L(
              "Gửi “Má ăn cơm chưa?” từ ứng dụng gia đình (Hôm nay → Gửi yêu thương): thẻ hiện ở đây sau vài giây, chạm “Ăn rồi” là gia đình thấy câu trả lời.",
              "Send “Má ăn cơm chưa?” from the family app (Today → Send some love): the card appears here within seconds; tap an answer and the family sees it.",
            )}{" "}
            <Link href={`/?elder=${elderId}`}>{L("Mở ứng dụng gia đình", "Open the family app")}</Link>
          </li>
          <li>
            <b>{L("Thuốc, tâm trạng, trò chơi", "Medicine, mood, game")}</b>{" "}
            {L("“Đã uống thuốc”, “Hôm nay thấy sao?”, “Trò chơi ca dao” đều lưu qua API (người cao tuổi tự chọn, không chấm điểm).", "“I took it”, “How are you today?” and the folk-verse game are stored via the API (self-report, never scored).")}
          </li>
        </ol>
        <div className={s.guideRow} role="group" aria-label={L("Người cao tuổi", "Elder")}>
          {ELDERS.map(([id, vi, e]) => (
            <Link key={id} href={href(sp, { elder: id })} aria-current={id === elderId ? "page" : undefined}>
              {en ? e : vi}
            </Link>
          ))}
        </div>
        <div className={s.guideRow} role="group" aria-label={L("Ngôn ngữ", "Language")}>
          <Link href={href(sp, { lang: null })} aria-current={!en ? "true" : undefined}>
            Tiếng Việt
          </Link>
          <Link href={href(sp, { lang: "en" })} aria-current={en ? "true" : undefined}>
            English
          </Link>
          <Link href={href(sp, { kiosk: "1" })}>{L("Toàn màn hình", "Full screen")}</Link>
        </div>
        <p className={s.guideMuted}>
          {profile.live
            ? L("Đang dùng API trực tiếp. Dữ liệu mô phỏng.", "Live API. Simulated data.")
            : L("Không kết nối được API: hiển thị dữ liệu mẫu, thao tác được lưu trên máy.", "API unreachable: showing bundled sample data; taps are kept on this device.")}{" "}
          {L("Âm thanh: thêm ?tts=0 để tắt giọng đọc.", "Sound: add ?tts=0 for captions only.")}
        </p>
        <Link className={s.guideBack} href={`/?elder=${elderId}`}>
          {L("← Ứng dụng gia đình", "← Family app")}
        </Link>
      </aside>
    </div>
  );
}

export default function ScreenPage({ searchParams }: PageProps<"/screen">) {
  return (
    <Suspense fallback={<div className={s.stage} />}>
      <ScreenContent searchParams={searchParams as Promise<SP>} />
    </Suspense>
  );
}
