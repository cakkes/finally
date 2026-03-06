"use client";

import { useEffect, useRef } from "react";
import { createChart, IChartApi, ISeriesApi, LineSeries } from "lightweight-charts";
import { PriceData } from "../types";

interface MainChartProps {
  ticker: string;
  priceHistory: number[];
  currentPrice: PriceData | undefined;
}

export default function MainChart({ ticker, priceHistory, currentPrice }: MainChartProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { color: "#1a1a2e" },
        textColor: "#8b949e",
        fontFamily: "'Geist Mono', monospace",
      },
      grid: {
        vertLines: { color: "#30363d33" },
        horzLines: { color: "#30363d33" },
      },
      crosshair: {
        vertLine: { color: "#209dd7", width: 1, style: 2 },
        horzLine: { color: "#209dd7", width: 1, style: 2 },
      },
      timeScale: {
        borderColor: "#30363d",
        timeVisible: true,
      },
      rightPriceScale: {
        borderColor: "#30363d",
      },
      width: chartContainerRef.current.clientWidth,
      height: chartContainerRef.current.clientHeight,
    });

    const series = chart.addSeries(LineSeries, {
      color: "#209dd7",
      lineWidth: 2,
      crosshairMarkerRadius: 4,
      crosshairMarkerBorderColor: "#209dd7",
      crosshairMarkerBackgroundColor: "#1a1a2e",
    });

    chartRef.current = chart;
    seriesRef.current = series;

    const resizeObserver = new ResizeObserver((entries) => {
      const { width, height } = entries[0].contentRect;
      chart.applyOptions({ width, height });
    });
    resizeObserver.observe(chartContainerRef.current);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, [ticker]);

  useEffect(() => {
    if (!seriesRef.current || priceHistory.length === 0) return;

    const now = Math.floor(Date.now() / 1000);
    const data = priceHistory.map((price, i) => ({
      time: (now - (priceHistory.length - 1 - i)) as any,
      value: price,
    }));

    seriesRef.current.setData(data);
    chartRef.current?.timeScale().fitContent();
  }, [priceHistory]);

  const price = currentPrice?.price ?? 0;
  const prevPrice = currentPrice?.previous_price ?? price;
  const changePct = prevPrice ? ((price - prevPrice) / prevPrice) * 100 : 0;

  return (
    <div className="flex flex-col h-full bg-bg-panel">
      <div className="flex items-center gap-4 px-3 py-2 border-b border-border">
        <span className="text-accent-yellow font-bold">{ticker}</span>
        {price > 0 && (
          <>
            <span className="text-text-primary font-medium">${price.toFixed(2)}</span>
            <span
              className={`text-xs ${
                changePct > 0 ? "text-green" : changePct < 0 ? "text-red" : "text-text-secondary"
              }`}
            >
              {changePct > 0 ? "+" : ""}
              {changePct.toFixed(2)}%
            </span>
          </>
        )}
        <span className="text-text-secondary text-xs ml-auto">PRICE CHART</span>
      </div>
      <div ref={chartContainerRef} className="flex-1 min-h-0" />
    </div>
  );
}
