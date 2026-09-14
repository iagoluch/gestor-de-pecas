import { useEffect, useState } from "react";
import type { OperationsOverview } from "../types/management";

export function useOperationsStream(query: string) {
  const [snapshot, setSnapshot] = useState<OperationsOverview | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const source = new EventSource(`/api/v1/operations/stream?${query}`, { withCredentials: true });
    source.addEventListener("snapshot", (event) => {
      try {
        setSnapshot(JSON.parse((event as MessageEvent).data) as OperationsOverview);
        setConnected(true);
      } catch {
        setConnected(false);
      }
    });
    source.onerror = () => setConnected(false);
    return () => source.close();
  }, [query]);

  return { snapshot, connected };
}

