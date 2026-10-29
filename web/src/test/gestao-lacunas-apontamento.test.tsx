import { cleanup, render, screen, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FilterProvider } from "../filters/FilterContext";
import { AnalyticsQualityPage } from "../pages/analytics/AnalyticsPages";
import { AuditAppointmentsPage } from "../pages/audit/AuditPages";
import { TraceabilityOrderPage } from "../pages/traceability/TraceabilityPages";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function respond(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
}

function renderWith(page: ReactElement, routes: Record<string, unknown>, url = "/") {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    const key = Object.keys(routes).find((route) => path.includes(route));
    return respond(key ? routes[key] : { items: [], authorizations: [] });
  }));
  return render(<MemoryRouter initialEntries={[url]}><FilterProvider>{page}</FilterProvider></MemoryRouter>);
}

const QUALITY = {
  periodo: {},
  totals: { boa: 100, refugo: 6, retrabalho: 5 },
  by_sector: [],
  by_product: [
    { produto: "PROD-A", boa: 90, refugo: 4, retrabalho: 0 },
    { produto: "PROD-B", boa: 10, refugo: 2, retrabalho: 5 },
  ],
  scrap_reasons: [{ motivo: "Trinca", quantidade: 6 }],
  rework_reasons: [{ motivo: "Solda porosa", quantidade: 5 }],
  ftt: { value: 0.9, availability: "disponivel", reason: null },
  availability: "disponivel",
  reason: "",
};

describe("Análises > Qualidade: retrabalho e produto", () => {
  it("desenha retrabalho por motivo ao lado do refugo e a tabela por produto", async () => {
    renderWith(<AnalyticsQualityPage />, { "/analytics/quality": QUALITY });
    const rework = (await screen.findByText("Retrabalho por motivo")).closest("section, div.section-card, article") as HTMLElement;
    expect(within(rework).getByText("Solda porosa")).toBeInTheDocument();
    expect(within(rework).getByText("5 peças")).toBeInTheDocument();
    expect(screen.getByText("Refugo por motivo")).toBeInTheDocument();

    const product = screen.getByText("Qualidade por produto").closest("section, div.section-card, article") as HTMLElement;
    const rowB = within(product).getByText("PROD-B").closest("tr") as HTMLElement;
    expect(within(rowB).getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["PROD-B", "10", "2", "5"]);
  });

  it("sem registros mostra estado vazio em retrabalho e produto", async () => {
    renderWith(<AnalyticsQualityPage />, { "/analytics/quality": { ...QUALITY, by_product: [], rework_reasons: [], scrap_reasons: [] } });
    const rework = (await screen.findByText("Retrabalho por motivo")).closest("section, div.section-card, article") as HTMLElement;
    expect(within(rework).queryByText("Solda porosa")).not.toBeInTheDocument();
    expect(rework.querySelector(".state-box--empty")).not.toBeNull();
    const product = screen.getByText("Qualidade por produto").closest("section, div.section-card, article") as HTMLElement;
    expect(product.querySelector(".state-box--empty")).not.toBeNull();
  });
});

const OPERATION_BASE = { quantidade_boa: 1, refugo: 0, retrabalho: 0, setor: "Corte", status: "Finalizado" };

describe("Rastreabilidade: recurso divergente", () => {
  it("mostra o selo previsto -> real só na operação com evento divergente", async () => {
    renderWith(<TraceabilityOrderPage />, {
      "/traceability/orders/": {
        op: "OP1",
        operations: [
          { ...OPERATION_BASE, apontamento_id: 1, operacao: "10", recurso_real: "LASER2", eventos: [{ id: 1, recurso_divergente: true, recurso_apontado: "LASER2", recurso_roteiro_codigo: "LASER1", recurso_roteiro_nome: "Laser 1" }] },
          { ...OPERATION_BASE, apontamento_id: 2, operacao: "20", recurso_real: "DOBRA1", eventos: [{ id: 2, recurso_divergente: false, recurso_apontado: "DOBRA1" }] },
        ],
        quantity_events: [], cutting_nestings: [], physical_states: [], rateio_sessions: [], operator_participations: [], legacy_movements: [], timeline: [], source_refs: {},
      },
    }, "/?op=OP1");
    const badge = await screen.findByText(/Divergente: previsto LASER1 \(Laser 1\) → real LASER2/);
    expect(badge).toBeInTheDocument();
    expect(screen.getAllByText(/^Divergente/)).toHaveLength(1);
    expect(screen.getByText("Recurso divergente")).toBeInTheDocument();
  });
});

describe("Auditoria > Apontamentos: recurso divergente", () => {
  it("mostra o selo quando a linha traz recurso_divergente e traço quando não", async () => {
    renderWith(<AuditAppointmentsPage />, {
      "/audit/appointments": {
        periodo: {}, availability: "disponivel", page: { page: 1, page_size: 200, total: 2 },
        items: [
          { apontamento_id: 1, op: "OP1", recurso_planejado: "LASER1", recurso_real: "LASER2", recurso_apontado: "LASER2", recurso_divergente: true, quantidade_boa: 1, refugo: 0, retrabalho: 0 },
          { apontamento_id: 2, op: "OP2", recurso_planejado: "DOBRA1", recurso_real: "DOBRA1", recurso_divergente: false, quantidade_boa: 1, refugo: 0, retrabalho: 0 },
        ],
      },
    });
    expect(await screen.findByText(/Divergente: previsto LASER1 → real LASER2/)).toBeInTheDocument();
    expect(screen.getAllByText(/^Divergente/)).toHaveLength(1);
    expect(screen.getByText("Recurso divergente")).toBeInTheDocument();
  });
});
