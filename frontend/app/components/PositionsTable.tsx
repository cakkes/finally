"use client";

import { Position } from "../types";

interface PositionsTableProps {
  positions: Position[];
}

export default function PositionsTable({ positions }: PositionsTableProps) {
  return (
    <div data-testid="positions-table" className="flex flex-col h-full bg-bg-panel">
      <div className="px-3 py-2 border-b border-border text-xs text-text-secondary font-bold tracking-wider">
        POSITIONS
      </div>
      <div className="flex-1 overflow-y-auto">
        {positions.length === 0 ? (
          <div className="flex items-center justify-center h-full text-text-secondary text-xs">
            No positions yet
          </div>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-text-secondary border-b border-border sticky top-0 bg-bg-panel">
                <th className="text-left px-3 py-1.5 font-normal">TICKER</th>
                <th className="text-right px-2 py-1.5 font-normal">QTY</th>
                <th className="text-right px-2 py-1.5 font-normal">AVG COST</th>
                <th className="text-right px-2 py-1.5 font-normal">PRICE</th>
                <th className="text-right px-2 py-1.5 font-normal">P&L</th>
                <th className="text-right px-3 py-1.5 font-normal">P&L%</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr key={p.ticker} className="border-b border-border/50 hover:bg-bg-main/50">
                  <td className="px-3 py-1.5 text-accent-yellow font-bold">{p.ticker}</td>
                  <td className="text-right px-2 py-1.5 tabular-nums">{p.quantity}</td>
                  <td className="text-right px-2 py-1.5 tabular-nums">${p.avg_cost.toFixed(2)}</td>
                  <td className="text-right px-2 py-1.5 tabular-nums">${p.current_price.toFixed(2)}</td>
                  <td
                    className={`text-right px-2 py-1.5 tabular-nums ${
                      p.unrealized_pnl >= 0 ? "text-green" : "text-red"
                    }`}
                  >
                    {p.unrealized_pnl >= 0 ? "+" : ""}${p.unrealized_pnl.toFixed(2)}
                  </td>
                  <td
                    className={`text-right px-3 py-1.5 tabular-nums ${
                      p.pnl_pct >= 0 ? "text-green" : "text-red"
                    }`}
                  >
                    {p.pnl_pct >= 0 ? "+" : ""}{p.pnl_pct.toFixed(2)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
