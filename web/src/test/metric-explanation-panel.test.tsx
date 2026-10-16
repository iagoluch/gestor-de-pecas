import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MetricExplanationPanel } from "../components/MetricExplanationPanel";
import { defaultFilters, FilterProvider } from "../filters/FilterContext";
import { ManagementOverviewPage } from "../pages/ManagementOverviewPage";
import { OperationsTimePage } from "../pages/operations/OperationsPages";
import type { ExplanationTree } from "../types/explanation";

afterEach(() => vi.restoreAllMocks());

const FILTERS = { ...defaultFilters(new Date(2026, 9, 16, 10, 0)) };

function tree(overrides: Partial<ExplanationTree> = {}): ExplanationTree {
  return {
    metric: "tempo.sem_demanda",
    label: "Recurso sem demanda",
    total_seconds: 36000,
    average_seconds: 9000,
    resource_count: 4,
    day_count: 1,
    parent_total_seconds: 43200,
    siblings: [
      { metric: "tempo.sem_demanda", label: "Recurso sem demanda", seconds: 36000 },
      { metric: "tempo.parada_nao_planejada", label: "Parada não planejada", seconds: 7200 },
    ],
    reason: "Nenhuma OP foi apontada nestes recursos, então ficaram esperando serviço.",
    rule: "Recurso ligado ao turno sem OP programada.",
    children: [
      {
        kind: "sector", label: "Corte", seconds: 21600, truncated: false, detail: null,
        children: [
          {
            kind: "resource", label: "LASER1", seconds: 14400, truncated: false, detail: null,
            children: [
              {
                kind: "stretch", label: "07:12 → 12:00", seconds: 10800, truncated: false, children: [],
                detail: { start: "2026-10-16T07:12:00", end: "2026-10-16T12:00:00", who: "Sistema", origin: "sistema", record_id: "estado:551", motivo: "início de turno" },
              },
              {
                kind: "stretch", label: "12:48 → 13:48", seconds: 3600, truncated: false, children: [],
                detail: { start: "2026-10-16T12:48:00", end: "2026-10-16T13:48:00", who: null, origin: "sistema", record_id: "estado:552" },
              },
            ],
          },
          {
            kind: "resource", label: "LASER2", seconds: 7200, truncated: false, detail: null,
            children: [{
              kind: "stretch", label: "08:00 → 10:00", seconds: 7200, truncated: false, children: [],
              detail: { start: "2026-10-16T08:00:00", end: "2026-10-16T10:00:00", who: null, origin: "sistema", record_id: "estado:560" },
            }],
          },
        ],
      },
      {
        kind: "sector", label: "Solda", seconds: 14400, truncated: false, detail: null,
        children: [{ kind: "resource", label: "SOLDA1", seconds: 14400, truncated: false, detail: null, children: [] }],
      },
    ],
    excluded: [{ label: "Parada planejada: almoço", seconds: 2880, reason: "Conta como parada planejada, não nesta linha." }],
    reconciliation: { ok: true, sum_seconds: 36000, diff_seconds: 0 },
    calculated_at: "2026-10-16T14:35:00",
    truncated: false,
    notes: [],
    ...overrides,
  };
}

function respond(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function renderPanel(fetchMock: ReturnType<typeof vi.fn>, onClose = vi.fn()) {
  vi.stubGlobal("fetch", fetchMock);
  function Where() {
    return <span data-testid="where">{useLocation().pathname}</span>;
  }
  const view = render(
    <MemoryRouter initialEntries={["/inicio"]}>
      <Where />
      <MetricExplanationPanel metric="tempo.sem_demanda" filters={FILTERS} onClose={onClose} />
    </MemoryRouter>,
  );
  return { ...view, onClose };
}

describe("MetricExplanationPanel", () => {
  it("mostra o número grande, a média por recurso e uma barra por setor", async () => {
    const fetchMock = vi.fn(async () => respond(tree()));
    renderPanel(fetchMock);

    const dialog = await screen.findByRole("dialog", { name: /Recurso sem demanda/ });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(await within(dialog).findByTestId("explanation-total")).toHaveTextContent("10h");
    expect(dialog).toHaveTextContent("média 2h 30m por recurso (4 recursos)");
    expect(dialog).toHaveTextContent("Nenhuma OP foi apontada nestes recursos");
    expect(within(dialog).getByRole("button", { name: /Corte/ })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: /Solda/ })).toBeInTheDocument();
    expect(dialog).not.toHaveTextContent("NaN");
    const url = String((fetchMock.mock.calls[0] as unknown[])[0]);
    expect(url).toContain("/api/v1/management/explicacao?metric=tempo.sem_demanda");
    expect(url).toContain("inicio=2026-10-16T00%3A00%3A00");
  });

  it("clica no setor para ver recursos e no recurso para ver trechos, sem trocar de tela", async () => {
    renderPanel(vi.fn(async () => respond(tree())));
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByTestId("explanation-total");

    expect(within(dialog).queryByRole("button", { name: /LASER1/ })).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: /Corte/ }));
    const laser1 = within(dialog).getByRole("button", { name: /LASER1/ });
    expect(within(dialog).getByRole("button", { name: /LASER2/ })).toBeInTheDocument();
    expect(within(dialog).queryByText("07:12 → 12:00")).not.toBeInTheDocument();
    fireEvent.click(laser1);
    expect(within(dialog).getByRole("button", { name: /07:12 → 12:00/ })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: /12:48 → 13:48/ })).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("/inicio");
  });

  it("fecha a conta com 'os setores somam' quando bate e avisa em vermelho quando não bate", async () => {
    const { unmount } = renderPanel(vi.fn(async () => respond(tree())));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText(/os setores somam 10h, igual ao número clicado/)).toBeInTheDocument();
    expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument();
    unmount();

    renderPanel(vi.fn(async () => respond(tree({ reconciliation: { ok: false, sum_seconds: 34200, diff_seconds: -1800 } }))));
    const broken = await screen.findByRole("dialog");
    const alert = await within(broken).findByRole("alert");
    expect(alert).toHaveTextContent("diferença de 30m");
    expect(within(broken).queryByText(/igual ao número clicado/)).not.toBeInTheDocument();
  });

  it("mostra o registro técnico só depois de clicar no trecho", async () => {
    renderPanel(vi.fn(async () => respond(tree())));
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByTestId("explanation-total");
    fireEvent.click(within(dialog).getByRole("button", { name: /Corte/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: /LASER1/ }));

    expect(dialog).not.toHaveTextContent("estado:551");
    fireEvent.click(within(dialog).getByRole("button", { name: /07:12 → 12:00/ }));
    expect(dialog).toHaveTextContent("estado:551");
    expect(dialog).toHaveTextContent("sistema");
    expect(dialog).not.toHaveTextContent("estado:552");
  });

  it("informa a hora do cálculo e mostra o que ficou de fora", async () => {
    renderPanel(vi.fn(async () => respond(tree())));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("calculado às 14:35")).toBeInTheDocument();
    expect(dialog).toHaveTextContent("Parada planejada: almoço");
  });

  it("explica o erro em português simples (403 e 500)", async () => {
    const { unmount } = renderPanel(vi.fn(async () => respond({ code: "management_access_denied", message: "negado" }, 403)));
    expect(await screen.findByText("Você não tem acesso a esta explicação.")).toBeInTheDocument();
    unmount();

    renderPanel(vi.fn(async () => respond({ code: "internal_error", message: "boom técnico" }, 500)));
    expect(await screen.findByText("Não foi possível carregar a explicação agora.")).toBeInTheDocument();
    expect(screen.queryByText(/boom técnico/)).not.toBeInTheDocument();
  });

  it("avisa quando a lista foi cortada por tamanho", async () => {
    renderPanel(vi.fn(async () => respond(tree({ truncated: true }))));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText(/lista foi cortada por tamanho/i)).toBeInTheDocument();
  });

  it("sem recursos com turno mostra a nota em vez de média, nunca NaN", async () => {
    renderPanel(vi.fn(async () => respond(tree({
      total_seconds: 0, average_seconds: null, resource_count: 0, children: [], notes: ["Sem recursos com turno no período."],
      reconciliation: { ok: true, sum_seconds: 0, diff_seconds: 0 },
    }))));
    const dialog = await screen.findByRole("dialog");
    await within(dialog).findByTestId("explanation-total");
    expect(dialog).toHaveTextContent("Sem recursos com turno no período.");
    expect(dialog).not.toHaveTextContent("NaN");
    expect(dialog).not.toHaveTextContent("por recurso");
  });

  it("mostra os dias quando o período tem mais de um", async () => {
    renderPanel(vi.fn(async () => respond(tree({ day_count: 3 }))));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText(/4 recursos, 3 dias/)).toBeInTheDocument();
  });

  it("Esc e clique no fundo fecham; o espaço do chat fica reservado", async () => {
    const { onClose } = renderPanel(vi.fn(async () => respond(tree())));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByTestId("explanation-chat-slot")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.mouseDown(screen.getByTestId("metric-explanation-panel"));
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});

describe("Visão Geral: composição do tempo clicável", () => {
  function overview() {
    const item = (label: string, seconds: number, source_field: string, metric: string, extra: Record<string, unknown> = {}) => ({
      label, seconds, source_field, metric, summed: true, average_seconds: seconds / 4, percentage: 10, ...extra,
    });
    return {
      periodo: {},
      production: { good: 0, scrap: 0, rework: 0, ops: 0, resources: 0, availability: "sem_registros", reason: null, source: "x" },
      production_plan: { value: null, availability: "nao_configurado", reason: null },
      kpis: {
        oee: { value: 0, availability: "disponivel", unit: "%" },
        availability: { value: 80, availability: "disponivel", unit: "%" },
        performance: { value: 36.6, availability: "disponivel", unit: "%" },
        ftt: { value: null, availability: "dados_insuficientes", unit: "%" },
      },
      sectors: [],
      time_composition: {
        items: [
          item("Produção", 7200, "production_seconds", "tempo.producao"),
          item("Recurso sem demanda", 36000, "no_demand_seconds", "tempo.sem_demanda"),
          item("Parada planejada", 3600, "planned_downtime_seconds", "tempo.parada_planejada", { summed: false, percentage: null }),
          item("Fora do turno", 28800, "out_of_shift_seconds", "tempo.fora_turno", { summed: false, percentage: null, average_seconds: null }),
        ] as Array<Record<string, unknown>>,
        resource_count: 4,
        day_count: 1,
        average_note: null as string | null,
        total_seconds: 43200,
        availability: "disponivel",
      },
      audit: { open_issues: [] },
      data_quality: {},
      insights: {
        exceptions: [], exception_count: 0, losses: [], critical_resources: [], limitations: [],
        kpi_explanations: {},
      },
    };
  }

  function renderOverview(body: unknown) {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes("/management/explicacao")) return respond(tree());
      if (path.includes("/overview/trend")) return respond({ code: "x", message: "sem série" }, 500);
      return respond(body);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter><FilterProvider><ManagementOverviewPage /></FilterProvider></MemoryRouter>);
    return fetchMock;
  }

  it("clicar em 'Recurso sem demanda' abre o painel com tempo.sem_demanda", async () => {
    const fetchMock = renderOverview(overview());
    const row = await screen.findByRole("button", { name: /Recurso sem demanda/ });
    expect(row).toHaveTextContent("média");
    fireEvent.click(row);

    const dialog = await screen.findByRole("dialog", { name: /Recurso sem demanda/ });
    await within(dialog).findByTestId("explanation-total");
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/management/explicacao?metric=tempo.sem_demanda"))).toBe(true);
    });
  });

  it("item sem métrica não vira botão; média aparece onde existe e 'não somado' só onde não há média", async () => {
    const body = overview();
    body.time_composition.items.push({ label: "Item antigo", seconds: 60, source_field: "x", summed: true, average_seconds: 15, percentage: 1 });
    renderOverview(body);
    await screen.findByRole("button", { name: /Recurso sem demanda/ });
    expect(screen.queryByRole("button", { name: /Item antigo/ })).not.toBeInTheDocument();
    // Parada planejada não entra no total mas tem média: mostra a média, não "não somado".
    const planned = screen.getByRole("button", { name: /Parada planejada/ });
    expect(planned).toHaveTextContent("média");
    expect(planned).not.toHaveTextContent("não somado");
    // Fora do turno não tem média: aí sim "não somado".
    expect(screen.getByRole("button", { name: /Fora do turno/ })).toHaveTextContent("não somado");
  });

  it("sem recursos mostra a nota do backend, sem média quebrada", async () => {
    const body = overview();
    body.time_composition.resource_count = 0;
    body.time_composition.average_note = "Sem recursos com turno no período.";
    body.time_composition.items.forEach((entry) => { entry.average_seconds = null; });
    renderOverview(body);
    await screen.findByRole("button", { name: /Recurso sem demanda/ });
    expect(screen.getByText("Sem recursos com turno no período.")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("NaN");
  });
});

describe("Operações > Tempo: categorias clicáveis", () => {
  it("só as categorias com id de métrica ganham clique; parada fica como estava", async () => {
    const time = {
      periodo: {}, totals: { producao: 7200, parada: 3600, sem_demanda: 36000, fora_turno: 28800 },
      physical_seconds: 75600, raw_attributed_timeline_seconds: 0, overlap_removed_seconds: 0, overlap_seconds: 0,
      conflicting_state_seconds: 0, conflicting_sector_seconds: 0, by_sector: [], by_resource: [],
      availability: "disponivel", reason: "",
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => (
      String(input).includes("/management/explicacao") ? respond(tree()) : respond(time)
    ));
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter><FilterProvider><OperationsTimePage /></FilterProvider></MemoryRouter>);

    const semDemanda = await screen.findByRole("button", { name: /Explicar Sem demanda/i });
    expect(screen.getByRole("button", { name: /Explicar Produção/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Explicar Parada/i })).not.toBeInTheDocument();
    fireEvent.click(semDemanda);
    await screen.findByRole("dialog", { name: /Recurso sem demanda/ });
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("metric=tempo.sem_demanda"))).toBe(true);
  });
});
