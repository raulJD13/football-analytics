"use client";

import { useEffect, useState } from "react";
import PageTransition from "@/components/ui/PageTransition";
import KpiCard from "@/components/ui/KpiCard";
import StandingsTable from "@/components/ui/StandingsTable";
import MatchCard from "@/components/ui/MatchCard";
import { KpiSkeleton, TableSkeleton } from "@/components/ui/CardSkeleton";
import {
  fetchStandings,
  postPredict,
  type StandingEntry,
  type PredictResponse,
} from "@/lib/api";

export default function OverviewPage() {
  const [standings, setStandings] = useState<StandingEntry[]>([]);
  const [predictions, setPredictions] = useState<
    (PredictResponse & { homeName: string; awayName: string })[]
  >([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const data = await fetchStandings();
        setStandings(data.standings);

        const top = data.standings.slice(0, 8);
        const pairs = [
          [top[0], top[1]],
          [top[2], top[3]],
          [top[4], top[5]],
          [top[6], top[7]],
        ];
        const preds = await Promise.all(
          pairs.map(async ([h, a]) => {
            const res = await postPredict({
              home_team_id: h.team_id,
              away_team_id: a.team_id,
            });
            return { ...res, homeName: h.team_name, awayName: a.team_name };
          }),
        );
        setPredictions(preds);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (error) {
    return (
      <PageTransition>
        <div className="rounded-lg border border-loss/40 bg-loss/10 p-4 text-sm text-loss">
          Failed to load dashboard data — is the API running on port 8001?
          <br />
          <span className="mt-1 block font-mono text-xs text-text-secondary">{error}</span>
        </div>
      </PageTransition>
    );
  }

  const totalMatches = standings.reduce((s, r) => s + r.played, 0) / 2;

  return (
    <PageTransition>
      <div className="grid grid-cols-4 gap-4">
        {loading ? (
          Array.from({ length: 4 }).map((_, i) => <KpiSkeleton key={i} />)
        ) : (
          <>
            <KpiCard title="Matches processed" value={totalMatches} />
            <KpiCard title="Model accuracy" value={54.6} suffix="%" decimals={1} />
            <KpiCard title="Brier score" value={0.63} decimals={2} />
            <KpiCard title="Teams tracked" value={standings.length} />
          </>
        )}
      </div>

      <div className="mt-6 grid grid-cols-2 gap-6">
        <div className="rounded-lg border border-border-custom bg-bg-card p-5">
          <h2 className="mb-4 text-sm font-semibold text-text-primary">
            Top matchup predictions
          </h2>
          {loading ? (
            <TableSkeleton rows={4} />
          ) : (
            <div className="space-y-4">
              {predictions.map((p) => (
                <MatchCard
                  key={`${p.home_team_id}-${p.away_team_id}`}
                  homeName={p.homeName}
                  awayName={p.awayName}
                  homeWin={p.home_win}
                  draw={p.draw}
                  awayWin={p.away_win}
                  expectedHome={p.expected_home_goals}
                  expectedAway={p.expected_away_goals}
                />
              ))}
            </div>
          )}
        </div>

        <div className="rounded-lg border border-border-custom bg-bg-card p-5">
          <h2 className="mb-4 text-sm font-semibold text-text-primary">
            Standings snapshot
          </h2>
          {loading ? (
            <TableSkeleton rows={5} />
          ) : (
            <StandingsTable standings={standings.slice(0, 5)} compact />
          )}
        </div>
      </div>
    </PageTransition>
  );
}
