import { Wifi, WifiOff } from 'lucide-react';

interface ConnectionStatusProps {
  isConnected: boolean;
  tickerCount: number;
}

export function ConnectionStatus({ isConnected, tickerCount }: ConnectionStatusProps) {
  return (
    <div className="flex items-center gap-4">
      <div className="flex items-center gap-2 text-sm">
        {isConnected ? (
          <>
            <Wifi className="w-4 h-4 text-accent-green" />
            <span className="text-accent-green">Connected</span>
          </>
        ) : (
          <>
            <WifiOff className="w-4 h-4 text-accent-red" />
            <span className="text-accent-red">Disconnected</span>
          </>
        )}
      </div>
      {tickerCount > 0 && (
        <div className="text-xs text-text-muted">
          {tickerCount} ticker{tickerCount !== 1 ? 's' : ''} subscribed
        </div>
      )}
    </div>
  );
}
