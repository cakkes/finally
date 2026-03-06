"use client";

import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { PortfolioSnapshot } from "../types";

interface PnLChartProps {
  data: PortfolioSnapshot[];
}

export default function PnLChart({ data }: PnLChartProps) {
  const chartData = data.map((s) => ({
    time: new Date(s.recorded_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    value: s.total_value,
  }));

  const values = chartData.map((d) => d.value);
  const min = values.length > 0 ? Math.min(...values) : 9900;
  const max = values.length > 0 ? Math.max(...values) : 10100;
  const padding = (max - min) * 0.1 || 50;

  return (
    <div className="flex flex-col h-full bg-bg-panel">
      <div className="px-3 py-2 border-b border-border text-xs text-text-secondary font-bold tracking-wider">
        PORTFOLIO VALUE
      </div>
      <div className="flex-1 min-h-0 p-2">
        {chartData.length === 0 ? (
          <div className="flex items-center justify-center h-full text-text-secondary text-xs">
            Awaiting data...
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <XAxis
                dataKey="time"
                tick={{ fill: "#8b949e", fontSize: 10 }}
                axisLine={{ stroke: "#30363d" }}
                tickLine={false}
              />
              <YAxis
                domain={[min - padding, max + padding]}
                tick={{ fill: "#8b949e", fontSize: 10 }}
                axisLine={{ stroke: "#30363d" }}
                tickLine={false}
                tickFormatter={(v) => `$${v.toLocaleString()}`}
              />
              <Tooltip
                contentStyle={{
                  background: "#1a1a2e",
                  border: "1px solid #30363d",
                  borderRadius: "4px",
                  color: "#e6edf3",
                  fontSize: "11px",
                }}
                formatter={(value: number | undefined) => [`$${(value ?? 0).toFixed(2)}`, "Value"]}
              />
              <Line
                type="monotone"
                dataKey="value"
                stroke="#209dd7"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 3, fill: "#209dd7" }}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
