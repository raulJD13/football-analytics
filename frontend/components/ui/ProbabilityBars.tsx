"use client";

import { motion } from "framer-motion";

interface Props {
  homeWin: number;
  draw: number;
  awayWin: number;
  homeLabel?: string;
  awayLabel?: string;
}

export default function ProbabilityBars({
  homeWin,
  draw,
  awayWin,
  homeLabel = "Home",
  awayLabel = "Away",
}: Props) {
  const bars = [
    { label: homeLabel, pct: homeWin, color: "bg-win" },
    { label: "Draw", pct: draw, color: "bg-draw" },
    { label: awayLabel, pct: awayWin, color: "bg-loss" },
  ];

  return (
    <div className="space-y-2">
      {bars.map((b) => (
        <div key={b.label} className="flex items-center gap-3">
          <span className="w-14 shrink-0 text-right text-xs text-text-secondary">
            {b.label}
          </span>
          <div className="relative h-5 flex-1 overflow-hidden rounded bg-bg-main">
            <motion.div
              className={`absolute inset-y-0 left-0 rounded ${b.color}`}
              initial={{ width: 0 }}
              animate={{ width: `${(b.pct * 100).toFixed(1)}%` }}
              transition={{ duration: 0.6, ease: "easeOut" }}
            />
          </div>
          <span className="w-12 text-right text-xs font-medium tabular-nums text-text-primary">
            {(b.pct * 100).toFixed(1)}%
          </span>
        </div>
      ))}
    </div>
  );
}
