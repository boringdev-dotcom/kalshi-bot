import { useEffect, useState } from "react";
import { wsUrl } from "./api";

export function useLiveTick(onMessage?: () => void): boolean {
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let timer: number | undefined;

    const connect = () => {
      ws = new WebSocket(wsUrl());
      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        if (!closed) timer = window.setTimeout(connect, 2000);
      };
      ws.onmessage = () => onMessage?.();
    };
    connect();
    return () => {
      closed = true;
      if (timer) window.clearTimeout(timer);
      ws?.close();
    };
  }, [onMessage]);

  return connected;
}
