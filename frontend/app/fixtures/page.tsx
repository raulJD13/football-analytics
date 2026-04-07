"use client";

import { useEffect, useState } from "react";
import PageTransition from "@/components/ui/PageTransition";
import MatchCard from "@/components/ui/MatchCard";
import { KpiSkeleton } from "@/components/ui/CardSkeleton";
import {
  fetchFixtures,
  type FixtureEntry,
} from "@/lib/api";

export default function FixturesPage() {
  const [fixtures, setFixtures] = useState<FixtureEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const data = await fetchFixtures(12);
        if (!cancelled) {
          setFixtures(data.fixtures);
        }
      } catch (err) {
        console.error("Failed to load fixtures:", err);
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };
    void load();
    const interval = window.setInterval(load, 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  return (
    <PageTransition>
      <p className="mb-6 text-sm text-text-secondary">
        Current-season fixtures with live score polling and production-model probabilities.
      </p>
      {loading ? (
        <div className="grid grid-cols-2 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <KpiSkeleton key={i} />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4">
          {fixtures.map((f) => (
            <MatchCard
              key={f.match_id}
              matchId={f.match_id}
              homeName={f.home_team_name}
              awayName={f.away_team_name}
              status={f.status}
              homeGoals={f.home_goals}
              awayGoals={f.away_goals}
              homeWin={f.home_win ?? 0}
              draw={f.draw ?? 0}
              awayWin={f.away_win ?? 0}
              expectedHome={f.expected_home_goals ?? 0}
              expectedAway={f.expected_away_goals ?? 0}
            />
          ))}
        </div>
      )}
    </PageTransition>
  );
}
