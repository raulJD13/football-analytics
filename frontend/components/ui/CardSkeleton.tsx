import { Skeleton } from "@/components/ui/skeleton";

export function KpiSkeleton() {
  return (
    <div className="rounded-lg border border-border-custom bg-bg-card p-5">
      <Skeleton className="h-3 w-24 bg-border-custom" />
      <Skeleton className="mt-3 h-7 w-16 bg-border-custom" />
    </div>
  );
}

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-8 w-full bg-border-custom" />
      ))}
    </div>
  );
}
