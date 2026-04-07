"use client";

import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface Point {
  match_date: string;
  cumulative_expected_goals_for: number;
  cumulative_expected_goals_against: number;
}

export default function XgTrendChart({ points }: { points: Point[] }) {
  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={points} margin={{ top: 12, right: 20, left: 0, bottom: 0 }}>
        <XAxis
          dataKey="match_date"
          tick={{ fill: "#718096", fontSize: 12 }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis tick={{ fill: "#718096", fontSize: 12 }} axisLine={false} tickLine={false} />
        <Tooltip
          contentStyle={{
            backgroundColor: "#161b27",
            border: "1px solid #1e2130",
            borderRadius: 6,
            color: "#e2e8f0",
            fontSize: 12,
          }}
        />
        <Line
          type="monotone"
          dataKey="cumulative_expected_goals_for"
          stroke="#22c55e"
          strokeWidth={2.5}
          dot={false}
          name="Cumulative xG"
        />
        <Line
          type="monotone"
          dataKey="cumulative_expected_goals_against"
          stroke="#ef4444"
          strokeWidth={2.5}
          dot={false}
          name="Cumulative xGA"
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
