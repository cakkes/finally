"use client";

import { useState, useRef, useEffect } from "react";
import { ChatMessage } from "../types";

interface ChatPanelProps {
  messages: ChatMessage[];
  loading: boolean;
  onSendMessage: (message: string) => void;
}

export default function ChatPanel({ messages, loading, onSendMessage }: ChatPanelProps) {
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const handleSend = () => {
    if (input.trim() && !loading) {
      onSendMessage(input.trim());
      setInput("");
    }
  };

  return (
    <div className="flex flex-col h-full bg-bg-panel border-l border-border">
      <div className="px-3 py-2 border-b border-border text-xs text-text-secondary font-bold tracking-wider">
        AI ASSISTANT
      </div>
      <div className="flex-1 overflow-y-auto p-3 space-y-3 min-h-0">
        {messages.length === 0 && (
          <div className="text-text-secondary text-xs text-center mt-8">
            Ask FinAlly to analyze your portfolio, execute trades, or manage your watchlist.
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i}>
            <div
              data-testid={msg.role === "assistant" ? "chat-message-assistant" : undefined}
              className={`text-xs rounded p-2 ${
                msg.role === "user"
                  ? "bg-blue/10 border border-blue/20 text-text-primary ml-4"
                  : "bg-bg-main border border-border text-text-primary mr-4"
              }`}
            >
              <div className="text-[10px] text-text-secondary mb-1 font-bold">
                {msg.role === "user" ? "YOU" : "FINALLY"}
              </div>
              <div className="whitespace-pre-wrap">{msg.content}</div>
            </div>
            {msg.actions?.trades_executed && msg.actions.trades_executed.length > 0 && (
              <div className="mt-1 ml-2 space-y-0.5">
                {msg.actions.trades_executed.map((t, j) => (
                  <div key={j} className="text-[10px] text-green">
                    &#10003; {t.side === "buy" ? "Bought" : "Sold"} {t.quantity} {t.ticker} @ ${t.price.toFixed(2)}
                  </div>
                ))}
              </div>
            )}
            {msg.actions?.watchlist_changes && msg.actions.watchlist_changes.length > 0 && (
              <div className="mt-1 ml-2 space-y-0.5">
                {msg.actions.watchlist_changes.map((w, j) => (
                  <div key={j} className="text-[10px] text-blue">
                    &#10003; {w.action === "add" ? "Added" : "Removed"} {w.ticker} {w.action === "add" ? "to" : "from"} watchlist
                  </div>
                ))}
              </div>
            )}
            {msg.actions?.errors && msg.actions.errors.length > 0 && (
              <div className="mt-1 ml-2 space-y-0.5">
                {msg.actions.errors.map((e, j) => (
                  <div key={j} className="text-[10px] text-red">
                    &#10007; {e}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
        {loading && (
          <div data-testid="chat-loading" className="flex items-center gap-2 text-xs text-text-secondary">
            <div className="flex gap-1">
              <span className="w-1.5 h-1.5 bg-blue rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
              <span className="w-1.5 h-1.5 bg-blue rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
              <span className="w-1.5 h-1.5 bg-blue rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
            </div>
            Thinking...
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>
      <div className="flex border-t border-border p-2 gap-1">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSend()}
          data-testid="chat-input"
          placeholder="Ask FinAlly..."
          className="flex-1 bg-bg-main border border-border rounded px-2 py-1.5 text-xs text-text-primary placeholder:text-text-secondary/50 outline-none focus:border-purple"
          disabled={loading}
        />
        <button
          onClick={handleSend}
          data-testid="chat-send"
          disabled={loading || !input.trim()}
          className="bg-purple/20 text-purple border border-purple/30 rounded px-3 py-1.5 text-xs font-bold hover:bg-purple/30 transition-colors disabled:opacity-40"
        >
          SEND
        </button>
      </div>
    </div>
  );
}
