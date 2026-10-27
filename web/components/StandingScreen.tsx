"use client";
import { useEffect, useState, useSyncExternalStore } from "react";
import type { ElderProfile } from "@/lib/types";
import { Mic, Phone } from "lucide-react";

type Line = [speaker: "ai" | "elder", vi: string, en: string];

/** Builds the caption demo from the elder's real profile (names, memory facts, medication). */
function scriptFor(p: ElderProfile, child: string | null): Line[] {
  const h = p.honorific || "bà";
  const H = h[0].toUpperCase() + h.slice(1);
  const given = p.display_name.split(" ").slice(1).join(" ") || p.display_name;
  const pr = h === "bà" ? "she" : "he";
  const fact = p.memory_facts?.[0];
  const med = p.medications?.find((m) => /^\d{1,2}:\d{2}$/.test(m.time));
  const lines: Line[] = [
    ["ai", `Chào ${h} ${given}! Con là Út Thương đây. Đêm qua ${h} ngủ ngon không ${h}?`, `Hello, ${p.name_en}! It's Út Thương. Did you sleep well?`],
    ["elder", "Ngủ cũng được con. Sáng nay trời mát, dễ chịu.", "Not bad. It's cool and pleasant this morning."],
  ];
  if (fact) {
    lines.push(["ai", `Dạ. Bữa trước ${h} kể con nghe: “${fact}”. Dạo này sao rồi ${h}?`, `You once told me: “${fact}”. How is that going?`]);
    lines.push(["elder", "Vẫn vậy con. Kể con nghe hoài cũng vui.", `Same as ever. ${pr === "she" ? "She" : "He"} enjoys telling it.`]);
  }
  if (med) {
    lines.push(["ai", `${H} nhớ uống ${med.name} lúc ${med.time.replace(":", " giờ ").replace(" giờ 00", " giờ")} nha ${h}.`, `Remember your ${med.name} at ${med.time}.`]);
  }
  if (child) {
    lines.push(["elder", `Ừ. Chiều nay ${child} có gọi không con?`, `Okay. Is ${child} calling this afternoon?`]);
    lines.push(["ai", `Dạ có, con sẽ nhắc ${child} gọi ${h} sau giờ làm.`, `Yes, I'll remind ${child} to call after work.`]);
  }
  return lines;
}

const WD = ["Chủ nhật", "Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy"];
const WD_EN = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MON_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

function subscribeClock(cb: () => void) {
  const id = setInterval(cb, 1000);
  return () => clearInterval(id);
}
function clockSnapshot() {
  const d = new Date();
  return `${d.getHours()}|${d.getMinutes()}|${d.getDay()}|${d.getDate()}|${d.getMonth()}`;
}

function Scene({ i }: { i: number }) {
  if (i === 0)
    return (
      <svg viewBox="0 0 400 300" className="size-full" preserveAspectRatio="xMidYMid slice" aria-hidden>
        <defs>
          <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#f4c9a0" />
            <stop offset="0.6" stopColor="#f6e2c4" />
          </linearGradient>
          <linearGradient id="river" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#7fa7a3" />
            <stop offset="1" stopColor="#4d7b78" />
          </linearGradient>
        </defs>
        <rect width="400" height="300" fill="url(#sky)" />
        <circle cx="270" cy="150" r="46" fill="#f3a35f" opacity="0.9" />
        <path d="M0 175 Q100 150 200 170 T400 160 V300 H0Z" fill="#5f7d4e" />
        <path d="M0 205 Q120 190 220 205 T400 200 V300 H0Z" fill="url(#river)" />
        <path d="M150 232 q30 -14 60 0 l-6 10 h-48z" fill="#3b3227" />
        <path d="M40 175 v-50 M40 130 q-20 -10 -30 5 M40 130 q20 -12 32 2 M40 140 q-24 0 -28 14 M40 140 q22 -4 30 10" stroke="#3f5a35" strokeWidth="5" fill="none" strokeLinecap="round" />
      </svg>
    );
  if (i === 1)
    return (
      <svg viewBox="0 0 400 300" className="size-full" preserveAspectRatio="xMidYMid slice" aria-hidden>
        <defs>
          <radialGradient id="warm" cx="0.3" cy="0.3" r="0.9">
            <stop offset="0" stopColor="#fbe7b0" />
            <stop offset="1" stopColor="#e9b26b" />
          </radialGradient>
        </defs>
        <rect width="400" height="300" fill="url(#warm)" />
        <path d="M-10 260 Q120 200 210 150 T420 40" stroke="#6b4a2f" strokeWidth="9" fill="none" strokeLinecap="round" />
        <path d="M150 182 Q170 230 230 250" stroke="#6b4a2f" strokeWidth="6" fill="none" strokeLinecap="round" />
        {[
          [90, 215], [160, 175], [235, 130], [300, 95], [360, 62], [205, 240], [120, 160], [270, 160], [330, 125],
        ].map(([x, y], k) => (
          <g key={k} transform={`translate(${x} ${y})`}>
            {[0, 72, 144, 216, 288].map((a) => (
              <ellipse key={a} cx="0" cy="-12" rx="8" ry="12" fill="#f7c626" transform={`rotate(${a})`} />
            ))}
            <circle r="5" fill="#d0731c" />
          </g>
        ))}
      </svg>
    );
  return (
    <svg viewBox="0 0 400 300" className="size-full" preserveAspectRatio="xMidYMid slice" aria-hidden>
      <rect width="400" height="300" fill="#dfe8c9" />
      <circle cx="90" cy="70" r="30" fill="#f6e7a8" />
      <path d="M0 140 Q200 100 400 135 V300 H0Z" fill="#a9c47a" />
      <path d="M0 175 Q200 140 400 170 V300 H0Z" fill="#87ad55" />
      <path d="M0 215 Q200 180 400 210 V300 H0Z" fill="#6a9440" />
      <path d="M0 255 Q200 225 400 250 V300 H0Z" fill="#4f7a2e" />
      <g fill="#3a3326">
        <path d="M300 170 l14 -12 l14 12 z" />
        <rect x="305" y="170" width="18" height="14" />
      </g>
    </svg>
  );
}

const SCENES = [
  { vi: "Quê nhà buổi sớm", en: "Home at dawn" },
  { vi: "Mai nở ngày Tết", en: "Tết apricot blossoms" },
  { vi: "Đồng lúa", en: "Rice fields" },
];

export function StandingScreen({ profile }: { profile: ElderProfile }) {
  const kids = (profile.family ?? []).filter((f) => f.relation === "son" || f.relation === "daughter");
  const child = (kids.find((f) => f.role === "primary") ?? kids[0])?.name ?? null;
  const hon = profile.honorific || "bà";
  const given = profile.display_name.split(" ").slice(1).join(" ") || profile.display_name;
  const who = { vi: `${hon} ${given}`, en: profile.name_en, child, script: scriptFor(profile, child) };
  const clock = useSyncExternalStore(subscribeClock, clockSnapshot, () => "");
  const [scene, setScene] = useState(0);
  const [turn, setTurn] = useState(1);

  useEffect(() => {
    const a = setInterval(() => setScene((s) => (s + 1) % SCENES.length), 6000);
    const b = setInterval(() => setTurn((t) => (t >= who.script.length ? 1 : t + 1)), 4200);
    return () => {
      clearInterval(a);
      clearInterval(b);
    };
  }, [who.script.length]);

  const [h, m, wd, dd, mo] = clock ? clock.split("|").map(Number) : [];
  const time = clock ? `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}` : "--:--";
  const part = !clock ? null : h < 11 ? ["buổi sáng", "morning"] : h < 14 ? ["buổi trưa", "afternoon"] : h < 18 ? ["buổi chiều", "afternoon"] : ["buổi tối", "evening"];
  const lines = who.script.slice(Math.max(0, turn - 2), turn);

  return (
    <div
      className="relative flex flex-col overflow-hidden rounded-[2.2cqw] text-[#f6efe2] shadow-2xl"
      style={{
        aspectRatio: "9 / 16",
        height: "min(calc(100dvh - 4rem), calc(100vw * 16 / 9))",
        containerType: "size",
        background: "radial-gradient(120% 70% at 50% 0%, #3a2c22 0%, #241b15 60%, #1c1511 100%)",
      }}
    >
      {/* concept label: this screen is a phase-2 design idea, not part of the prototype's scope */}
      <div className="flex items-center px-[5cqw] pt-[3cqw]">
        <span className="rounded-full border border-[#f6efe2]/25 px-[2.4cqw] py-[0.6cqw] text-[2.4cqw] font-semibold tracking-wide text-[#f6efe2]/75">
          Màn hình đứng (thiết kế giai đoạn 2)<span className="l-en"> · Standing screen (phase-2 concept)</span>
        </span>
      </div>

      {/* clock */}
      <div className="px-[6cqw] pt-[2cqw]">
        <p className="font-extrabold leading-[0.95] tracking-tight tnum" style={{ fontSize: "21cqw" }} aria-label={`Bây giờ là ${time}`}>
          {time}
        </p>
        <p className="font-semibold text-[#f6efe2]/90" style={{ fontSize: "6.4cqw" }}>
          {clock ? `${WD[wd]}, ${dd} tháng ${mo + 1}` : " "}
        </p>
        {clock && (
          <p className="l-en text-[#f6efe2]/60" style={{ fontSize: "3.6cqw" }}>
            {WD_EN[wd]}, {dd} {MON_EN[mo]}
          </p>
        )}
        <p className="mt-[1.5cqw] font-medium text-[#f3c77a]" style={{ fontSize: "5.4cqw" }}>
          Chào {part ? part[0] : ""}, {who.vi}!
          <span className="l-en block text-[#f6efe2]/60" style={{ fontSize: "3.4cqw" }}>
            Good {part ? part[1] : "day"}, {who.en}! (AI companion “Út Thương”)
          </span>
        </p>
      </div>

      {/* photo slideshow placeholder */}
      <figure className="relative mx-[6cqw] mt-[3cqw] overflow-hidden rounded-[3cqw]" style={{ aspectRatio: "16 / 9" }}>
        {SCENES.map((s, i) => (
          <div key={s.vi} className="absolute inset-0 transition-opacity duration-1000 ease-out" style={{ opacity: scene === i ? 1 : 0 }}>
            <Scene i={i} />
          </div>
        ))}
        <figcaption className="absolute inset-x-0 bottom-0 flex items-end justify-between bg-gradient-to-t from-black/55 to-transparent px-[3cqw] pb-[2cqw] pt-[6cqw]">
          <span className="font-semibold" style={{ fontSize: "3.6cqw" }}>
            {SCENES[scene].vi}
            <span className="l-en block font-normal opacity-75" style={{ fontSize: "2.8cqw" }}>
              {SCENES[scene].en} · family photos appear here
            </span>
            <span className="l-vi block font-normal opacity-75" style={{ fontSize: "2.8cqw" }}>
              Ảnh gia đình sẽ hiện ở đây
            </span>
          </span>
          <span className="flex gap-[1.2cqw]" aria-hidden>
            {SCENES.map((s, i) => (
              <span key={s.vi} className={`size-[1.8cqw] rounded-full ${i === scene ? "bg-white" : "bg-white/40"}`} />
            ))}
          </span>
        </figcaption>
      </figure>

      {/* two-way captions */}
      <div className="mx-[6cqw] mt-[2.5cqw] flex min-h-[22cqh] flex-1 flex-col justify-end gap-[1.6cqw] overflow-hidden" aria-live="polite">
        {lines.map(([who2, vi, en], i) => (
          <div
            key={`${turn}-${i}`}
            className={`fade-in max-w-[92%] rounded-[3cqw] px-[3.4cqw] py-[2.2cqw] ${
              who2 === "ai" ? "self-start rounded-tl-[0.8cqw] bg-[#f6efe2] text-[#2a1f17]" : "self-end rounded-tr-[0.8cqw] bg-[#3f5f8f] text-white"
            } ${i === 0 && lines.length > 1 ? "opacity-60" : ""}`}
          >
            <p className="font-bold opacity-70" style={{ fontSize: "2.8cqw" }}>
              {who2 === "ai" ? "Út Thương" : who.vi[0].toUpperCase() + who.vi.slice(1)}
            </p>
            <p className="font-semibold leading-snug" style={{ fontSize: i === 0 && lines.length > 1 ? "3.6cqw" : "4.8cqw" }}>
              {vi}
            </p>
            <p className="l-en opacity-70" style={{ fontSize: "2.8cqw" }}>
              {en}
            </p>
          </div>
        ))}
      </div>

      {/* big buttons */}
      <div className={`grid gap-[3cqw] px-[6cqw] pb-[3cqw] pt-[3cqw] ${who.child ? "grid-cols-2" : "grid-cols-1"}`}>
        {who.child && <button type="button" className="flex flex-col items-center justify-center gap-[1cqw] rounded-[4cqw] bg-[#4f9a62] py-[3.4cqw] font-extrabold text-white active:translate-y-px" style={{ fontSize: "5.6cqw" }}>
          <Phone className="size-[8cqw]" aria-hidden />
          Gọi con {who.child}
          <span className="l-en font-medium opacity-80" style={{ fontSize: "3cqw" }}>
            Call {who.child}
          </span>
        </button>}
        <button type="button" className="flex flex-col items-center justify-center gap-[1cqw] rounded-[4cqw] bg-[#f3c77a] py-[3.4cqw] font-extrabold text-[#2a1f17] active:translate-y-px" style={{ fontSize: "5.6cqw" }}>
          <Mic className="size-[8cqw]" aria-hidden />
          Nói chuyện
          <span className="l-en font-medium opacity-80" style={{ fontSize: "3cqw" }}>
            Talk to Út Thương
          </span>
        </button>
      </div>
      <p className="pb-[2.4cqw] text-center text-[#f6efe2]/55" style={{ fontSize: "2.4cqw" }}>
        Dữ liệu mô phỏng / Simulated data · Bản mô phỏng giao diện / UI mockup
      </p>
    </div>
  );
}
