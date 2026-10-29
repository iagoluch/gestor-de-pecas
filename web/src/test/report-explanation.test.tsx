import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FilterProvider } from "../filters/FilterContext";
import { ProductionCompletedPage } from "../pages/production/ProductionPages";
import { ReportsPage } from "../pages/reports/ReportsPages";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function respond(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function valueExplanation(metric: string) {
  return {
    kind: "value", metric, label: `Explicação ${metric}`, unit: "pct", value: 50, reason: "Teste.", rule: "Regra de teste.",
    children: [], excluded: [], reconciliation: { ok: true, sum: 50, diff: 0 }, calculated_at: "2026-10-21T10:00:00", truncated: false, notes: [],
  };
}

const PRODUCTION = { availability: "disponivel", good: 120, scrap: 0, rework: 3, ops: 4, reason: "" };
const SECTORS = [
  { setor: "corte", producao_boa: 80, refugo: 0, retrabalho: 3, tempo_produtivo_segundos: 3600 },
  { setor: "Não informado", producao_boa: 40, refugo: 0, retrabalho: 0, tempo_produtivo_segundos: 0 },
];

const PAYLOADS: Record<string, unknown> = {
  gerencial: {
    overview: { production: PRODUCTION, kpis: { oee: { value: 40, unit: "%", availability: "disponivel" } }, sectors: SECTORS },
  },
  producao: { production: PRODUCTION, quality: { reason: "Fonte de teste" }, sectors: SECTORS },
  perdas: {
    paradas: { total_seconds: 7200, count: 5, by_resource: [], by_reason: [] },
    qualidade: { totals: { refugo: 6, retrabalho: 0 } },
  },
  indicadores: {
    analytics: {
      oee: { value: 40, unit: "%", availability: "disponivel" },
      qualidade: { ftt: { value: 95, unit: "%", availability: "disponivel" } },
      tempos: { physical_seconds: 36000, by_resource: [] },
      capacidade: { utilizacao_percentual: 62, availability: "disponivel" },
      confiabilidade: {},
    },
  },
  dados_analiticos: { orders: { items: [] }, audit: { count: 7 }, nestings: { count: 2 }, periodo: {} },
};

function mountFetch(type: string) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.includes("/management/explicacao")) return respond(valueExplanation(new URL(path, "http://x").searchParams.get("metric") ?? ""));
    if (path.includes(`/reports/${type}`)) return respond(PAYLOADS[type]);
    if (path.includes("/orders/production")) return respond(PAYLOADS.producao);
    return respond({ items: [] });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function explanationCalls(fetchMock: ReturnType<typeof mountFetch>) {
  return fetchMock.mock.calls.map((call) => String((call as unknown[])[0])).filter((url) => url.includes("/management/explicacao"));
}

async function opens(fetchMock: ReturnType<typeof mountFetch>, name: RegExp, metric: string, sector?: string) {
  fireEvent.click(await screen.findByRole("button", { name }));
  await screen.findByRole("dialog");
  await waitFor(() => expect(explanationCalls(fetchMock).some((url) => url.includes(`metric=${metric}`) && (!sector || url.includes(`setor=${sector}`)))).toBe(true));
  fireEvent.click(screen.getByRole("button", { name: "Fechar explicação" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
}

const page = (node: React.ReactNode, url = "/") => render(<MemoryRouter initialEntries={[url]}><FilterProvider>{node}</FilterProvider></MemoryRouter>);
const reportPage = (type: string) => page(<ReportsPage />, `/relatorios?tipo=${type}`);
const buttons = (name: RegExp) => screen.queryByRole("button", { name });

describe("Relatórios: números clicáveis com a conta aberta", () => {
  it("Gerencial: cartões e células de setor abrem qtd.* / kpi.oee; zero e 'Não informado' ficam texto", async () => {
    const fetchMock = mountFetch("gerencial");
    reportPage("gerencial");
    await opens(fetchMock, /Ver de onde vem este número: Produção boa 120/, "qtd.boa");
    await opens(fetchMock, /Ver de onde vem este número: Retrabalho 3/, "qtd.retrabalho");
    await opens(fetchMock, /Ver de onde vem este número: OEE 40/, "kpi.oee");
    await opens(fetchMock, /Ver de onde vem este número: Produção boa em corte 80/, "qtd.boa", "corte");
    await opens(fetchMock, /Ver de onde vem este número: Retrabalho em corte 3/, "qtd.retrabalho", "corte");
    expect(buttons(/Refugo/)).not.toBeInTheDocument();
    expect(buttons(/em Não informado/)).not.toBeInTheDocument();
    expect(buttons(/Tempo produtivo/)).not.toBeInTheDocument();
  });

  it("Perdas: refugo e retrabalho abrem qld.*; parada e ocorrências ficam texto; retrabalho zero fica texto", async () => {
    const fetchMock = mountFetch("perdas");
    reportPage("perdas");
    await opens(fetchMock, /Ver de onde vem este número: Refugo 6/, "qld.refugo");
    expect(buttons(/Retrabalho/)).not.toBeInTheDocument();
    expect(buttons(/Tempo de parada/)).not.toBeInTheDocument();
    expect(buttons(/Ocorrências/)).not.toBeInTheDocument();
  });

  it("Indicadores: OEE e FTT abrem a explicação; Utilização e Tempo registrado ficam texto (fonte diferente)", async () => {
    const fetchMock = mountFetch("indicadores");
    reportPage("indicadores");
    await opens(fetchMock, /Ver de onde vem este número: OEE 40/, "kpi.oee");
    await opens(fetchMock, /Ver de onde vem este número: FTT 95/, "qtd.ftt");
    expect(buttons(/Utilização/)).not.toBeInTheDocument();
    expect(buttons(/Tempo registrado/)).not.toBeInTheDocument();
  });

  it("Dados analíticos: só Inconsistências abre qld.auditoria.total", async () => {
    const fetchMock = mountFetch("dados_analiticos");
    reportPage("dados_analiticos");
    await opens(fetchMock, /Ver de onde vem este número: Inconsistências 7/, "qld.auditoria.total");
    expect(buttons(/Nestings/)).not.toBeInTheDocument();
    expect(buttons(/Ordens/)).not.toBeInTheDocument();
  });
});

describe("Relatórios: dois botões de exportação", () => {
  it.each([
    ["gerencial", () => reportPage("gerencial")],
    ["producao", () => page(<ProductionCompletedPage />)],
    ["perdas", () => reportPage("perdas")],
    ["indicadores", () => reportPage("indicadores")],
    ["dados_analiticos", () => reportPage("dados_analiticos")],
  ])("%s: 'Export técnico' e 'Export simples' pedem o mesmo relatório em modos diferentes", async (type, renderNode) => {
    const fetchMock = mountFetch(type as string);
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    renderNode();
    const exportCalls = () => fetchMock.mock.calls.map((call) => String((call as unknown[])[0])).filter((url) => url.includes("/export.xlsx"));
    fireEvent.click(await screen.findByRole("button", { name: "Export técnico" }));
    await waitFor(() => expect(exportCalls().some((url) => url.includes(`/reports/${type}/export.xlsx`) && url.includes("modo=tecnico"))).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "Export simples" }));
    await waitFor(() => expect(exportCalls().some((url) => url.includes("modo=simples"))).toBe(true));
  });
});

describe("Relatórios: uma aba só, com seletor de tipo", () => {
  it("o seletor troca o relatório e mantém os quatro tipos", async () => {
    mountFetch("gerencial");
    reportPage("gerencial");
    await screen.findByRole("heading", { name: /Relatórios/ });
    const tabs = screen.getAllByRole("tab").map((tab) => tab.textContent);
    expect(tabs).toEqual(["Gerencial", "Perdas", "Indicadores", "Dados analíticos"]);
    expect(screen.getByRole("tab", { name: "Gerencial" })).toHaveAttribute("aria-selected", "true");
  });
});

describe("Produção realizada: traz o que era exclusivo do relatório de Produção", () => {
  it("cartão de OPs e a fonte de qualidade continuam visíveis", async () => {
    mountFetch("producao");
    page(<ProductionCompletedPage />);
    expect(await screen.findByText("OPs")).toBeInTheDocument();
    expect(screen.getByText("Fonte de qualidade: Fonte de teste")).toBeInTheDocument();
  });
});
