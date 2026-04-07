"use client";

import FeatureImportance from "@/components/charts/FeatureImportance";
import { useEffect, useState } from "react";
import KpiCard from "@/components/ui/KpiCard";
import PageTransition from "@/components/ui/PageTransition";
import { fetchModelMetrics, type ModelMetricsResponse } from "@/lib/api";

export default function ModelPage() {
  const [metrics, setMetrics] = useState<ModelMetricsResponse | null>(null);

  useEffect(() => {
    fetchModelMetrics().then(setMetrics).catch(console.error);
  }, []);

  if (!metrics) {
    return <PageTransition><div className="text-sm text-text-secondary">Loading model metrics…</div></PageTransition>;
  }

  const improvement = ((metrics.accuracy - metrics.baseline_accuracy) * 100).toFixed(1);

  return (
    <PageTransition>
      <div className="grid grid-cols-4 gap-4">
        <KpiCard title="Accuracy" value={metrics.accuracy * 100} suffix="%" decimals={1} />
        <KpiCard title="Brier score" value={metrics.brier_score} decimals={3} />
        <KpiCard title="Log loss" value={metrics.log_loss ?? 0} decimals={3} />
        <KpiCard title="Baseline accuracy" value={metrics.baseline_accuracy * 100} suffix="%" decimals={1} />
      </div>

      <div className="mt-6 rounded-lg border border-border-custom bg-bg-card p-5">
        <h2 className="mb-4 text-sm font-semibold text-text-primary">
          Feature importance (Production classifier)
        </h2>
        <FeatureImportance features={metrics.feature_importance} />
      </div>

      <div className="mt-4 rounded-lg border border-border-custom bg-bg-card p-4 text-sm text-text-secondary">
        Beats the &quot;always predict home win&quot; baseline by{" "}
        <span className="font-semibold text-win">+{improvement}pp</span>.
        Model registered in MLflow as <code className="text-indigo">{metrics.model_name}</code>{" "}
        (Production v{metrics.model_version}).
      </div>
    </PageTransition>
  );
}
