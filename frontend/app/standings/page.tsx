"use client";

import { useEffect, useState } from "react";
import PageTransition from "@/components/ui/PageTransition";
import StandingsTable from "@/components/ui/StandingsTable";
import { TableSkeleton } from "@/components/ui/CardSkeleton";
import { fetchStandings, type StandingEntry } from "@/lib/api";

export default function StandingsPage() {
  const [standings, setStandings] = useState<StandingEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchStandings()
      .then((d) => setStandings(d.standings))
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }, []);

  if (error) {
    return (
      <PageTransition>
        <div className="rounded-lg border border-loss/40 bg-loss/10 p-4 text-sm text-loss">
          Failed to load standings — is the API running on port 8001?
          <br />
          <span className="mt-1 block font-mono text-xs text-text-secondary">{error}</span>
        </div>
      </PageTransition>
    );
  }

  return (
    <PageTransition>
      <div className="rounded-lg border border-border-custom bg-bg-card p-5">
        {loading ? (
          <TableSkeleton rows={20} />
        ) : (
          <StandingsTable standings={standings} />
        )}
      </div>
    </PageTransition>
  );
}
