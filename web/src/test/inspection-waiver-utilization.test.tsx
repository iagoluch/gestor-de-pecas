import { cleanup, render, screen, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FilterProvider } from "../filters/FilterContext";
import { AuditAlertsIssuesPage } from "../pages/audit/AuditPages";
import { TraceabilityNestingPage, TraceabilityOrderPage } from "../pages/traceability/TraceabilityPages";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

const WAIVER = {
  inspecao_id: 7, dispensada: true, op: "OP9", operacao: "20", recurso: "DOBRA1", setor: "dobra",
  produto: "PROD-1", descricao: "Suporte", quantidade: 12, motivo: "Cliente aceitou sem medição",
  autorizado_por: "Carla Supervisora", cracha: "4421", dispensada_em: "2026-10-28T14:30:00", registrada_por: "Ana",
};

const ORDER = {
  op: "OP9", timeline: [], cutting_nestings: [], operations: [], pieces: [],
  inspection_waived: false, inspection_waivers: [],
};

function mount(routes: Record<string, unknown>, page: ReactElement, entry = "/") {
  const mock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    for (const [fragment, body] of Object.entries(routes)) if (path.includes(fragment)) return json(body);
    return json({ items: [], count: 0, by_severity: {}, authorizations: [] });
  });
  vi.stubGlobal("fetch", mock);
  render(<MemoryRouter initialEntries={[entry]}><FilterProvider>{page}</FilterProvider></MemoryRouter>);
  return mock;
}

describe("Rastreabilidade OP: inspeção dispensada", () => {
  it("mostra o selo com motivo, autorizador, crachá e data", async () => {
    mount({ "/traceability/orders/": { ...ORDER, inspection_waived: true, inspection_waivers: [WAIVER] } }, <TraceabilityOrderPage />, "/rastreabilidade/op-produto?op=OP9");
    await screen.findByText("Cliente aceitou sem medição");
    const status = screen.getByText("A inspeção desta OP foi dispensada, sem medição de peças.").closest("[role='status']") as HTMLElement;
    expect(within(status).getByText("Inspeção dispensada")).toBeInTheDocument();
    expect(screen.getByText("Cliente aceitou sem medição")).toBeInTheDocument();
    expect(screen.getByText("Carla Supervisora")).toBeInTheDocument();
    expect(screen.getByText("4421")).toBeInTheDocument();
    expect(screen.getByText(/28\/10\/2026/)).toBeInTheDocument();
  });

  it("sem dispensa não mostra o selo", async () => {
    mount({ "/traceability/orders/": ORDER }, <TraceabilityOrderPage />, "/rastreabilidade/op-produto?op=OP9");
    await screen.findByText("Peças inspecionadas");
    expect(screen.queryByText("Inspeção dispensada")).not.toBeInTheDocument();
  });

  it("mostra aproveitamento nos nestings de corte da OP e '—' quando não há dado", async () => {
    mount({
      "/traceability/orders/": {
        ...ORDER,
        cutting_nestings: [
          { apontamento_id: 1, tarefa: "T1", programa: "P1", nesting: 1, maquina: "LASER1", aproveitamento_percentual: 82.5 },
          { apontamento_id: 2, tarefa: "T2", programa: "P2", nesting: 2, maquina: "LASER1", aproveitamento_percentual: null },
        ],
      },
    }, <TraceabilityOrderPage />, "/rastreabilidade/op-produto?op=OP9");
    expect(await screen.findByText("Nestings de Corte da OP")).toBeInTheDocument();
    expect(screen.getByText("82,5%")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

describe("Auditoria: inspeções dispensadas no período", () => {
  it("lista as dispensas com todos os campos", async () => {
    const mock = mount({
      "/traceability/inspection-waivers": { periodo: {}, items: [WAIVER], count: 1, availability: "disponivel" },
    }, <AuditAlertsIssuesPage />);
    expect(await screen.findByText("Inspeções dispensadas no período")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "OP9" })).toBeInTheDocument();
    for (const text of ["DOBRA1", "PROD-1", "12", "Cliente aceitou sem medição", "Carla Supervisora", "4421"]) {
      expect(screen.getAllByText(new RegExp(text, "i")).length).toBeGreaterThan(0);
    }
    expect(mock.mock.calls.some((call) => String(call[0]).includes("/traceability/inspection-waivers?"))).toBe(true);
  });

  it("mostra estado vazio quando não houve dispensa", async () => {
    mount({
      "/traceability/inspection-waivers": { periodo: {}, items: [], count: 0, availability: "sem_registros" },
    }, <AuditAlertsIssuesPage />);
    expect(await screen.findByText("Nenhuma inspeção dispensada no período")).toBeInTheDocument();
  });
});

describe("Rastreabilidade Nesting: aproveitamento da chapa", () => {
  const BASE = {
    items: [
      { apontamento_id: 1, tarefa: "T1", programa: "P1", nesting: 1, maquina: "LASER1", previsto_segundos: 60, real_segundos: 60, real_periodo_segundos: 60, aproveitamento_percentual: 78.25 },
      { apontamento_id: 2, tarefa: "T2", programa: "P2", nesting: 2, maquina: "LASER1", previsto_segundos: 60, real_segundos: 60, real_periodo_segundos: 60, aproveitamento_percentual: null },
    ],
    count: 2,
    page: { page: 1, page_size: 200, total: 2 },
  };

  it("com dado: cartões, coluna, tabela por tarefa e regra", async () => {
    mount({
      "/traceability/nestings": {
        ...BASE,
        aproveitamento: {
          nestings: 2, nestings_com_dado: 1, nestings_sem_dado: 1, area_usada_total: 10, aproveitamento_medio_percentual: 78.25,
          por_tarefa: [
            { tarefa: "T1", nestings: 1, nestings_com_dado: 1, area_usada: 10, aproveitamento_medio_percentual: 78.25 },
            { tarefa: "T2", nestings: 1, nestings_com_dado: 0, area_usada: 0, aproveitamento_medio_percentual: null },
          ],
          regra: "Aproveitamento = (1 - fração de sucata) x 100, por nesting.",
        },
      },
    }, <TraceabilityNestingPage />);
    const group = await screen.findByRole("group", { name: "Aproveitamento da chapa" });
    expect(within(group).getByText("Aproveitamento médio")).toBeInTheDocument();
    expect(within(group).getByText("78,3%")).toBeInTheDocument();
    expect(within(group).getByText("Nestings com dado")).toBeInTheDocument();
    expect(within(group).getByText("Nestings sem dado")).toBeInTheDocument();
    expect(screen.getByText(/Aproveitamento = \(1 - fração de sucata\)/)).toBeInTheDocument();
    expect(screen.getByText("Aproveitamento por tarefa")).toBeInTheDocument();
    // linha sem dado vira "—", nunca 0%
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText("0,0%")).not.toBeInTheDocument();
  });

  it("sem nenhum nesting com dado: média '—'", async () => {
    mount({
      "/traceability/nestings": {
        ...BASE,
        items: [BASE.items[1]],
        count: 1,
        aproveitamento: {
          nestings: 1, nestings_com_dado: 0, nestings_sem_dado: 1, area_usada_total: 0, aproveitamento_medio_percentual: null,
          por_tarefa: [{ tarefa: "T2", nestings: 1, nestings_com_dado: 0, area_usada: 0, aproveitamento_medio_percentual: null }],
          regra: "Regra de teste.",
        },
      },
    }, <TraceabilityNestingPage />);
    const group = await screen.findByRole("group", { name: "Aproveitamento da chapa" });
    expect(within(group).getByText("Sem nesting com dado no filtro")).toBeInTheDocument();
    expect(within(group).queryByText(/%/)).not.toBeInTheDocument();
  });
});
