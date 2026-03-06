export interface PriceData {
  ticker: string;
  price: number;
  previous_price: number;
  timestamp: string;
  direction: "up" | "down" | "unchanged";
}

export interface Position {
  ticker: string;
  quantity: number;
  avg_cost: number;
  current_price: number;
  unrealized_pnl: number;
  pnl_pct: number;
}

export interface Portfolio {
  cash_balance: number;
  positions: Position[];
  total_value: number;
  total_unrealized_pnl: number;
}

export interface TradeRequest {
  ticker: string;
  quantity: number;
  side: "buy" | "sell";
}

export interface TradeResponse {
  success: boolean;
  trade?: {
    ticker: string;
    side: string;
    quantity: number;
    price: number;
  };
  portfolio?: Portfolio;
  error?: string;
}

export interface WatchlistEntry {
  ticker: string;
  price: number;
  previous_price: number;
  change_pct: number;
  direction: string;
}

export interface PortfolioSnapshot {
  total_value: number;
  recorded_at: string;
}

export interface ChatMessage {
  id?: string;
  role: "user" | "assistant";
  content: string;
  actions?: {
    trades_executed?: Array<{
      ticker: string;
      side: string;
      quantity: number;
      price: number;
    }>;
    watchlist_changes?: Array<{
      ticker: string;
      action: string;
    }>;
    errors?: string[];
  };
}

export interface ChatResponse {
  message: string;
  trades_executed: Array<{
    ticker: string;
    side: string;
    quantity: number;
    price: number;
  }>;
  watchlist_changes: Array<{
    ticker: string;
    action: string;
  }>;
  errors: string[];
}
