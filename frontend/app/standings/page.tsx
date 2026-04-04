"use client";

import { useEffect, useState } from "react";
import PageTransition from "@/components/ui/PageTransition";
import StandingsTable from "@/components/ui/StandingsTable";
import { TableSkeleton } from "@/components/ui/CardSkeleton";
import { fetchStandings, type StandingEntry } from "@/lib/api";

export default function StandingsPage() {
  const [standings, setStandings] = useState<StandingEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchStandings()
      .then((d) => setStandings(d.standings))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

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
