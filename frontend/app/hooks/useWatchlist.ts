"use client";

import { useState, useEffect, useCallback } from "react";

export function useWatchlist() {
  const [tickers, setTickers] = useState<string[]>([]);

  const fetchWatchlist = useCallback(async () => {
    try {
      const res = await fetch("/api/watchlist");
      if (res.ok) {
        const data = await res.json();
        setTickers(data.map((e: { ticker: string }) => e.ticker));
      }
    } catch {
      // ignore
    }
  }, []);

  const addTicker = useCallback(async (ticker: string): Promise<boolean> => {
    try {
      const res = await fetch("/api/watchlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker: ticker.toUpperCase() }),
      });
      if (res.ok) {
        await fetchWatchlist();
        return true;
      }
      return false;
    } catch {
      return false;
    }
  }, [fetchWatchlist]);

  const removeTicker = useCallback(async (ticker: string): Promise<boolean> => {
    try {
      const res = await fetch(`/api/watchlist/${ticker}`, { method: "DELETE" });
      if (res.ok || res.status === 204) {
        await fetchWatchlist();
        return true;
      }
      return false;
    } catch {
      return false;
    }
  }, [fetchWatchlist]);

  useEffect(() => {
    fetchWatchlist();
  }, [fetchWatchlist]);

  return { tickers, addTicker, removeTicker, refreshWatchlist: fetchWatchlist };
}
