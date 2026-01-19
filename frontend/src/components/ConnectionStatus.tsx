import { Wifi, WifiOff } from 'lucide-react';

interface ConnectionStatusProps {
  isConnected: boolean;
  tickerCount: number;
}

export function ConnectionStatus({ isConnected, tickerCount }: ConnectionStatusProps) {
  return (
    <div className="flex items-center gap-2 md:gap-4">
      <div className="flex items-center gap-1.5 md:gap-2 text-xs md:text-sm">
        {isConnected ? (
          <>
            <Wifi className="w-3.5 h-3.5 md:w-4 md:h-4 text-accent-green" />
            <span className="text-accent-green hidden sm:inline">Connected</span>
          </>
        ) : (
          <>
            <WifiOff className="w-3.5 h-3.5 md:w-4 md:h-4 text-accent-red" />
            <span className="text-accent-red hidden sm:inline">Disconnected</span>
          </>
        )}
      </div>
      {tickerCount > 0 && (
        <div className="text-xs text-text-muted hidden sm:block">
          {tickerCount} ticker{tickerCount !== 1 ? 's' : ''}
        </div>
      )}
    </div>
  );
}
