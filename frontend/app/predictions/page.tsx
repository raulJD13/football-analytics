"use client";

import { useEffect, useState } from "react";
import PageTransition from "@/components/ui/PageTransition";
import ProbabilityBars from "@/components/ui/ProbabilityBars";
import { TableSkeleton } from "@/components/ui/CardSkeleton";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  fetchStandings,
  postPredictExplain,
  type StandingEntry,
  type PredictExplainResponse,
} from "@/lib/api";

export default function PredictionsPage() {
  const [teams, setTeams] = useState<StandingEntry[]>([]);
  const [homeId, setHomeId] = useState<string>("");
  const [awayId, setAwayId] = useState<string>("");
  const [result, setResult] = useState<PredictExplainResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [teamsLoading, setTeamsLoading] = useState(true);

  useEffect(() => {
    fetchStandings()
      .then((d) => setTeams(d.standings))
      .catch(console.error)
      .finally(() => setTeamsLoading(false));
  }, []);

  const homeName = teams.find((t) => String(t.team_id) === homeId)?.team_name ?? "";
  const awayName = teams.find((t) => String(t.team_id) === awayId)?.team_name ?? "";

  async function handlePredict() {
    if (!homeId || !awayId || homeId === awayId) return;
    setLoading(true);
    setResult(null);
    try {
      const res = await postPredictExplain({
        home_team_id: Number(homeId),
        away_team_id: Number(awayId),
      });
      setResult(res);
    } catch (err) {
      console.error("Prediction failed:", err);
    } finally {
      setLoading(false);
    }
  }

  // Confidence heuristic based on how "decisive" the probabilities are
  function confidence(r: PredictExplainResponse): string {
    const max = Math.max(r.home_win, r.draw, r.away_win);
    if (max > 0.55) return "High";
    if (max > 0.4) return "Medium";
    return "Low";
  }

  return (
    <PageTransition>
      <p className="mb-6 text-sm text-text-secondary">
        Select two teams and predict match outcome probabilities.
      </p>

      {teamsLoading ? (
        <TableSkeleton rows={3} />
      ) : (
        <div className="mx-auto max-w-xl space-y-6">
          {/* Team selectors */}
          <div className="grid grid-cols-[1fr_auto_1fr] items-end gap-4">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-text-secondary">
                Home team
              </label>
              <Select value={homeId} onValueChange={(v) => setHomeId(v ?? "")}>
                <SelectTrigger className="w-full bg-bg-card border-border-custom text-text-primary">
                  <SelectValue placeholder="Select home team" />
                </SelectTrigger>
                <SelectContent className="bg-bg-card border-border-custom">
                  {teams.map((t) => (
                    <SelectItem
                      key={t.team_id}
                      value={String(t.team_id)}
                      disabled={String(t.team_id) === awayId}
                      className="text-text-primary"
                    >
                      {t.team_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <span className="pb-2 text-sm font-medium text-text-secondary">vs</span>

            <div>
              <label className="mb-1.5 block text-xs font-medium text-text-secondary">
                Away team
              </label>
              <Select value={awayId} onValueChange={(v) => setAwayId(v ?? "")}>
                <SelectTrigger className="w-full bg-bg-card border-border-custom text-text-primary">
                  <SelectValue placeholder="Select away team" />
                </SelectTrigger>
                <SelectContent className="bg-bg-card border-border-custom">
                  {teams.map((t) => (
                    <SelectItem
                      key={t.team_id}
                      value={String(t.team_id)}
                      disabled={String(t.team_id) === homeId}
                      className="text-text-primary"
                    >
                      {t.team_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          {/* Predict button */}
          <Button
            onClick={handlePredict}
            disabled={!homeId || !awayId || homeId === awayId || loading}
            className="w-full bg-indigo hover:bg-indigo/80 text-white"
          >
            {loading ? "Predicting..." : "Predict"}
          </Button>

          {/* Result */}
          {result && (
            <div className="rounded-lg border border-border-custom bg-bg-card p-6 space-y-5">
              <div className="flex items-center justify-between text-sm font-medium text-text-primary">
                <span>{homeName}</span>
                <span className="text-xs text-text-secondary">vs</span>
                <span>{awayName}</span>
              </div>

              <ProbabilityBars
                homeWin={result.home_win}
                draw={result.draw}
                awayWin={result.away_win}
                homeLabel={homeName.slice(0, 12)}
                awayLabel={awayName.slice(0, 12)}
              />

              <div className="flex justify-between text-xs text-text-secondary">
                <span>Expected goals: {result.expected_home_goals.toFixed(1)}</span>
                <span>Expected goals: {result.expected_away_goals.toFixed(1)}</span>
              </div>

              <div className="border-t border-border-custom pt-3 text-xs text-text-secondary">
                Model: {result.model_version} · Confidence:{" "}
                <span
                  className={
                    confidence(result) === "High"
                      ? "text-win"
                      : confidence(result) === "Medium"
                        ? "text-yellow-400"
                        : "text-loss"
                  }
                >
                  {confidence(result)}
                </span>
              </div>

              {result.top_contributions.length > 0 ? (
                <div className="border-t border-border-custom pt-4">
                  <p className="mb-3 text-xs font-semibold uppercase tracking-wide text-text-secondary">
                    SHAP explanation · {result.explanation_label}
                  </p>
                  <div className="space-y-2">
                    {result.top_contributions.map((item) => (
                      <div key={item.feature} className="flex items-center justify-between text-xs">
                        <div>
                          <p className="font-medium text-text-primary">{item.feature}</p>
                          <p className="text-text-secondary">value {item.value.toFixed(3)}</p>
                        </div>
                        <span className={item.contribution >= 0 ? "text-win" : "text-loss"}>
                          {item.contribution >= 0 ? "+" : ""}
                          {item.contribution.toFixed(3)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          )}
        </div>
      )}
    </PageTransition>
  );
}
