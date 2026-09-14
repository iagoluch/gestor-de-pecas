type RealtimeListener = () => void;
export type RealtimeStatus = "connecting" | "connected" | "reconnecting";

const listeners = new Map<RealtimeListener, { ignoreLiveTick: boolean }>();
const statusListeners = new Set<(status: RealtimeStatus) => void>();
let source: EventSource | null = null;
let status: RealtimeStatus = "connecting";

function notify(topic?: string) {
  listeners.forEach((options, listener) => {
    if (options.ignoreLiveTick && topic === "live_tick") return;
    listener();
  });
}

function setStatus(next: RealtimeStatus) {
  if (status === next) return;
  status = next;
  statusListeners.forEach((listener) => listener(status));
}

function connect() {
  if (source || typeof EventSource === "undefined") return;
  setStatus("connecting");
  source = new EventSource("/api/v1/system/events", { withCredentials: true });
  source.onopen = () => setStatus("connected");
  source.onerror = () => setStatus("reconnecting");
  source.addEventListener("connected", () => setStatus("connected"));
  source.addEventListener("refresh", (event) => {
    setStatus("connected");
    let topic: string | undefined;
    try {
      const payload = JSON.parse((event as MessageEvent).data) as { topic?: string };
      topic = payload.topic;
    } catch {
      // Um evento legado sem payload continua sendo uma invalidação válida.
    }
    notify(topic);
  });
}

function disconnect() {
  if (listeners.size || statusListeners.size || !source) return;
  source.close();
  source = null;
  status = "connecting";
}

export function subscribeRealtime(
  listener: RealtimeListener,
  options: { ignoreLiveTick?: boolean } = {},
) {
  listeners.set(listener, { ignoreLiveTick: Boolean(options.ignoreLiveTick) });
  connect();
  return () => {
    listeners.delete(listener);
    disconnect();
  };
}

export function subscribeRealtimeStatus(listener: (next: RealtimeStatus) => void) {
  statusListeners.add(listener);
  listener(status);
  connect();
  return () => {
    statusListeners.delete(listener);
    disconnect();
  };
}
