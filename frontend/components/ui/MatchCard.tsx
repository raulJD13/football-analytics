import Link from "next/link";
import ProbabilityBars from "./ProbabilityBars";

interface Props {
  matchId?: number;
  homeName: string;
  awayName: string;
  status?: string;
  homeGoals?: number | null;
  awayGoals?: number | null;
  homeWin: number;
  draw: number;
  awayWin: number;
  expectedHome: number;
  expectedAway: number;
}

export default function MatchCard({
  matchId,
  homeName,
  awayName,
  status,
  homeGoals,
  awayGoals,
  homeWin,
  draw,
  awayWin,
  expectedHome,
  expectedAway,
}: Props) {
  const content = (
    <div className="rounded-lg border border-border-custom bg-bg-card p-4 transition-transform duration-150 hover:-translate-y-px">
      <div className="mb-3 flex items-center justify-between text-sm font-medium text-text-primary">
        <span>{homeName}</span>
        <div className="text-center">
          <span className="text-xs text-text-secondary">
            {homeGoals != null && awayGoals != null ? `${homeGoals} - ${awayGoals}` : "vs"}
          </span>
          {status ? (
            <span className="block text-[10px] uppercase tracking-wide text-text-secondary">
              {status}
            </span>
          ) : null}
        </div>
        <span>{awayName}</span>
      </div>
      <ProbabilityBars
        homeWin={homeWin}
        draw={draw}
        awayWin={awayWin}
        homeLabel={homeName.slice(0, 12)}
        awayLabel={awayName.slice(0, 12)}
      />
      <div className="mt-2 flex justify-between text-[11px] text-text-secondary">
        <span>xG {expectedHome.toFixed(1)}</span>
        <span>xG {expectedAway.toFixed(1)}</span>
      </div>
    </div>
  );

  if (matchId == null) {
    return content;
  }

  return (
    <Link href={`/matches/${matchId}`} className="block">
      {content}
    </Link>
  );
}
