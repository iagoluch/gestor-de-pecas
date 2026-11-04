import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FilterProvider } from "../filters/FilterContext";
import { ManagementOverviewPage } from "../pages/ManagementOverviewPage";

afterEach(() => vi.restoreAllMocks());

const DEFAULT_CARDS = {
  producao_boa: true,
  oee: true,
  disponibilidade: true,
  performance: true,
  ftt: true,
  simulation: true,
  planned_vs_actual: true,
  exceptions: true,
  time_composition: true,
  top_losses: true,
  live_events: true,
  sectors_table: true,
  top_resources: true,
  audit_issues: true,
};

const DEFAULT_ORDER = Object.keys(DEFAULT_CARDS) as Array<keyof typeof DEFAULT_CARDS>;
const ALL_HIDDEN = Object.fromEntries(DEFAULT_ORDER.map((key) => [key, false])) as typeof DEFAULT_CARDS;

function metric() {
  return { value: null, availability: "sem_registros", unit: "%", reason: "Sem dados" };
}

function explanation(key: "oee" | "availability" | "performance" | "ftt", label: string) {
  return {
    key,
    label,
    metric: metric(),
    period: {},
    components: [],
    largest_impact: null,
    causes: [],
    resources: [],
    evidence: [],
    calculation_policy: "backend_only",
    simulation_only: false,
    limitation: null,
  };
}

function overviewBody() {
  return {
    periodo: {},
    production: { good: 10, scrap: 0, rework: 0, ops: 2, resources: 1, availability: "disponivel", reason: null, source: "test" },
    production_plan: metric(),
    kpis: { oee: metric(), availability: metric(), performance: metric(), ftt: metric() },
    sectors: [],
    time_composition: { items: [], total_seconds: 0, availability: "sem_registros" },
    audit: { open_issues: [] },
    data_quality: {},
    insights: {
      periodo: {},
      generated_at: "2026-11-03T10:30:00",
      exceptions: [],
      exception_count: 0,
      losses: [],
      critical_resources: [],
      kpi_explanations: {
        oee: explanation("oee", "OEE"),
        availability: explanation("availability", "Disponibilidade"),
        performance: explanation("performance", "Performance"),
        ftt: explanation("ftt", "FTT / Qualidade"),
      },
      limitations: [],
      policies: { calculation: "backend_only", priority: "fatos", resource_ranking: "tempo", thresholds: "fatos" },
      availability: "disponivel",
      simulation_only: false,
    },
  };
}

function stubFetch(cards: typeof DEFAULT_CARDS = DEFAULT_CARDS, order: Array<keyof typeof DEFAULT_CARDS> = DEFAULT_ORDER) {
  let state = { cards: { ...cards }, order: [...order] };
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const responseFor = (body: unknown) =>
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      });

    if (url.includes("/api/v1/auth/preferences") && init?.method === "POST") {
      state = JSON.parse(String(init.body)) as { cards: typeof DEFAULT_CARDS; order: Array<keyof typeof DEFAULT_CARDS> };
      return responseFor({ dashboard_home: state, updated_at: "2026-11-03T10:30:00" });
    }
    if (url.includes("/api/v1/auth/preferences")) {
      return responseFor({ dashboard_home: state, updated_at: null });
    }
    if (url.includes("/api/v1/management/overview/trend")) {
      return responseFor({ availability: "sem_registros", points: [] });
    }
    return responseFor(overviewBody());
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderPage() {
  return render(
    <MemoryRouter>
      <FilterProvider>
        <ManagementOverviewPage />
      </FilterProvider>
    </MemoryRouter>,
  );
}

function lastPreferencesPost(fetchMock: ReturnType<typeof vi.fn>) {
  const call = [...fetchMock.mock.calls].reverse().find(
    ([input, init]) => String(input).includes("/api/v1/auth/preferences") && (init as RequestInit | undefined)?.method === "POST",
  );
  if (!call) throw new Error("Nenhuma gravação de preferência foi enviada");
  return JSON.parse(String((call[1] as RequestInit).body as string)) as {
    dashboard_home: { cards: typeof DEFAULT_CARDS; order: Array<keyof typeof DEFAULT_CARDS> };
  };
}

describe("Tela inicial — personalização direta", () => {
  it("oculta um bloco direto na tela e persiste o estado", async () => {
    const fetchMock = stubFetch();
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Personalizar" }));
    const liveEvents = screen.getByLabelText("Agora na fábrica");
    fireEvent.click(within(liveEvents).getByRole("button", { name: "Ocultar" }));
    expect(within(liveEvents).getByText("Ocultado por você")).toBeInTheDocument();
    expect(lastPreferencesPost(fetchMock).dashboard_home.cards.live_events).toBe(false);
  });

  it("oculta todos os blocos e explica como reativar", async () => {
    stubFetch(ALL_HIDDEN);
    renderPage();
    expect(await screen.findByText("Nenhum bloco visível na tela inicial")).toBeInTheDocument();
    expect(screen.queryByText("Produção boa")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Personalizar" })).toBeInTheDocument();
  });

  it("o botão de mover para baixo persiste uma nova ordem", async () => {
    const fetchMock = stubFetch();
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Personalizar" }));
    fireEvent.click(screen.getByRole("button", { name: "Mover Produção boa para baixo" }));
    const body = lastPreferencesPost(fetchMock);
    expect(body.dashboard_home.order[0]).toBe("oee");
    expect(body.dashboard_home.order[1]).toBe("producao_boa");
  });

  it("arrastar um bloco com o mouse persiste a nova ordem", async () => {
    const fetchMock = stubFetch();
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Personalizar" }));
    const sourceSection = screen.getByLabelText("Composição do tempo");
    const sourceHandle = within(sourceSection).getByRole("button", { name: /Arrastar Composição do tempo/ });
    const targetSection = screen.getByLabelText("Setores — leitura rápida");
    const data: { value?: string } = {};
    const dataTransfer = {
      types: ["application/x-dashboard-card"],
      effectAllowed: "",
      dropEffect: "",
      setData(_type: string, value: string) { data.value = value; },
      getData(_type: string) { return data.value ?? ""; },
    };
    fireEvent.dragStart(sourceHandle, { dataTransfer });
    fireEvent.dragOver(targetSection, { dataTransfer });
    fireEvent.drop(targetSection, { dataTransfer });
    const body = lastPreferencesPost(fetchMock);
    expect(body.dashboard_home.order.indexOf("sectors_table")).toBeLessThan(body.dashboard_home.order.indexOf("time_composition"));
  });

  it("Restaurar padrão reenvia todos os blocos visíveis e a ordem original", async () => {
    const fetchMock = stubFetch(ALL_HIDDEN);
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Personalizar" }));
    fireEvent.click(screen.getByRole("button", { name: "Restaurar padrão" }));
    const body = lastPreferencesPost(fetchMock);
    expect(Object.values(body.dashboard_home.cards)).toEqual(Array(14).fill(true));
    expect(body.dashboard_home.order).toEqual(DEFAULT_ORDER);
  });
});
