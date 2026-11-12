import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FilterProvider } from "../filters/FilterContext";
import { AuditProductionEventsPage, AuditStatusEventsPage, statusClassLabel } from "../pages/audit/AuditPages";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function renderWith(page: ReactElement, routes: Record<string, unknown>) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    const key = Object.keys(routes).find((route) => path.includes(route));
    return new Response(JSON.stringify(key ? routes[key] : { items: [] }), { status: 200, headers: { "content-type": "application/json" } });
  }));
  return render(<MemoryRouter><FilterProvider>{page}</FilterProvider></MemoryRouter>);
}

describe("Auditoria > Eventos de Status", () => {
  it("classifica parada como planejada ou não planejada e o resto pela categoria", () => {
    expect(statusClassLabel({ categoria: "parada", classificacao: "nao_planejada" })).toBe("Parada não planejada");
    expect(statusClassLabel({ categoria: "parada", classificacao: "planejada" })).toBe("Parada planejada");
    expect(statusClassLabel({ categoria: "producao", classificacao: null })).not.toMatch(/Parada/);
  });

  it("lista o status com código, motivo e status em aberto", async () => {
    renderWith(<AuditStatusEventsPage />, {
      "/audit/status-events": {
        summary: { eventos: 1, recursos: 1, paradas_nao_planejadas: 1, em_aberto: 1 },
        page: { page: 1, page_size: 200, total: 1 },
        items: [{
          id: 7, recurso: "LASER1", setor: "CORTE", codigo_status: "P01", descricao: "Falta de material",
          categoria: "parada", classificacao: "nao_planejada", inicio: "2026-11-10T08:00:00", fim: null,
          em_aberto: true, duracao_segundos: 1800, operador: "ANA", motivo: "Sem chapa", comentario: null, op: "OP9",
        }],
      },
    });
    expect(await screen.findByText("Falta de material")).toBeInTheDocument();
    expect(screen.getByText("P01")).toBeInTheDocument();
    expect(screen.getByText("Parada não planejada")).toBeInTheDocument();
    expect(screen.getAllByText("Em aberto")).toHaveLength(2);
    expect(screen.getByText("Sem chapa")).toBeInTheDocument();
  });

  it("sem demanda automático mostra Sistema como colaborador e o porquê", async () => {
    renderWith(<AuditStatusEventsPage />, {
      "/audit/status-events": {
        summary: { eventos: 1, recursos: 1, paradas_nao_planejadas: 0, em_aberto: 1 },
        page: { page: 1, page_size: 200, total: 1 },
        items: [{
          id: 8, recurso: "DOBRA1", categoria: "fila", inicio: "2026-11-10T09:00:00", fim: null, em_aberto: true,
          operador: "ANA", autor: "Sistema", automatico: true, motivo: "Recurso sem demanda",
          causa: "Recurso ficou sem OP ativa depois que ANA interrompeu a OP OP7", comentario: null, op: null,
        }],
      },
    });
    expect(await screen.findByText("Sistema")).toBeInTheDocument();
    expect(screen.queryByText("ANA")).not.toBeInTheDocument();
    expect(screen.getByText("Recurso sem demanda — Recurso ficou sem OP ativa depois que ANA interrompeu a OP OP7")).toBeInTheDocument();
  });

  it("filtros na barra de cima e recurso escolhido digitando vai para o servidor", async () => {
    renderWith(<AuditStatusEventsPage />, {
      "/audit/status-events": {
        summary: { eventos: 0, recursos: 0, paradas_nao_planejadas: 0, em_aberto: 0 },
        page: { page: 1, page_size: 100, total: 0 },
        opcoes: { recursos: [{ codigo: "LASER1", nome: "CORTE LASER" }, { codigo: "DOBRA1", nome: "Gasparini" }], status: ["Setup"], classes: ["parada_planejada"] },
        items: [],
      },
    });
    const recurso = await screen.findByLabelText("Recurso");
    // Os filtros da tabela ficam na mesma barra dos filtros gerais.
    expect(recurso.closest("form")).toBe(screen.getByRole("form", { name: "Filtros gerenciais" }));
    expect(document.querySelector('datalist option[value="Parada planejada"]')).not.toBeNull();
    // A lista mostra o nome líquido; digitar parte dele e apertar Enter escolhe o recurso pelo código.
    fireEvent.change(recurso, { target: { value: "gaspa" } });
    fireEvent.keyDown(recurso, { key: "Enter" });
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes("evento_recurso=DOBRA1"))).toBe(true));
    expect(recurso).toHaveValue("Gasparini");
  });
});

describe("Auditoria > Eventos de Produção", () => {
  it("mostra atividade, quantidades, linha do Corte e quantidade sem evento", async () => {
    renderWith(<AuditProductionEventsPage />, {
      "/audit/production-events": {
        summary: { eventos: 3, quantidade_boa: 12, quantidade_refugo: 1, quantidade_retrabalho: 0, quantidade_sem_evento: 1 },
        page: { page: 1, page_size: 200, total: 3 },
        items: [
          { apontamento_id: 1, op: "OP1", produto: "P-100", operacao: "020", recurso: "DOBRA1", atividade: "setup", inicio: "2026-11-10T07:00:00", fim: "2026-11-10T07:30:00", tempo_real_segundos: 1800, quantidade_boa: null, quantidade_refugo: null, quantidade_retrabalho: null },
          { apontamento_id: null, tarefa: "T55", plano: "PL-3", recurso: "LASER1", atividade: "producao", inicio: "2026-11-10T06:00:00", fim: "2026-11-10T06:40:00" },
          { apontamento_id: null, op: "OP2", operacao: "010", atividade: null, inicio: "2026-11-10T05:00:00", quantidade_boa: 2, quantidade_refugo: 0, quantidade_retrabalho: 0, inconsistencia: "quantidade_sem_evento" },
        ],
      },
    });
    expect(await screen.findByText("Tarefa T55 · Plano PL-3")).toBeInTheDocument();
    expect(screen.getByText("Quantidade sem evento")).toBeInTheDocument();
    expect(screen.getByText("1 quantidade(s) sem evento")).toBeInTheDocument();
    expect(screen.getByText("P-100")).toBeInTheDocument();
  });

  it("primeira peça aprovada e reprovada aparecem com quem decidiu", async () => {
    renderWith(<AuditProductionEventsPage />, {
      "/audit/production-events": {
        summary: { eventos: 2, quantidade_boa: 0, quantidade_refugo: 0, quantidade_retrabalho: 0, quantidade_sem_evento: 0 },
        page: { page: 1, page_size: 200, total: 2 },
        items: [
          { apontamento_id: 1, op: "OP1", colaborador: "ANA", atividade: "primeira_peca", resultado_primeira_peca: "RETRABALHO", inicio: "2026-11-10T08:00:00", fim: "2026-11-10T08:00:00" },
          { apontamento_id: 1, op: "OP1", colaborador: "BIA", atividade: "primeira_peca", resultado_primeira_peca: "CONFORME", inicio: "2026-11-10T08:30:00", fim: "2026-11-10T08:30:00" },
        ],
      },
    });
    expect(await screen.findByText("1ª peça aprovada")).toBeInTheDocument();
    expect(screen.getByText("1ª peça reprovada (retrabalho)")).toBeInTheDocument();
  });
});
