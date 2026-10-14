type RealtimeListener = () => void;
export type RealtimeStatus = "connecting" | "connected" | "reconnecting";

// Quando o servidor recusa a conexão (429 por teto de conexões ao vivo, ou
// outro erro HTTP), o navegador fecha o EventSource (readyState CLOSED) e NÃO
// tenta de novo sozinho. Aí a reconexão é nossa, com espera crescente para não
// martelar um servidor que já está cheio. Queda no meio do stream continua com
// a reconexão automática do próprio navegador.
const EVENT_SOURCE_CLOSED = 2; // EventSource.CLOSED
export const STREAM_RETRY_BASE_MS = 5_000;
export const STREAM_RETRY_MAX_MS = 30_000;

export function nextStreamRetryDelay(current: number) {
  return Math.min(current * 2, STREAM_RETRY_MAX_MS);
}

export function eventSourceGaveUp(source: EventSource) {
  return source.readyState === EVENT_SOURCE_CLOSED;
}

const listeners = new Map<RealtimeListener, { ignoreLiveTick: boolean }>();
const statusListeners = new Set<(status: RealtimeStatus) => void>();
let source: EventSource | null = null;
let status: RealtimeStatus = "connecting";
let retryTimer: ReturnType<typeof setTimeout> | null = null;
let retryDelay = STREAM_RETRY_BASE_MS;

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

function scheduleRetry() {
  const wait = retryDelay;
  retryDelay = nextStreamRetryDelay(retryDelay);
  retryTimer = setTimeout(() => {
    retryTimer = null;
    if (listeners.size || statusListeners.size) connect();
  }, wait);
}

function connect() {
  if (source || retryTimer || typeof EventSource === "undefined") return;
  setStatus("connecting");
  const current = new EventSource("/api/v1/system/events", { withCredentials: true });
  source = current;
  current.onopen = () => {
    retryDelay = STREAM_RETRY_BASE_MS;
    setStatus("connected");
  };
  current.onerror = () => {
    setStatus("reconnecting");
    if (source !== current || !eventSourceGaveUp(current)) return;
    // Libera a conexão morta: sem isso, ``connect`` acharia que ainda há uma.
    current.close();
    source = null;
    scheduleRetry();
  };
  current.addEventListener("connected", () => setStatus("connected"));
  current.addEventListener("refresh", (event) => {
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
  if (listeners.size || statusListeners.size) return;
  if (retryTimer) {
    clearTimeout(retryTimer);
    retryTimer = null;
  }
  retryDelay = STREAM_RETRY_BASE_MS;
  if (!source && status === "connecting") return;
  source?.close();
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
