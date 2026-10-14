import { useEffect, useState } from "react";
import { STREAM_RETRY_BASE_MS, eventSourceGaveUp, nextStreamRetryDelay } from "../api/realtime";
import type { OperationsOverview } from "../types/management";

export function useOperationsStream(query: string) {
  const [snapshot, setSnapshot] = useState<OperationsOverview | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let source: EventSource | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let retryDelay = STREAM_RETRY_BASE_MS;
    let stopped = false;

    const open = () => {
      const current = new EventSource(`/api/v1/operations/stream?${query}`, { withCredentials: true });
      source = current;
      current.addEventListener("snapshot", (event) => {
        try {
          setSnapshot(JSON.parse((event as MessageEvent).data) as OperationsOverview);
          setConnected(true);
          retryDelay = STREAM_RETRY_BASE_MS;
        } catch {
          setConnected(false);
        }
      });
      current.onerror = () => {
        setConnected(false);
        // 429 (telas demais ao vivo) ou outro erro HTTP: o navegador desiste
        // sem tentar de novo; tentamos nós, com espera crescente.
        if (stopped || !eventSourceGaveUp(current)) return;
        current.close();
        retryTimer = setTimeout(open, retryDelay);
        retryDelay = nextStreamRetryDelay(retryDelay);
      };
    };

    open();
    return () => {
      stopped = true;
      clearTimeout(retryTimer);
      source?.close();
    };
  }, [query]);

  return { snapshot, connected };
}
