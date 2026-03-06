"use client";

import { useState } from "react";
import { TradeResponse } from "../types";

interface TradeBarProps {
  onTrade: (ticker: string, quantity: number, side: "buy" | "sell") => Promise<TradeResponse>;
  selectedTicker: string;
}

export default function TradeBar({ onTrade, selectedTicker }: TradeBarProps) {
  const [ticker, setTicker] = useState("");
  const [quantity, setQuantity] = useState("");
  const [result, setResult] = useState<{ message: string; success: boolean } | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const activeTicker = ticker || selectedTicker;

  const handleTrade = async (side: "buy" | "sell") => {
    const qty = parseFloat(quantity);
    if (!activeTicker || !qty || qty <= 0) return;

    setSubmitting(true);
    const res = await onTrade(activeTicker.toUpperCase(), qty, side);
    setSubmitting(false);

    if (res.success && res.trade) {
      setResult({
        message: `${side === "buy" ? "Bought" : "Sold"} ${res.trade.quantity} ${res.trade.ticker} @ $${res.trade.price.toFixed(2)}`,
        success: true,
      });
      setQuantity("");
    } else {
      setResult({ message: res.error || "Trade failed", success: false });
    }

    setTimeout(() => setResult(null), 3000);
  };

  return (
    <div data-testid="trade-bar" className="flex items-center gap-2 px-3 py-2 bg-bg-panel border-t border-border">
      <span className="text-xs text-text-secondary font-bold tracking-wider mr-1">TRADE</span>
      <input
        type="text"
        value={ticker}
        onChange={(e) => setTicker(e.target.value.toUpperCase())}
        data-testid="trade-ticker"
        placeholder={selectedTicker || "TICKER"}
        className="w-20 bg-bg-main border border-border rounded px-2 py-1 text-xs text-text-primary placeholder:text-text-secondary/50 outline-none focus:border-blue"
        maxLength={10}
      />
      <input
        type="number"
        value={quantity}
        onChange={(e) => setQuantity(e.target.value)}
        data-testid="trade-quantity"
        placeholder="QTY"
        className="w-16 bg-bg-main border border-border rounded px-2 py-1 text-xs text-text-primary placeholder:text-text-secondary/50 outline-none focus:border-blue"
        min="0"
        step="1"
      />
      <button
        data-testid="buy-button"
        onClick={() => handleTrade("buy")}
        disabled={submitting || !activeTicker || !quantity}
        className="bg-green/20 text-green border border-green/30 rounded px-3 py-1 text-xs font-bold hover:bg-green/30 transition-colors disabled:opacity-40"
      >
        BUY
      </button>
      <button
        data-testid="sell-button"
        onClick={() => handleTrade("sell")}
        disabled={submitting || !activeTicker || !quantity}
        className="bg-red/20 text-red border border-red/30 rounded px-3 py-1 text-xs font-bold hover:bg-red/30 transition-colors disabled:opacity-40"
      >
        SELL
      </button>
      {result && (
        <span className={`text-xs ml-2 ${result.success ? "text-green" : "text-red"}`}>
          {result.message}
        </span>
      )}
    </div>
  );
}
