"use client";

import { useState, useCallback } from "react";
import Header from "./components/Header";
import WatchlistPanel from "./components/WatchlistPanel";
import MainChart from "./components/MainChart";
import PortfolioHeatmap from "./components/PortfolioHeatmap";
import PositionsTable from "./components/PositionsTable";
import PnLChart from "./components/PnLChart";
import TradeBar from "./components/TradeBar";
import ChatPanel from "./components/ChatPanel";
import { useMarketData } from "./hooks/useMarketData";
import { usePortfolio } from "./hooks/usePortfolio";
import { useWatchlist } from "./hooks/useWatchlist";
import { useChat } from "./hooks/useChat";
import { TradeResponse } from "./types";

export default function Home() {
  const { prices, priceHistory, connected, reconnecting, flashTickers } = useMarketData();
  const { portfolio, history, executeTrade, refreshPortfolio } = usePortfolio();
  const { tickers, addTicker, removeTicker } = useWatchlist();
  const { messages, loading, sendMessage } = useChat();
  const [selectedTicker, setSelectedTicker] = useState("AAPL");

  const handleTrade = useCallback(
    async (ticker: string, quantity: number, side: "buy" | "sell"): Promise<TradeResponse> => {
      const result = await executeTrade({ ticker, quantity, side });
      return result;
    },
    [executeTrade]
  );

  const handleChatMessage = useCallback(
    async (message: string) => {
      await sendMessage(message);
      refreshPortfolio();
    },
    [sendMessage, refreshPortfolio]
  );

  const totalValue = portfolio?.total_value ?? 10000;
  const cashBalance = portfolio?.cash_balance ?? 10000;
  const positions = portfolio?.positions ?? [];

  return (
    <div className="flex flex-col h-screen">
      <Header
        totalValue={totalValue}
        cashBalance={cashBalance}
        connected={connected}
        reconnecting={reconnecting}
      />

      <div className="flex flex-1 min-h-0">
        {/* Left: Watchlist */}
        <div className="w-64 flex-shrink-0">
          <WatchlistPanel
            tickers={tickers}
            prices={prices}
            priceHistory={priceHistory}
            flashTickers={flashTickers}
            selectedTicker={selectedTicker}
            onSelectTicker={setSelectedTicker}
            onAddTicker={addTicker}
            onRemoveTicker={removeTicker}
          />
        </div>

        {/* Center: Chart + Heatmap */}
        <div className="flex-1 flex flex-col min-w-0">
          <div className="flex-1 min-h-0">
            <MainChart
              ticker={selectedTicker}
              priceHistory={priceHistory.get(selectedTicker) || []}
              currentPrice={prices.get(selectedTicker)}
            />
          </div>
          <div className="h-40 border-t border-border">
            <PortfolioHeatmap positions={positions} totalValue={totalValue} />
          </div>
        </div>

        {/* Right: Chat */}
        <div className="w-72 flex-shrink-0">
          <ChatPanel
            messages={messages}
            loading={loading}
            onSendMessage={handleChatMessage}
          />
        </div>
      </div>

      {/* Bottom: Positions + P&L + Trade */}
      <div className="h-48 flex border-t border-border">
        <div className="flex-1 min-w-0">
          <PositionsTable positions={positions} />
        </div>
        <div className="w-80 border-l border-border">
          <PnLChart data={history} />
        </div>
      </div>

      <TradeBar onTrade={handleTrade} selectedTicker={selectedTicker} />
    </div>
  );
}
