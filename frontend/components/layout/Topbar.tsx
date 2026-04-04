"use client";

import { usePathname } from "next/navigation";

const PAGE_TITLES: Record<string, string> = {
  "/overview": "Overview",
  "/fixtures": "Fixtures",
  "/predictions": "Predictions",
  "/standings": "Standings",
  "/model": "Model metrics",
};

export default function Topbar() {
  const pathname = usePathname();
  const title =
    PAGE_TITLES[pathname] ??
    (pathname.startsWith("/teams/") ? "Team detail" : "Football Analytics");

  return (
    <header className="flex h-14 items-center justify-between border-b border-border-custom bg-bg-main px-6">
      <h1 className="text-base font-semibold text-text-primary">{title}</h1>
      <div className="flex items-center gap-4">
        {/* League selector */}
        <span className="rounded-md border border-border-custom bg-bg-card px-3 py-1 text-xs font-medium text-text-secondary">
          LaLiga
        </span>

        {/* Pipeline live indicator */}
        <div className="flex items-center gap-2 text-xs text-text-secondary">
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-win opacity-75" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-win" />
          </span>
          Pipeline live
        </div>
      </div>
    </header>
  );
}
