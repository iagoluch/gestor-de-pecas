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
