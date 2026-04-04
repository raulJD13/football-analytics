"use client";

import { useEffect, useState } from "react";
import PageTransition from "@/components/ui/PageTransition";
import MatchCard from "@/components/ui/MatchCard";
import { KpiSkeleton } from "@/components/ui/CardSkeleton";
import {
  fetchStandings,
  postPredict,
  type StandingEntry,
  type PredictResponse,
} from "@/lib/api";

export default function FixturesPage() {
  const [fixtures, setFixtures] = useState<
    (PredictResponse & { homeName: string; awayName: string })[]
  >([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const data = await fetchStandings();
        const teams = data.standings;

        // Generate round-robin matchday from all teams (top 10 pairs)
        const pairs: [StandingEntry, StandingEntry][] = [];
        for (let i = 0; i < teams.length - 1 && pairs.length < 10; i += 2) {
          pairs.push([teams[i], teams[i + 1]]);
        }

        const results = await Promise.all(
          pairs.map(async ([h, a]) => {
            const res = await postPredict({
              home_team_id: h.team_id,
              away_team_id: a.team_id,
            });
            return { ...res, homeName: h.team_name, awayName: a.team_name };
          }),
        );
        setFixtures(results);
      } catch (err) {
        console.error("Failed to load fixtures:", err);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <PageTransition>
      <p className="mb-6 text-sm text-text-secondary">
        Simulated fixture predictions between all LaLiga teams.
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
              key={`${f.home_team_id}-${f.away_team_id}`}
              homeName={f.homeName}
              awayName={f.awayName}
              homeWin={f.home_win}
              draw={f.draw}
              awayWin={f.away_win}
              expectedHome={f.expected_home_goals}
              expectedAway={f.expected_away_goals}
            />
          ))}
        </div>
      )}
    </PageTransition>
  );
}
