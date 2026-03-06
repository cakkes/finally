"use client";

import { Position } from "../types";

interface PortfolioHeatmapProps {
  positions: Position[];
  totalValue: number;
}

function getPnLColor(pnlPct: number): string {
  if (pnlPct > 5) return "#00c853";
  if (pnlPct > 0) return "#00c85380";
  if (pnlPct === 0) return "#ecad0a60";
  if (pnlPct > -5) return "#ff174480";
  return "#ff1744";
}

export default function PortfolioHeatmap({ positions, totalValue }: PortfolioHeatmapProps) {
  if (positions.length === 0) {
    return (
      <div data-testid="portfolio-heatmap" className="flex items-center justify-center h-full bg-bg-panel text-text-secondary text-xs">
        No positions to display
      </div>
    );
  }

  const positionsWithValue = positions.map((p) => ({
    ...p,
    marketValue: p.quantity * p.current_price,
  }));

  const totalPositionValue = positionsWithValue.reduce((sum, p) => sum + p.marketValue, 0);

  return (
    <div data-testid="portfolio-heatmap" className="flex flex-col h-full bg-bg-panel">
      <div className="px-3 py-2 border-b border-border text-xs text-text-secondary font-bold tracking-wider">
        PORTFOLIO HEATMAP
      </div>
      <div className="flex-1 flex flex-wrap content-start p-1 gap-1 overflow-hidden min-h-0">
        {positionsWithValue
          .sort((a, b) => b.marketValue - a.marketValue)
          .map((p) => {
            const weight = totalPositionValue > 0 ? (p.marketValue / totalPositionValue) * 100 : 0;
            const minWidth = Math.max(weight, 15);

            return (
              <div
                key={p.ticker}
                className="rounded flex flex-col items-center justify-center text-xs font-bold overflow-hidden"
                style={{
                  backgroundColor: getPnLColor(p.pnl_pct),
                  flexBasis: `${minWidth}%`,
                  flexGrow: weight > 20 ? 2 : 1,
                  minHeight: "40px",
                  padding: "4px",
                }}
              >
                <span className="text-white text-shadow">{p.ticker}</span>
                <span className="text-white/80 text-[10px]">
                  {p.pnl_pct > 0 ? "+" : ""}
                  {p.pnl_pct.toFixed(1)}%
                </span>
              </div>
            );
          })}
      </div>
    </div>
  );
}
