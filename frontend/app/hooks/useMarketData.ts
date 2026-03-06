"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { PriceData } from "../types";

const MAX_HISTORY = 200;

interface MarketDataState {
  prices: Map<string, PriceData>;
  priceHistory: Map<string, number[]>;
  connected: boolean;
  reconnecting: boolean;
}

export function useMarketData() {
  const [prices, setPrices] = useState<Map<string, PriceData>>(new Map());
  const [priceHistory, setPriceHistory] = useState<Map<string, number[]>>(new Map());
  const [connected, setConnected] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [flashTickers, setFlashTickers] = useState<Map<string, "up" | "down">>(new Map());
  const eventSourceRef = useRef<EventSource | null>(null);
  const priceHistoryRef = useRef<Map<string, number[]>>(new Map());

  useEffect(() => {
    const connect = () => {
      const es = new EventSource("/api/stream/prices");
      eventSourceRef.current = es;

      es.onopen = () => {
        setConnected(true);
        setReconnecting(false);
      };

      es.onmessage = (event) => {
        try {
          const raw = JSON.parse(event.data);
          // Backend sends a ticker-keyed dict: {"AAPL": {...}, "AMZN": {...}}
          const updates: PriceData[] = Array.isArray(raw)
            ? raw
            : "ticker" in raw
            ? [raw]
            : Object.values(raw);

          setPrices((prev) => {
            const next = new Map(prev);
            const flashes = new Map<string, "up" | "down">();

            for (const update of updates) {
              const existing = next.get(update.ticker);
              if (existing && existing.price !== update.price) {
                flashes.set(
                  update.ticker,
                  update.price > existing.price ? "up" : "down"
                );
              }
              next.set(update.ticker, update);

              // Update history ref
              const history = priceHistoryRef.current.get(update.ticker) || [];
              history.push(update.price);
              if (history.length > MAX_HISTORY) history.shift();
              priceHistoryRef.current.set(update.ticker, history);
            }

            if (flashes.size > 0) {
              setFlashTickers(new Map(flashes));
              setTimeout(() => setFlashTickers(new Map()), 500);
            }

            setPriceHistory(new Map(priceHistoryRef.current));
            return next;
          });
        } catch {
          // ignore parse errors
        }
      };

      es.onerror = () => {
        setConnected(false);
        setReconnecting(true);
        es.close();
        setTimeout(connect, 3000);
      };
    };

    connect();

    return () => {
      eventSourceRef.current?.close();
    };
  }, []);

  return { prices, priceHistory, connected, reconnecting, flashTickers };
}
