"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { House, ListChecks, ListTodo, Pill, Plus, Stethoscope, X } from "lucide-react";
import type { CareTask, FamilyMemberRow, FamilyViewer, TaskKind } from "@/lib/types";
import { postWrite, useOutbox } from "@/lib/outbox";
import { useLang } from "@/lib/useLang";
import { shortDate } from "@/lib/format";
import { NotSaved, SaveRefused } from "../SaveState";
import { T } from "../T";

const KIND: Record<TaskKind, { vi: string; en: string; Icon: typeof Pill }> = {
  appointment: { vi: "Đi khám", en: "Appointment", Icon: Stethoscope },
  medicine: { vi: "Mua thuốc", en: "Medicine", Icon: Pill },
  visit: { vi: "Về thăm", en: "Visit", Icon: House },
  other: { vi: "Việc khác", en: "Other", Icon: ListTodo },
};

type Status = { state: "idle" | "saving" | "queued" } | { state: "rejected"; detail: string };

/** "Chia việc chăm sóc": who takes Mom to the clinic, buys the medicine, visits. */
export function TasksCard({
  elderId,
  tasks,
  members,
  viewer,
  todayIso,
}: {
  elderId: string;
  tasks: CareTask[];
  members: FamilyMemberRow[];
  viewer: FamilyViewer;
  todayIso: string;
}) {
  const router = useRouter();
  const lang = useLang();
  const [adding, setAdding] = useState(false);
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<TaskKind>("visit");
  const [assignee, setAssignee] = useState<string>(viewer.member_id ?? members[0]?.id ?? "");
  const [due, setDue] = useState("");
  const [status, setStatus] = useState<Status>({ state: "idle" });
  const [toggled, setToggled] = useState<Record<number, boolean>>({});
  const pending = useOutbox(elderId).filter((p) => p.kind === "task");
  const base = `/api/elders/${encodeURIComponent(elderId)}/family/tasks`;
  const open = tasks.filter((t) => !(toggled[t.id] ?? t.done));
  const done = tasks.filter((t) => toggled[t.id] ?? t.done);

  const canEdit = (t: CareTask) =>
    viewer.role === "primary" ||
    (viewer.role === "viewer" && (t.assignee_id === viewer.member_id || (t.created_by ?? "") === viewer.name));

  async function toggle(t: CareTask) {
    const next = !(toggled[t.id] ?? t.done);
    setToggled((m) => ({ ...m, [t.id]: next }));
    setStatus({ state: "saving" });
    const r = await postWrite("task", elderId, `${base}/${t.id}`, { done: next }, { meta: { taskId: t.id } });
    if (r.state === "rejected") {
      setToggled((m) => ({ ...m, [t.id]: !next }));
      return setStatus({ state: "rejected", detail: r.detail });
    }
    setStatus({ state: r.state === "queued" ? "queued" : "idle" });
    if (r.state === "saved") router.refresh();
  }

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim()) return;
    setStatus({ state: "saving" });
    const r = await postWrite("task", elderId, base, { kind, title: title.trim(), assignee_id: assignee || null, due_date: due || null }, { meta: { title: title.trim() } });
    if (r.state === "rejected") return setStatus({ state: "rejected", detail: r.detail });
    setStatus({ state: r.state === "queued" ? "queued" : "idle" });
    setTitle("");
    setDue("");
    setAdding(false);
    if (r.state === "saved") router.refresh();
  }

  const row = (t: CareTask) => {
    const k = KIND[t.kind] ?? KIND.other;
    const isDone = toggled[t.id] ?? t.done;
    const editable = canEdit(t);
    const overdue = !isDone && t.due_date != null && t.due_date < todayIso;
    return (
      <li key={t.id} className="flex items-start gap-3 py-3">
        <input
          type="checkbox"
          checked={isDone}
          disabled={!editable}
          onChange={() => toggle(t)}
          aria-label={`${lang === "en" ? "Done" : "Xong"}: ${lang === "en" ? t.title_en : t.title_vi}`}
          className="mt-1 size-6 shrink-0 accent-[var(--accent)] disabled:opacity-40"
        />
        <div className="min-w-0 flex-1">
          <p className={`font-medium leading-snug ${isDone ? "text-ink-3 line-through" : ""}`}>
            <T vi={t.title_vi} en={t.title_en} />
          </p>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm text-ink-3">
            <span className="inline-flex items-center gap-1">
              <k.Icon size={14} aria-hidden />
              <T vi={k.vi} en={k.en} />
            </span>
            {t.assignee_name && (
              <span>
                · <T vi={`${t.assignee_name}${t.assignee_id === viewer.member_id ? " (bạn)" : ""}`} en={`${t.assignee_name}${t.assignee_id === viewer.member_id ? " (you)" : ""}`} />
              </span>
            )}
            {t.due_date && (
              <span className={overdue ? "font-semibold text-red-ink" : ""}>
                · <T vi={`${overdue ? "quá hạn " : "hạn "}${shortDate(t.due_date)}`} en={`${overdue ? "overdue " : "due "}${shortDate(t.due_date)}`} />
              </span>
            )}
            {isDone && t.done_by && (
              <span>
                · <T vi={`${t.done_by} đã xong`} en={`done by ${t.done_by}`} />
              </span>
            )}
          </p>
        </div>
      </li>
    );
  };

  return (
    <section aria-labelledby="tasks-h" className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-3">
        <h2 id="tasks-h" className="flex items-center gap-2 text-sm font-bold uppercase tracking-wide text-ink-3">
          <ListChecks size={16} aria-hidden />
          <T vi="Chia việc chăm sóc" en="Care tasks" />
        </h2>
        {viewer.permissions.manage_tasks && (
          <button
            type="button"
            onClick={() => setAdding((a) => !a)}
            aria-expanded={adding}
            aria-controls="task-form"
            className="inline-flex min-h-11 items-center gap-1.5 font-semibold text-accent"
          >
            {adding ? <X size={16} aria-hidden /> : <Plus size={16} aria-hidden />}
            {adding ? <T vi="Đóng" en="Close" /> : <T vi="Thêm việc" en="Add task" />}
          </button>
        )}
      </div>

      {adding && (
        <form id="task-form" onSubmit={add} className="fade-in flex flex-col gap-2.5 rounded-2xl border border-line bg-surface p-3.5">
          <label className="flex flex-col gap-1 text-sm font-semibold text-ink-2">
            <T vi="Việc cần làm" en="What needs doing" />
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              maxLength={160}
              required
              placeholder={lang === "en" ? "e.g. Take Mom to the eye clinic" : "VD: Chở má đi khám mắt"}
              className="min-h-12 rounded-xl border border-line-strong bg-bg px-3 text-base font-normal text-ink placeholder:text-ink-3"
            />
          </label>
          <div className="grid grid-cols-2 gap-2">
            <label className="flex flex-col gap-1 text-sm font-semibold text-ink-2">
              <T vi="Loại" en="Kind" />
              <select value={kind} onChange={(e) => setKind(e.target.value as TaskKind)} className="min-h-12 rounded-xl border border-line-strong bg-bg px-2 text-base font-normal text-ink">
                {(Object.keys(KIND) as TaskKind[]).map((k) => (
                  <option key={k} value={k}>
                    {lang === "en" ? KIND[k].en : KIND[k].vi}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-sm font-semibold text-ink-2">
              <T vi="Ai làm" en="Who" />
              <select value={assignee} onChange={(e) => setAssignee(e.target.value)} className="min-h-12 rounded-xl border border-line-strong bg-bg px-2 text-base font-normal text-ink">
                {members.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="flex flex-col gap-1 text-sm font-semibold text-ink-2">
            <T vi="Hạn (không bắt buộc)" en="Due (optional)" />
            <input type="date" value={due} min={todayIso} onChange={(e) => setDue(e.target.value)} className="min-h-12 rounded-xl border border-line-strong bg-bg px-3 text-base font-normal text-ink" />
          </label>
          <button type="submit" disabled={!title.trim() || status.state === "saving"} className="min-h-12 rounded-xl bg-accent font-bold text-accent-ink disabled:opacity-40">
            <T vi="Giao việc" en="Assign" />
          </button>
        </form>
      )}

      {open.length === 0 ? (
        <p className="text-ink-2">
          <T vi="Không còn việc nào đang chờ." en="Nothing waiting." />
        </p>
      ) : (
        <ul className="divide-y divide-line">{open.map(row)}</ul>
      )}
      {done.length > 0 && (
        <details className="rounded-2xl bg-surface-2 px-4">
          <summary className="flex min-h-11 cursor-pointer list-none items-center font-semibold text-ink-2">
            <T vi={`Đã xong (${done.length})`} en={`Done (${done.length})`} />
          </summary>
          <ul className="divide-y divide-line">{done.map(row)}</ul>
        </details>
      )}
      {!viewer.permissions.full_view && (
        <p className="text-sm text-ink-3">
          <T vi="Bạn đánh dấu được việc giao cho mình hoặc do mình tạo." en="You can tick off tasks assigned to you or created by you." />
        </p>
      )}
      {(pending.length > 0 || status.state === "queued") && <NotSaved />}
      {status.state === "rejected" && <SaveRefused detail={status.detail} />}
    </section>
  );
}
