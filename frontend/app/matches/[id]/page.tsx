"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import MatchCard from "@/components/ui/MatchCard";
import PageTransition from "@/components/ui/PageTransition";
import { fetchMatchDetail, type MatchDetailResponse } from "@/lib/api";

export default function MatchDetailPage() {
  const params = useParams();
  const matchId = Number(params.id);
  const [detail, setDetail] = useState<MatchDetailResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!matchId) return;
    fetchMatchDetail(matchId)
      .then(setDetail)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [matchId]);

  if (error) {
    return <PageTransition><div className="text-sm text-loss">{error}</div></PageTransition>;
  }
  if (!detail) {
    return <PageTransition><div className="text-sm text-text-secondary">Loading match detail…</div></PageTransition>;
  }

  return (
    <PageTransition>
      <div className="space-y-6">
        <MatchCard
          matchId={detail.fixture.match_id}
          homeName={detail.fixture.home_team_name}
          awayName={detail.fixture.away_team_name}
          status={detail.fixture.status}
          homeGoals={detail.fixture.home_goals}
          awayGoals={detail.fixture.away_goals}
          homeWin={detail.fixture.home_win ?? 0}
          draw={detail.fixture.draw ?? 0}
          awayWin={detail.fixture.away_win ?? 0}
          expectedHome={detail.fixture.expected_home_goals ?? 0}
          expectedAway={detail.fixture.expected_away_goals ?? 0}
        />

        <div className="grid grid-cols-2 gap-6">
          <div className="rounded-lg border border-border-custom bg-bg-card p-5">
            <h2 className="mb-4 text-sm font-semibold text-text-primary">Home form</h2>
            <div className="space-y-2 text-sm">
              {detail.home_form.map((match) => (
                <div key={match.match_id} className="flex justify-between text-text-secondary">
                  <span>{match.match_date}</span>
                  <span>{match.outcome} · {match.team_goals}-{match.opponent_goals}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-lg border border-border-custom bg-bg-card p-5">
            <h2 className="mb-4 text-sm font-semibold text-text-primary">Away form</h2>
            <div className="space-y-2 text-sm">
              {detail.away_form.map((match) => (
                <div key={match.match_id} className="flex justify-between text-text-secondary">
                  <span>{match.match_date}</span>
                  <span>{match.outcome} · {match.team_goals}-{match.opponent_goals}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-6">
          <div className="rounded-lg border border-border-custom bg-bg-card p-5">
            <h2 className="mb-4 text-sm font-semibold text-text-primary">Head-to-head</h2>
            <div className="space-y-2 text-sm">
              {detail.head_to_head.map((match) => (
                <div key={match.match_id} className="flex justify-between text-text-secondary">
                  <span>{match.match_date}</span>
                  <span>{match.home_team_name} {match.home_goals}-{match.away_goals} {match.away_team_name}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-lg border border-border-custom bg-bg-card p-5">
            <h2 className="mb-4 text-sm font-semibold text-text-primary">
              Model explanation {detail.explanation_label ? `· ${detail.explanation_label}` : ""}
            </h2>
            <div className="space-y-2 text-sm">
              {detail.top_contributions.length > 0 ? (
                detail.top_contributions.map((item) => (
                  <div key={item.feature} className="flex items-center justify-between text-text-secondary">
                    <span>{item.feature}</span>
                    <span className={item.contribution >= 0 ? "text-win" : "text-loss"}>
                      {item.contribution >= 0 ? "+" : ""}
                      {item.contribution.toFixed(3)}
                    </span>
                  </div>
                ))
              ) : (
                <p className="text-text-secondary">No SHAP explanation available for this fixture.</p>
              )}
            </div>
          </div>
        </div>
      </div>
    </PageTransition>
  );
}
