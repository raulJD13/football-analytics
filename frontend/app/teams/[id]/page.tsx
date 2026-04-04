"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import PageTransition from "@/components/ui/PageTransition";
import FormDots from "@/components/ui/FormDots";
import { TableSkeleton } from "@/components/ui/CardSkeleton";
import {
  fetchTeamStats,
  fetchTeamForm,
  type TeamStatsResponse,
  type FormMatch,
} from "@/lib/api";

function StatBlock({
  title,
  stats,
}: {
  title: string;
  stats: TeamStatsResponse["home"];
}) {
  return (
    <div className="rounded-lg border border-border-custom bg-bg-card p-5">
      <h3 className="mb-4 text-sm font-semibold text-text-primary">{title}</h3>
      <dl className="grid grid-cols-2 gap-y-3 gap-x-6 text-sm">
        {([
          ["Goals / match", stats.avg_goals_scored?.toFixed(2) ?? "-"],
          ["Conceded / match", stats.avg_goals_conceded?.toFixed(2) ?? "-"],
          ["Pts / match", stats.points_per_game.toFixed(2)],
          ["Clean sheets", stats.clean_sheets],
          ["Record", `${stats.won}W ${stats.drawn}D ${stats.lost}L`],
          ["Def. variance", stats.defensive_variance?.toFixed(2) ?? "-"],
        ] as const).map(([label, value]) => (
          <div key={label}>
            <dt className="text-xs text-text-secondary">{label}</dt>
            <dd className="mt-0.5 font-medium tabular-nums text-text-primary">
              {value}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export default function TeamDetailPage() {
  const params = useParams();
  const teamId = Number(params.id);

  const [stats, setStats] = useState<TeamStatsResponse | null>(null);
  const [form, setForm] = useState<FormMatch[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!teamId) return;
    Promise.all([fetchTeamStats(teamId), fetchTeamForm(teamId)])
      .then(([s, f]) => {
        setStats(s);
        setForm(f.matches);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [teamId]);

  if (loading) {
    return (
      <PageTransition>
        <TableSkeleton rows={10} />
      </PageTransition>
    );
  }

  if (!stats) {
    return (
      <PageTransition>
        <p className="text-text-secondary">Team not found.</p>
      </PageTransition>
    );
  }

  const formStr = form
    .slice(0, 5)
    .map((m) => m.outcome)
    .reverse()
    .join("");

  return (
    <PageTransition>
      <div className="mb-6 flex items-center gap-4">
        <h2 className="text-xl font-semibold text-text-primary">
          {stats.team_name}
        </h2>
        {formStr && <FormDots form={formStr} />}
      </div>

      {/* Home vs Away cards */}
      <div className="grid grid-cols-2 gap-6">
        <StatBlock title="Home" stats={stats.home} />
        <StatBlock title="Away" stats={stats.away} />
      </div>

      {/* Strength metrics */}
      <div className="mt-6 grid grid-cols-2 gap-6">
        <div className="rounded-lg border border-border-custom bg-bg-card p-5">
          <p className="text-xs text-text-secondary">Home attack strength</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums text-indigo">
            {stats.home_attack_strength?.toFixed(3) ?? "-"}
          </p>
        </div>
        <div className="rounded-lg border border-border-custom bg-bg-card p-5">
          <p className="text-xs text-text-secondary">Away defence weakness</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums text-indigo">
            {stats.away_defence_weakness?.toFixed(3) ?? "-"}
          </p>
        </div>
      </div>

      {/* Recent form table */}
      <div className="mt-6 rounded-lg border border-border-custom bg-bg-card p-5">
        <h3 className="mb-4 text-sm font-semibold text-text-primary">
          Last 10 matches
        </h3>
        <table className="w-full text-left text-sm tabular-nums">
          <thead>
            <tr className="border-b border-border-custom text-xs font-medium text-text-secondary">
              <th className="py-2 pr-3">Date</th>
              <th className="py-2 pr-3">H/A</th>
              <th className="py-2 pr-3">Opponent</th>
              <th className="py-2 pr-3 text-center">Score</th>
              <th className="py-2 pr-3 text-center">Result</th>
              <th className="py-2 text-center">Pts</th>
            </tr>
          </thead>
          <tbody>
            {form.map((m) => (
              <tr
                key={m.match_id}
                className="border-b border-border-custom/50 hover:bg-bg-card/60 transition-colors"
              >
                <td className="py-2 pr-3 text-text-secondary">{m.match_date}</td>
                <td className="py-2 pr-3 text-text-secondary">
                  {m.is_home ? "H" : "A"}
                </td>
                <td className="py-2 pr-3 text-text-primary">
                  {m.opponent_team_id}
                </td>
                <td className="py-2 pr-3 text-center text-text-primary">
                  {m.team_goals ?? "-"} - {m.opponent_goals ?? "-"}
                </td>
                <td className="py-2 pr-3 text-center">
                  <span
                    className={
                      m.outcome === "W"
                        ? "text-win font-semibold"
                        : m.outcome === "L"
                          ? "text-loss font-semibold"
                          : "text-draw"
                    }
                  >
                    {m.outcome}
                  </span>
                </td>
                <td className="py-2 text-center text-text-secondary">{m.points}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </PageTransition>
  );
}
