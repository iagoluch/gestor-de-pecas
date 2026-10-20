import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ManagementInsightDrawer } from "../components/ManagementInsightDrawer";
import { ValueExplanationBody } from "../components/ValueExplanationPanel";
import type { ValueExplanation } from "../types/valueExplanation";
import { FilterProvider } from "../filters/FilterContext";
import { AnalyticsOeePage } from "../pages/analytics/AnalyticsPages";
import { HomeSectorsPage } from "../pages/home/HomePages";
import type { KpiExplanation } from "../types/api";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function respond(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function metricValue(value: number | null, availability = "disponivel", reason: string | null = null) {
  return { value, unit: "%", availability, reason };
}

function valueExplanation(metric: string) {
  return {
    kind: "value",
    metric,
    label: `Explicação ${metric}`,
    unit: "pct",
    value: 50,
    reason: "Teste.",
    rule: "Regra de teste.",
    children: [],
    excluded: [],
    reconciliation: { ok: true, sum: 50, diff: 0 },
    calculated_at: "2026-10-19T14:00:00",
    truncated: false,
    notes: [],
  };
}

const OEE = {
  oee: { value: 40, availability: "disponivel", reason: "" },
  components: {
    oee: metricValue(40),
    availability: metricValue(80),
    performance: metricValue(70),
    ftt: metricValue(null, "dados_insuficientes", "Sem peças apontadas."),
  },
  extended_metrics: {
    utilization: metricValue(60),
    productivity: metricValue(55),
    ae: metricValue(45),
  },
  availability: "disponivel",
  reason: "",
};

function mountFetch() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.includes("/management/explicacao")) {
      return respond(valueExplanation(new URL(path, "http://x").searchParams.get("metric") ?? ""));
    }
    if (path.includes("/analytics/oee")) return respond(OEE);
    return respond({ items: [] });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function explanationCalls(fetchMock: ReturnType<typeof mountFetch>) {
  return fetchMock.mock.calls.map((call) => String((call as unknown[])[0])).filter((url) => url.includes("/management/explicacao"));
}

describe("OEE: percentuais clicáveis", () => {
  it("cada indicador com número abre a explicação kpi.* e o FTT reaproveita qtd.ftt", async () => {
    const fetchMock = mountFetch();
    render(<MemoryRouter><FilterProvider><AnalyticsOeePage /></FilterProvider></MemoryRouter>);

    const expected: Array<[RegExp, string]> = [
      [/Ver de onde vem este número: OEE 40/, "kpi.oee"],
      [/Ver de onde vem este número: Disponibilidade 80/, "kpi.disponibilidade"],
      [/Ver de onde vem este número: Performance 70/, "kpi.performance"],
      [/Ver de onde vem este número: AE 45/, "kpi.ae"],
      [/Ver de onde vem este número: Produtividade 55/, "kpi.produtividade"],
      [/Ver de onde vem este número: Utilização 60/, "kpi.utilizacao"],
    ];
    for (const [name, id] of expected) {
      fireEvent.click(await screen.findByRole("button", { name }));
      await screen.findByRole("dialog");
      await waitFor(() => expect(explanationCalls(fetchMock).some((url) => url.includes(`metric=${id}`))).toBe(true));
      fireEvent.click(screen.getByRole("button", { name: "Fechar explicação" }));
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    }
  });

  it("indicador sem número (dados insuficientes) fica texto simples", async () => {
    mountFetch();
    render(<MemoryRouter><FilterProvider><AnalyticsOeePage /></FilterProvider></MemoryRouter>);
    await screen.findByRole("button", { name: /Ver de onde vem este número: OEE/ });
    expect(screen.queryByRole("button", { name: /Ver de onde vem este número: FTT/ })).not.toBeInTheDocument();
  });
});

describe("Drawer de KPI: conta com valores reais", () => {
  function kpi(key: KpiExplanation["key"], value: number | null): KpiExplanation {
    return {
      key,
      label: key.toUpperCase(),
      metric: metricValue(value) as KpiExplanation["metric"],
      period: {},
      components: [],
      causes: [],
      resources: [],
      evidence: [],
      calculation_policy: "backend_only",
      simulation_only: false,
    };
  }

  it("o resultado vira botão e chama onExplain com o id certo de cada KPI", () => {
    const onExplain = vi.fn();
    const mapping: Array<[KpiExplanation["key"], string]> = [
      ["oee", "kpi.oee"],
      ["availability", "kpi.disponibilidade"],
      ["performance", "kpi.performance"],
      ["ftt", "qtd.ftt"],
    ];
    for (const [key, id] of mapping) {
      const { unmount } = render(
        <MemoryRouter><ManagementInsightDrawer explanation={kpi(key, 42)} onClose={() => undefined} onExplain={onExplain} /></MemoryRouter>,
      );
      fireEvent.click(screen.getByRole("button", { name: /Ver de onde vem este número/ }));
      expect(onExplain).toHaveBeenLastCalledWith(id);
      unmount();
    }
  });

  it("sem número ou sem onExplain o resultado continua texto simples", () => {
    const { unmount } = render(
      <MemoryRouter><ManagementInsightDrawer explanation={kpi("oee", null)} onClose={() => undefined} onExplain={() => undefined} /></MemoryRouter>,
    );
    expect(screen.queryByRole("button", { name: /Ver de onde vem este número/ })).not.toBeInTheDocument();
    unmount();
    render(<MemoryRouter><ManagementInsightDrawer explanation={kpi("oee", 42)} onClose={() => undefined} /></MemoryRouter>);
    expect(screen.queryByRole("button", { name: /Ver de onde vem este número/ })).not.toBeInTheDocument();
  });
});

describe("Painel: entradas do kpi.* em horas e %", () => {
  const input = (label: string, value: number, unidade: string) => ({
    kind: "input" as const, label, value, children: [], truncated: false,
    detail: { unidade, metric: "tempo.producao", tempo: "8h 0m" },
  });
  const explanation: ValueExplanation = {
    kind: "value", metric: "kpi.disponibilidade", label: "Disponibilidade", unit: "pct", value: 80,
    reason: "Teste.", rule: "Regra.", calculated_at: "2026-10-19T14:00:00", truncated: false, notes: [],
    children: [input("Numerador: tempo trabalhado", 28800, "segundos"), input("Componente: Performance", 70, "%")],
    excluded: [{ label: "Fila", value: 3600, unidade: "segundos", reason: "Espera." }],
    reconciliation: { ok: true, sum: 80, diff: 0 },
  };

  it("segundos viram horas, % ganha o sinal e as chaves técnicas não aparecem", () => {
    render(<ValueExplanationBody explanation={explanation} />);
    expect(screen.getByText("8h")).toBeInTheDocument();
    expect(screen.getByText("70%")).toBeInTheDocument();
    expect(screen.getByText(/Fila 1h:/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Numerador/ }));
    expect(screen.queryByText("Unidade")).not.toBeInTheDocument();
    expect(screen.queryByText("Metric")).not.toBeInTheDocument();
    expect(screen.getByText("Tempo")).toBeInTheDocument();
  });
});

describe("Tela inicial / Setores: células clicáveis por setor", () => {
  const SECTOR = {
    setor: "corte", producao_boa: 120, refugo: 0, retrabalho: 3, ops: 4,
    tempo_producao_segundos: 7200, tempo_setup_segundos: 0, tempo_parada_segundos: 1800,
  };

  it("boa, retrabalho e tempo de produção abrem a explicação com o setor; zero e Paradas ficam texto", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes("/management/explicacao")) return respond(valueExplanation(new URL(path, "http://x").searchParams.get("metric") ?? ""));
      if (path.includes("/management/sectors")) return respond({ items: [SECTOR], highlights: [], count: 1, data_quality: {} });
      return respond({ items: [] });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter><FilterProvider><HomeSectorsPage /></FilterProvider></MemoryRouter>);

    const expected: Array<[RegExp, string]> = [
      [/Ver de onde vem este número: Produção boa em .* 120/, "qtd.boa"],
      [/Ver de onde vem este número: Retrabalho em .* 3/, "qtd.retrabalho"],
      [/Ver de onde vem este número: Tempo de produção em /, "tempo.producao"],
    ];
    for (const [name, id] of expected) {
      fireEvent.click(await screen.findByRole("button", { name }));
      await screen.findByRole("dialog");
      await waitFor(() => expect(explanationCalls(fetchMock as ReturnType<typeof mountFetch>).some((url) => url.includes(`metric=${id}`) && url.includes("setor=corte"))).toBe(true));
      fireEvent.click(screen.getByRole("button", { name: "Fechar explicação" }));
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    }
    expect(screen.queryByRole("button", { name: /Refugo em / })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Tempo de setup em / })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Paradas/ })).not.toBeInTheDocument();
  });
});
