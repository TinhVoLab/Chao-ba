import { Suspense } from "react";
import type { Metadata } from "next";
import { ArrowUpRight, Headphones, Mic, ShieldCheck } from "lucide-react";
import { loadElderContext } from "@/lib/api";
import { API_BASE } from "@/lib/config";
import { ApiStatus } from "@/components/ApiStatus";
import { PageSkeleton } from "@/components/Skeletons";
import { StatusShape } from "@/components/StatusShape";
import { T } from "@/components/T";

export const metadata: Metadata = { title: "Cuộc gọi web / Web call" };

export default function CallPage({ searchParams }: PageProps<"/call">) {
  return (
    <Suspense fallback={<PageSkeleton rows={2} />}>
      <CallContent searchParams={searchParams} />
    </Suspense>
  );
}

async function CallContent({ searchParams }: { searchParams: PageProps<"/call">["searchParams"] }) {
  const sp = await searchParams;
  const ctx = await loadElderContext(sp.elder);
  const ordered = [ctx.elder, ...ctx.elders.filter((e) => e.id !== ctx.elder.id)];
  return (
    <div className="flex flex-col gap-6 pt-2">
      <header className="flex flex-col gap-2">
        <span className="grid size-12 place-items-center rounded-2xl bg-accent-tint text-accent">
          <Headphones size={24} aria-hidden />
        </span>
        <h1 className="text-[1.75rem] font-bold leading-tight tracking-tight">
          <T vi="Cuộc gọi web với Út Thương" en="Web call with Út Thương" />
        </h1>
        <p className="max-w-[60ch] text-ink-2">
          <T
            vi="Mở trang gọi mà người thân sẽ dùng: một nút lớn, nói tiếng Việt. Trình duyệt chỉ gửi chữ và thời điểm ngừng nói, không gửi âm thanh."
            en="Opens the page your parent uses: one big button, spoken Vietnamese. The browser sends only text and pause timings, never audio."
          />
        </p>
        <ApiStatus />
      </header>
      <ul className="flex flex-col gap-3">
        {ordered.map((e, i) => (
          <li key={e.id}>
            <a
              href={`${API_BASE}/call?elder=${encodeURIComponent(e.id)}`}
              target="_blank"
              rel="noopener"
              className={`flex min-h-16 items-center justify-between gap-3 rounded-2xl px-4 py-3 transition-colors duration-150 ${
                i === 0 ? "bg-accent text-accent-ink hover:bg-accent-hover" : "border border-line bg-surface hover:border-line-strong"
              }`}
            >
              <span className="flex items-center gap-3">
                <span className={`grid size-11 place-items-center rounded-full ${i === 0 ? "bg-accent-ink/15" : "bg-surface-2"}`}>
                  <Mic size={20} aria-hidden />
                </span>
                <span>
                  <span className="block text-lg font-bold">{e.display_name}</span>
                  <span className={`flex items-center gap-1.5 text-sm ${i === 0 ? "opacity-85" : "text-ink-3"}`}>
                    <StatusShape light={e.light} size={14} />
                    {e.age} · {e.province}
                  </span>
                </span>
              </span>
              <span className="flex items-center gap-1 font-semibold">
                <T vi="Mở" en="Open" />
                <ArrowUpRight size={18} aria-hidden />
              </span>
            </a>
          </li>
        ))}
      </ul>
      <p className="flex items-start gap-2 text-sm text-ink-3">
        <ShieldCheck size={16} className="mt-0.5 shrink-0" aria-hidden />
        <T
          vi="Một cuộc gọi thật sẽ thêm ngày mới (không mô phỏng) vào dữ liệu của người đó, so với mức nền mô phỏng."
          en="A real call appends a new, non-simulated day for that person, compared against the simulated baseline."
        />
      </p>
    </div>
  );
}
