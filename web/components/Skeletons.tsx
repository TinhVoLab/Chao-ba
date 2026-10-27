export function PageSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-4 pt-2" aria-busy="true" aria-live="polite">
      <div className="flex gap-2">
        <div className="skeleton h-12 w-36 rounded-full" />
        <div className="skeleton h-12 w-32 rounded-full" />
        <div className="skeleton h-12 w-32 rounded-full" />
      </div>
      <div className="skeleton h-9 w-48" />
      <div className="skeleton h-56" />
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton h-20" />
      ))}
      <span className="sr-only">Đang tải / Loading</span>
    </div>
  );
}
