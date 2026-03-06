"use client";

interface HeaderProps {
  totalValue: number;
  cashBalance: number;
  connected: boolean;
  reconnecting: boolean;
}

export default function Header({ totalValue, cashBalance, connected, reconnecting }: HeaderProps) {
  const statusColor = connected ? "bg-green" : reconnecting ? "bg-yellow-500" : "bg-red";
  const statusLabel = connected ? "LIVE" : reconnecting ? "RECONNECTING" : "DISCONNECTED";

  return (
    <header className="flex items-center justify-between px-4 py-2 border-b border-border bg-bg-panel">
      <div className="flex items-center gap-6">
        <h1 className="text-xl font-bold tracking-wider text-accent-yellow">
          Fin<span className="text-blue">Ally</span>
        </h1>
        <div className="flex items-center gap-4 text-sm">
          <div>
            <span className="text-text-secondary mr-2">PORTFOLIO</span>
            <span className="text-blue text-lg font-bold">
              ${totalValue.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>
          <div className="text-border">|</div>
          <div>
            <span className="text-text-secondary mr-2">CASH</span>
            <span data-testid="cash-balance" className="text-text-primary font-medium">
              ${cashBalance.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>
        </div>
      </div>
      <div className="flex items-center gap-2 text-xs text-text-secondary">
        <div data-testid="connection-status" data-status={connected ? "connected" : reconnecting ? "reconnecting" : "disconnected"} className={`w-2 h-2 rounded-full ${statusColor} ${connected ? "pulse" : ""}`} />
        {statusLabel}
      </div>
    </header>
  );
}
