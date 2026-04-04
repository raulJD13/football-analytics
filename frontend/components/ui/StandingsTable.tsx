"use client";

import Link from "next/link";
import FormDots from "./FormDots";
import type { StandingEntry } from "@/lib/api";

interface Props {
  standings: StandingEntry[];
  compact?: boolean; // true = top-5 preview (no projected_points)
}

export default function StandingsTable({ standings, compact = false }: Props) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm tabular-nums">
        <thead>
          <tr className="border-b border-border-custom text-xs font-medium text-text-secondary">
            <th className="py-2 pr-2 w-8">#</th>
            <th className="py-2 pr-3">Team</th>
            <th className="py-2 px-2 text-center">PJ</th>
            {!compact && (
              <>
                <th className="py-2 px-2 text-center">G</th>
                <th className="py-2 px-2 text-center">E</th>
                <th className="py-2 px-2 text-center">P</th>
                <th className="py-2 px-2 text-center">GF</th>
                <th className="py-2 px-2 text-center">GC</th>
                <th className="py-2 px-2 text-center">Dif</th>
              </>
            )}
            <th className="py-2 px-2">Form</th>
            <th className="py-2 px-2 text-center">Pts</th>
            {!compact && <th className="py-2 px-2 text-center">Proj</th>}
          </tr>
        </thead>
        <tbody>
          {standings.map((s) => (
            <tr
              key={s.team_id}
              className="border-b border-border-custom/50 hover:bg-bg-card/60 transition-colors"
            >
              <td className="py-2 pr-2 text-text-secondary">{s.position}</td>
              <td className="py-2 pr-3 font-medium text-text-primary">
                <Link
                  href={`/teams/${s.team_id}`}
                  className="hover:text-indigo transition-colors"
                >
                  {s.team_name}
                </Link>
              </td>
              <td className="py-2 px-2 text-center text-text-secondary">
                {s.played}
              </td>
              {!compact && (
                <>
                  <td className="py-2 px-2 text-center text-text-secondary">{s.won}</td>
                  <td className="py-2 px-2 text-center text-text-secondary">{s.drawn}</td>
                  <td className="py-2 px-2 text-center text-text-secondary">{s.lost}</td>
                  <td className="py-2 px-2 text-center text-text-secondary">{s.goals_for ?? "-"}</td>
                  <td className="py-2 px-2 text-center text-text-secondary">{s.goals_against ?? "-"}</td>
                  <td className="py-2 px-2 text-center text-text-secondary">{s.goal_difference ?? "-"}</td>
                </>
              )}
              <td className="py-2 px-2">
                <FormDots form={s.form_last_5} />
              </td>
              <td className="py-2 px-2 text-center font-semibold text-text-primary">
                {s.points}
              </td>
              {!compact && (
                <td className="py-2 px-2 text-center text-win font-medium">
                  {s.projected_points}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
