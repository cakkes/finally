"use client";

import { useState, useRef, useEffect } from "react";
import { PriceData } from "../types";

interface WatchlistPanelProps {
  tickers: string[];
  prices: Map<string, PriceData>;
  priceHistory: Map<string, number[]>;
  flashTickers: Map<string, "up" | "down">;
  selectedTicker: string;
  onSelectTicker: (ticker: string) => void;
  onAddTicker: (ticker: string) => void;
  onRemoveTicker: (ticker: string) => void;
}

function Sparkline({ data }: { data: number[] }) {
  if (data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const w = 60;
  const h = 20;
  const points = data.map((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - ((v - min) / range) * h;
    return `${x},${y}`;
  }).join(" ");
  const lastPrice = data[data.length - 1];
  const firstPrice = data[0];
  const color = lastPrice >= firstPrice ? "#00c853" : "#ff1744";

  return (
    <svg width={w} height={h} className="inline-block">
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default function WatchlistPanel({
  tickers,
  prices,
  priceHistory,
  flashTickers,
  selectedTicker,
  onSelectTicker,
  onAddTicker,
  onRemoveTicker,
}: WatchlistPanelProps) {
  const [newTicker, setNewTicker] = useState("");
  const [hoveredTicker, setHoveredTicker] = useState<string | null>(null);

  const handleAdd = () => {
    if (newTicker.trim()) {
      onAddTicker(newTicker.trim().toUpperCase());
      setNewTicker("");
    }
  };

  return (
    <div data-testid="watchlist" className="flex flex-col h-full bg-bg-panel border-r border-border">
      <div className="px-3 py-2 border-b border-border text-xs text-text-secondary font-bold tracking-wider">
        WATCHLIST
      </div>
      <div className="flex-1 overflow-y-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-text-secondary border-b border-border">
              <th className="text-left px-3 py-1 font-normal">TICKER</th>
              <th className="text-right px-2 py-1 font-normal">PRICE</th>
              <th className="text-right px-2 py-1 font-normal">CHG%</th>
              <th className="px-2 py-1 font-normal"></th>
            </tr>
          </thead>
          <tbody>
            {tickers.map((ticker) => {
              const data = prices.get(ticker);
              const price = data?.price ?? 0;
              const prevPrice = data?.previous_price ?? price;
              const changePct = prevPrice ? ((price - prevPrice) / prevPrice) * 100 : 0;
              const flash = flashTickers.get(ticker);
              const history = priceHistory.get(ticker) || [];
              const isSelected = selectedTicker === ticker;

              return (
                <tr
                  key={ticker}
                  data-testid="watchlist-row"
                  data-ticker={ticker}
                  className={`cursor-pointer border-b border-border/50 hover:bg-bg-main/50 transition-colors ${
                    isSelected ? "bg-bg-main" : ""
                  } ${flash === "up" ? "flash-green" : flash === "down" ? "flash-red" : ""}`}
                  onClick={() => onSelectTicker(ticker)}
                  onMouseEnter={() => setHoveredTicker(ticker)}
                  onMouseLeave={() => setHoveredTicker(null)}
                >
                  <td className="px-3 py-1.5 text-accent-yellow font-bold">{ticker}</td>
                  <td className="text-right px-2 py-1.5 font-medium tabular-nums">
                    {price > 0 ? price.toFixed(2) : "--"}
                  </td>
                  <td
                    className={`text-right px-2 py-1.5 tabular-nums ${
                      changePct > 0 ? "text-green" : changePct < 0 ? "text-red" : "text-text-secondary"
                    }`}
                  >
                    {changePct !== 0 ? `${changePct > 0 ? "+" : ""}${changePct.toFixed(2)}%` : "--"}
                  </td>
                  <td className="px-2 py-1.5 w-16">
                    {hoveredTicker === ticker ? (
                      <button
                        data-testid={`remove-ticker-${ticker}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          onRemoveTicker(ticker);
                        }}
                        className="text-text-secondary hover:text-red text-xs"
                      >
                        X
                      </button>
                    ) : (
                      <Sparkline data={history} />
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="flex border-t border-border p-2 gap-1">
        <input
          type="text"
          value={newTicker}
          onChange={(e) => setNewTicker(e.target.value.toUpperCase())}
          onKeyDown={(e) => e.key === "Enter" && handleAdd()}
          placeholder="Add ticker"
          data-testid="add-ticker-input"
          className="flex-1 bg-bg-main border border-border rounded px-2 py-1 text-xs text-text-primary placeholder:text-text-secondary/50 outline-none focus:border-blue"
          maxLength={10}
        />
        <button
          onClick={handleAdd}
          data-testid="add-ticker-button"
          className="bg-blue/20 text-blue border border-blue/30 rounded px-2 py-1 text-xs hover:bg-blue/30 transition-colors"
        >
          +
        </button>
      </div>
    </div>
  );
}
