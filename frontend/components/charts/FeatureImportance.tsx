"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  ResponsiveContainer,
  Cell,
  Tooltip,
} from "recharts";

interface Feature {
  name: string;
  importance: number;
}

interface Props {
  features: Feature[];
}

export default function FeatureImportance({ features }: Props) {
  const sorted = [...features].sort((a, b) => b.importance - a.importance);

  return (
    <ResponsiveContainer width="100%" height={sorted.length * 36 + 20}>
      <BarChart
        data={sorted}
        layout="vertical"
        margin={{ top: 0, right: 20, bottom: 0, left: 0 }}
      >
        <XAxis type="number" hide />
        <YAxis
          type="category"
          dataKey="name"
          width={160}
          tick={{ fill: "#718096", fontSize: 12 }}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "#161b27",
            border: "1px solid #1e2130",
            borderRadius: 6,
            color: "#e2e8f0",
            fontSize: 12,
          }}
          cursor={{ fill: "rgba(99,102,241,0.08)" }}
        />
        <Bar dataKey="importance" radius={[0, 4, 4, 0]}>
          {sorted.map((_, i) => (
            <Cell key={i} fill={i < 3 ? "#6366f1" : "#1e2130"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
