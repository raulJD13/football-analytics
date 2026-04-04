import ProbabilityBars from "./ProbabilityBars";

interface Props {
  homeName: string;
  awayName: string;
  homeWin: number;
  draw: number;
  awayWin: number;
  expectedHome: number;
  expectedAway: number;
}

export default function MatchCard({
  homeName,
  awayName,
  homeWin,
  draw,
  awayWin,
  expectedHome,
  expectedAway,
}: Props) {
  return (
    <div className="rounded-lg border border-border-custom bg-bg-card p-4 transition-transform duration-150 hover:-translate-y-px">
      <div className="mb-3 flex items-center justify-between text-sm font-medium text-text-primary">
        <span>{homeName}</span>
        <span className="text-xs text-text-secondary">vs</span>
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
}
