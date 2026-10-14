import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useApiQuery } from "../hooks/useApiQuery";


class MockEventSource {
  static instance: MockEventSource | null = null;
  private listeners = new Map<string, EventListener>();

  constructor(_url: string | URL, _options?: EventSourceInit) {
    MockEventSource.instance = this;
  }

  addEventListener(type: string, listener: EventListener) {
    this.listeners.set(type, listener);
  }

  emit(type: string, payload?: Record<string, unknown>) {
    const event = payload
      ? new MessageEvent(type, { data: JSON.stringify(payload) })
      : new Event(type);
    this.listeners.get(type)?.(event);
  }

  close() {}
}


afterEach(() => {
  MockEventSource.instance = null;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});


describe("atualização Web em tempo real", () => {
  it("mantém os dados visíveis enquanto o refresh SSE consulta em segundo plano", async () => {
    let resolveRefresh: ((value: Response) => void) | null = null;
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ value: "primeiro" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }))
      .mockImplementationOnce(() => new Promise<Response>((resolve) => { resolveRefresh = resolve; }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("EventSource", MockEventSource);

    function Probe() {
      const query = useApiQuery<{ value: string }>("/api/v1/probe");
      return query.loading ? <span>Carregando</span> : <span>{query.data?.value}</span>;
    }

    render(<Probe />);
    expect(await screen.findByText("primeiro")).toBeInTheDocument();
    act(() => MockEventSource.instance?.emit("refresh", { topic: "live_tick" }));
    expect(screen.getByText("primeiro")).toBeInTheDocument();
    expect(screen.queryByText("Carregando")).not.toBeInTheDocument();

    await act(async () => {
      resolveRefresh?.(new Response(JSON.stringify({ value: "segundo" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }));
    });
    expect(await screen.findByText("segundo")).toBeInTheDocument();
  });
});


class RefusedEventSource {
  static instances: RefusedEventSource[] = [];
  readyState = 0;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn(() => { this.readyState = 2; });

  constructor(_url: string | URL, _options?: EventSourceInit) {
    RefusedEventSource.instances.push(this);
  }

  addEventListener() {}

  // Resposta 429/erro HTTP: o navegador fecha (CLOSED) e não tenta de novo.
  refuse() {
    this.readyState = 2;
    this.onerror?.();
  }
}


describe("canal ao vivo recusado pelo servidor (429)", () => {
  it("libera a conexão morta e tenta de novo com espera crescente", async () => {
    vi.useFakeTimers();
    RefusedEventSource.instances = [];
    vi.stubGlobal("EventSource", RefusedEventSource);
    const { subscribeRealtimeStatus } = await import("../api/realtime");
    const statuses: string[] = [];
    const unsubscribe = subscribeRealtimeStatus((next) => statuses.push(next));
    try {
      expect(RefusedEventSource.instances).toHaveLength(1);

      RefusedEventSource.instances[0].refuse();
      expect(RefusedEventSource.instances[0].close).toHaveBeenCalled();
      expect(statuses.at(-1)).toBe("reconnecting");
      vi.advanceTimersByTime(4_999);
      expect(RefusedEventSource.instances).toHaveLength(1);
      vi.advanceTimersByTime(1);
      expect(RefusedEventSource.instances).toHaveLength(2);

      // Segunda recusa: espera dobra (10 s), sem martelar o servidor.
      RefusedEventSource.instances[1].refuse();
      vi.advanceTimersByTime(9_999);
      expect(RefusedEventSource.instances).toHaveLength(2);
      vi.advanceTimersByTime(1);
      expect(RefusedEventSource.instances).toHaveLength(3);

      // Conectou: volta ao normal.
      RefusedEventSource.instances[2].onopen?.();
      expect(statuses.at(-1)).toBe("connected");
    } finally {
      unsubscribe();
      vi.useRealTimers();
    }
  });

  it("queda no meio do stream fica com a reconexão do próprio navegador", async () => {
    vi.useFakeTimers();
    RefusedEventSource.instances = [];
    vi.stubGlobal("EventSource", RefusedEventSource);
    const { subscribeRealtimeStatus } = await import("../api/realtime");
    const unsubscribe = subscribeRealtimeStatus(() => undefined);
    try {
      RefusedEventSource.instances[0].onopen?.();
      RefusedEventSource.instances[0].readyState = 0; // CONNECTING: navegador reconecta
      RefusedEventSource.instances[0].onerror?.();
      vi.advanceTimersByTime(60_000);
      expect(RefusedEventSource.instances).toHaveLength(1);
      expect(RefusedEventSource.instances[0].close).not.toHaveBeenCalled();
    } finally {
      unsubscribe();
      vi.useRealTimers();
    }
  });
});
