"use client";

import { useState, useEffect, useCallback } from "react";
import { Portfolio, TradeRequest, TradeResponse, PortfolioSnapshot } from "../types";

export function usePortfolio() {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [history, setHistory] = useState<PortfolioSnapshot[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchPortfolio = useCallback(async () => {
    try {
      const res = await fetch("/api/portfolio");
      if (res.ok) {
        const data = await res.json();
        setPortfolio(data);
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchHistory = useCallback(async () => {
    try {
      const res = await fetch("/api/portfolio/history");
      if (res.ok) {
        const data = await res.json();
        setHistory(data);
      }
    } catch {
      // ignore
    }
  }, []);

  const executeTrade = useCallback(async (trade: TradeRequest): Promise<TradeResponse> => {
    try {
      const res = await fetch("/api/portfolio/trade", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(trade),
      });
      const data = await res.json();
      if (data.portfolio) {
        setPortfolio(data.portfolio);
      }
      await fetchPortfolio();
      return data;
    } catch {
      return { success: false, error: "Network error" };
    }
  }, [fetchPortfolio]);

  useEffect(() => {
    fetchPortfolio();
    fetchHistory();
    const interval = setInterval(() => {
      fetchPortfolio();
      fetchHistory();
    }, 30000);
    return () => clearInterval(interval);
  }, [fetchPortfolio, fetchHistory]);

  return { portfolio, history, loading, executeTrade, refreshPortfolio: fetchPortfolio };
}
