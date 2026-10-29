import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FilterProvider } from "../filters/FilterContext";
import { AnalyticsQualityPage } from "../pages/analytics/AnalyticsPages";
import { AuditAlertsIssuesPage } from "../pages/audit/AuditPages";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function respond(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function valueExplanation(metric: string, label: string, value: number) {
  return {
    kind: "value",
    metric,
    label,
    unit: "count",
    value,
    reason: "Teste.",
    rule: "Regra de teste.",
    children: [],
    excluded: [],
    reconciliation: { ok: true, sum: value, diff: 0 },
    calculated_at: "2026-10-19T14:00:00",
    truncated: false,
    notes: [],
  };
}

const QUALITY = {
  periodo: {},
  totals: { boa: 120, refugo: 7, retrabalho: 0 },
  by_sector: [
    { setor: "corte", boa: 80, refugo: 5, retrabalho: 0 },
    { setor: "Não informado", boa: 40, refugo: 2, retrabalho: 0 },
  ],
  by_product: [],
  scrap_reasons: [],
  rework_reasons: [],
  ftt: { value: 0.9, availability: "disponivel", reason: null },
  availability: "disponivel",
  reason: "",
};

const ISSUES = [{ type: "sobreposicao", severity: "critico", message: "Conflito", seconds: 60 }];
const ALERTS = { items: ISSUES, count: 4, by_severity: { critico: 1, erro: 3 }, reliability_percentage: null, reliability_reason: "sem fórmula oficial" };

function mountFetch() {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.includes("/management/explicacao")) {
      const metric = new URL(path, "http://x").searchParams.get("metric") ?? "";
      return respond(valueExplanation(metric, `Explicação ${metric}`, 1));
    }
    if (path.includes("/analytics/quality")) return respond(QUALITY);
    if (path.includes("/management/alerts")) return respond(ALERTS);
    if (path.includes("/management/internal-alerts")) return respond({ items: [], count: 0 });
    if (path.includes("/api/v1/audit")) {
      return respond({ periodo: {}, issues: ISSUES, count: 4, by_severity: ALERTS.by_severity, records_analyzed: 0, resource_states_analyzed: 0, rateio_sessions_analyzed: 0, physical_state_source: "", reliability_percentage: null, reliability_reason: "" });
    }
    return respond({ items: [], authorizations: [] });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderPage(page: ReactElement) {
  const fetchMock = mountFetch();
  render(<MemoryRouter><FilterProvider>{page}</FilterProvider></MemoryRouter>);
  return fetchMock;
}

function explanationCalls(fetchMock: ReturnType<typeof mountFetch>) {
  return fetchMock.mock.calls.map((call) => String((call as unknown[])[0])).filter((url) => url.includes("/management/explicacao"));
}

describe("Qualidade: números clicáveis", () => {
  it("os totais de peças abrem a explicação qld.* e zero fica texto simples", async () => {
    const fetchMock = renderPage(<AnalyticsQualityPage />);
    const good = await screen.findByRole("button", { name: "Ver de onde vem este número: Produção boa 120" });
    fireEvent.click(good);
    expect(await screen.findByRole("dialog", { name: "Explicação qld.boa" })).toBeInTheDocument();
    expect(explanationCalls(fetchMock)[0]).toContain("metric=qld.boa");
    fireEvent.click(screen.getByRole("button", { name: "Fechar explicação" }));

    expect(screen.getByRole("button", { name: "Ver de onde vem este número: Refugo 7" })).toBeInTheDocument();
    // Retrabalho 0: nada a explicar, não vira botão.
    expect(screen.queryByRole("button", { name: /Retrabalho 0$/ })).not.toBeInTheDocument();
  });

  it("o FTT reaproveita qtd.ftt", async () => {
    const fetchMock = renderPage(<AnalyticsQualityPage />);
    const ftt = await screen.findByRole("button", { name: /Ver de onde vem este número: FTT/ });
    fireEvent.click(ftt);
    await screen.findByRole("dialog");
    await waitFor(() => expect(explanationCalls(fetchMock).some((url) => url.includes("metric=qtd.ftt"))).toBe(true));
  });

  it("na tabela por setor a célula leva o setor como filtro e 'Não informado' não é clicável", async () => {
    const fetchMock = renderPage(<AnalyticsQualityPage />);
    const cell = await screen.findByRole("button", { name: /Boas em .* 80/ });
    fireEvent.click(cell);
    await screen.findByRole("dialog");
    await waitFor(() => {
      const url = explanationCalls(fetchMock).find((item) => item.includes("metric=qld.boa"));
      expect(url).toBeDefined();
      expect(url).toContain("setor=corte");
    });
    expect(screen.queryByRole("button", { name: /Boas em .* 40/ })).not.toBeInTheDocument();
  });
});

describe("Alertas e Auditoria: contagens clicáveis", () => {
  it("Alertas: cada severidade e o total abrem qld.auditoria.*; zero não vira botão", async () => {
    const fetchMock = renderPage(<AuditAlertsIssuesPage />);
    const total = await screen.findByRole("button", { name: "Ver de onde vem este número: Total de alertas 4" });
    fireEvent.click(total);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByTestId("explanation-total")).toBeInTheDocument();
    expect(explanationCalls(fetchMock)[0]).toContain("metric=qld.auditoria.total");
    fireEvent.click(screen.getByRole("button", { name: "Fechar explicação" }));

    expect(screen.getByRole("button", { name: "Ver de onde vem este número: Alertas críticos 1" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ver de onde vem este número: Alertas com erro 3" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Alertas de atenção/ })).not.toBeInTheDocument();
  });

  it("Inconsistências usam os mesmos ids dos Alertas", async () => {
    const fetchMock = renderPage(<AuditAlertsIssuesPage />);
    const errors = await screen.findByRole("button", { name: "Ver de onde vem este número: Inconsistências com erro 3" });
    fireEvent.click(errors);
    await screen.findByRole("dialog");
    await waitFor(() => expect(explanationCalls(fetchMock)[0]).toContain("metric=qld.auditoria.erro"));
  });
});
