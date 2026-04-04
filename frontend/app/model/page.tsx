"use client";

import PageTransition from "@/components/ui/PageTransition";
import KpiCard from "@/components/ui/KpiCard";
import FeatureImportance from "@/components/charts/FeatureImportance";

// Poisson model metrics from the training run
const METRICS = {
  accuracy: 54.6,
  brierScore: 0.63,
  logLoss: 1.02,
  baselineAccuracy: 48.8,
};

// Poisson model feature contributions (derived from strength parameters)
const FEATURES = [
  { name: "home_attack_strength", importance: 0.28 },
  { name: "away_defence_weakness", importance: 0.22 },
  { name: "home_advantage (1.2)", importance: 0.20 },
  { name: "league_avg_goals", importance: 0.15 },
  { name: "away_attack_strength", importance: 0.10 },
  { name: "home_defence_rate", importance: 0.05 },
];

export default function ModelPage() {
  const improvement = (METRICS.accuracy - METRICS.baselineAccuracy).toFixed(1);

  return (
    <PageTransition>
      {/* KPI row */}
      <div className="grid grid-cols-4 gap-4">
        <KpiCard title="Accuracy" value={METRICS.accuracy} suffix="%" decimals={1} />
        <KpiCard title="Brier score" value={METRICS.brierScore} decimals={2} />
        <KpiCard title="Log loss" value={METRICS.logLoss} decimals={2} />
        <KpiCard title="Baseline accuracy" value={METRICS.baselineAccuracy} suffix="%" decimals={1} />
      </div>

      {/* Feature importance chart */}
      <div className="mt-6 rounded-lg border border-border-custom bg-bg-card p-5">
        <h2 className="mb-4 text-sm font-semibold text-text-primary">
          Feature importance (Poisson model)
        </h2>
        <FeatureImportance features={FEATURES} />
      </div>

      {/* Note */}
      <div className="mt-4 rounded-lg border border-border-custom bg-bg-card p-4 text-sm text-text-secondary">
        Beats the &quot;always predict home win&quot; baseline by{" "}
        <span className="font-semibold text-win">+{improvement}pp</span>.
        Model registered in MLflow as <code className="text-indigo">poisson-match-predictor</code>{" "}
        (Production alias).
      </div>
    </PageTransition>
  );
}
