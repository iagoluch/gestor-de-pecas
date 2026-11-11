import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { FilterProvider, useManagementFilters } from "../filters/FilterContext";
import { AuditAnalyticsPage } from "../pages/audit/AuditAnalyticsPage";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const CATALOGO = {
  regra_periodo: "Entra todo evento que toca o período.",
  grupos: ["Produção e rastreio", "Paradas e tempos", "Dados e sistema"],
  tipos: [
    { id: "01", grupo: "Produção e rastreio", somente_consulta: false, titulo: "Eventos de status", descricao: "Status", filtros_comuns: ["setor", "recurso", "op", "operador"], filtros_proprios: ["produto", "operacao", "evento_status", "evento_classe", "em_aberto"], campos: [] },
    { id: "02", grupo: "Produção e rastreio", somente_consulta: false, titulo: "Eventos de produção", descricao: "Produção", filtros_comuns: ["setor", "recurso", "op", "operador"], filtros_proprios: ["produto", "operacao"], campos: [] },
    { id: "08", grupo: "Paradas e tempos", somente_consulta: false, titulo: "Tempo padrão x real", descricao: "Tempo", filtros_comuns: ["setor", "recurso", "op", "operador"], filtros_proprios: [], campos: [] },
    { id: "19", grupo: "Dados e sistema", somente_consulta: true, titulo: "Envios ao Protheus", descricao: "Envios", filtros_comuns: [], filtros_proprios: [], campos: [] },
  ],
};

const STATUS = {
  tipo: "01", titulo: "Eventos de status", as_of: "2026-11-10T09:30:00", estado: "com_dados", fontes: {}, avisos: [],
  regra_periodo: "Entra todo evento que toca o período.",
  campos: [{ chave: "id", rotulo: "ID do evento" }, { chave: "motivo", rotulo: "Motivo" }, { chave: "em_aberto", rotulo: "Em aberto" }],
  summary: { eventos: 1, recursos: 1, paradas_nao_planejadas: 1, em_aberto: 1 },
  opcoes: { status: ["Falta de material"], classes: ["parada_nao_planejada"] },
  page: { page: 1, page_size: 100, total: 1 },
  items: [{
    id: 7, recurso: "LASER1", recurso_nome: "Laser 1", setor: "CORTE", codigo_status: "P01", descricao: "Falta de material",
    categoria: "parada", classificacao: "nao_planejada", inicio: "2026-11-10T08:00:00", fim: null, em_aberto: true,
    duracao_segundos: 1800, operador: "ANA", motivo: "Sem chapa", comentario: null, op: "OP9",
  }],
};

const PRODUCAO = {
  tipo: "02", titulo: "Eventos de produção", as_of: "2026-11-10T09:30:00", estado: "sem_registros", fontes: {},
  avisos: ["Com filtro de OP, operação ou produto, as linhas do Corte (por tarefa e plano) não entram."],
  regra_periodo: "Entra todo evento que toca o período.", campos: [], summary: {}, page: { page: 1, page_size: 100, total: 0 }, items: [],
};

const TEMPO = {
  tipo: "08", titulo: "Tempo padrão x real", as_of: "2026-11-10T09:30:00", estado: "com_dados", fontes: {}, avisos: [],
  regra_periodo: "Entra todo evento que toca o período.",
  campos: [{ chave: "op", rotulo: "OP" }, { chave: "desvio_percentual", rotulo: "Desvio %" }],
  summary: { comparaveis: 2, desvio_percentual: null },
  page: { page: 1, page_size: 100, total: 2 },
  items: [{ op: "OP7", desvio_percentual: 25 }, { op: "OP8", desvio_percentual: null }],
};

const ENVIOS = { ...TEMPO, tipo: "19", titulo: "Envios ao Protheus", campos: [{ chave: "op", rotulo: "OP" }], summary: { envios: 0 }, estado: "sem_registros", items: [], page: { page: 1, page_size: 100, total: 0 } };

function stubFetch(routes: Record<string, unknown>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    const key = Object.keys(routes).sort((a, b) => b.length - a.length).find((route) => path.includes(route));
    return new Response(JSON.stringify(key ? routes[key] : {}), { status: 200, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** Põe um valor na barra global de filtros antes de abrir a tela. */
function WithOp({ op }: { op: string }) {
  const { filters, setFilters } = useManagementFilters();
  if (filters.op !== op) setFilters({ ...filters, op });
  return <AuditAnalyticsPage />;
}

function renderPage(path = "/auditoria/analitica", op?: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <FilterProvider>{op ? <WithOp op={op} /> : <AuditAnalyticsPage />}</FilterProvider>
    </MemoryRouter>,
  );
}

describe("Auditoria analítica", () => {
  it("tipo 01 mostra as mesmas colunas da tela antiga, a referência e o detalhe com todos os campos", async () => {
    stubFetch({ "/audit/reports/01": STATUS, "/audit/reports": CATALOGO });
    renderPage();
    expect(await screen.findByText("Falta de material", { selector: "td, td *" })).toBeTruthy();
    for (const label of ["OP", "Recurso", "Setor", "Código", "Status", "Classificação", "Início", "Fim", "Duração no período", "Colaborador", "Motivo / observação"]) {
      expect(screen.getAllByRole("columnheader").some((cell) => cell.textContent?.startsWith(label))).toBe(true);
    }
    expect(screen.getByText(/Referência \(as_of\)/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Ver" }));
    expect(await screen.findByText("Detalhe do registro")).toBeTruthy();
    expect(screen.getByText("ID do evento")).toBeTruthy();
    expect(screen.getByText("Sim")).toBeTruthy();
  });

  it("trocar de tipo mantém a OP da barra, mostra os avisos e o estado sem registros", async () => {
    const fetchMock = stubFetch({ "/audit/reports/01": STATUS, "/audit/reports/02": PRODUCAO, "/audit/reports": CATALOGO });
    renderPage("/auditoria/analitica?tipo=01", "OP9");
    await screen.findByText("Falta de material", { selector: "td, td *" });
    fireEvent.change(screen.getByLabelText("Tipo de relatório"), { target: { value: "02" } });
    expect(await screen.findByText("Sem registros")).toBeTruthy();
    expect(screen.getByText(/linhas do Corte/)).toBeTruthy();
    const call = fetchMock.mock.calls.map(([input]) => String(input)).find((path) => path.includes("/audit/reports/02?"));
    expect(call).toContain("op=OP9");
  });

  it("exporta pela API com os mesmos filtros", async () => {
    stubFetch({ "/audit/reports/01": STATUS, "/audit/reports": CATALOGO });
    const download = vi.spyOn(api, "download").mockResolvedValue(undefined);
    renderPage();
    await screen.findByText("Falta de material", { selector: "td, td *" });
    expect(screen.queryByRole("button", { name: /CSV/ })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Exportar Excel" }));
    await waitFor(() => expect(download).toHaveBeenCalled());
    const [path, name] = download.mock.calls[0];
    expect(path).toMatch(/^\/api\/v1\/audit\/reports\/01\/export\.xlsx\?inicio=/);
    expect(name).toBe("auditoria_tipo_01.xlsx");
  });

  it("tipos novos: agrupados, colunas do catálogo, desvio pronto do servidor e sem dado como 'sem registros'", async () => {
    stubFetch({ "/audit/reports/08": TEMPO, "/audit/reports": CATALOGO });
    renderPage("/auditoria/analitica?tipo=08");
    expect(await screen.findByText("OP7")).toBeTruthy();
    expect(screen.getByText("25")).toBeTruthy();
    expect(screen.getByText("sem registros")).toBeTruthy();
    expect(screen.getByRole("group", { name: "Paradas e tempos" })).toBeTruthy();
  });

  it("Envios ao Protheus é só consulta e tipo desconhecido cai no primeiro do catálogo", async () => {
    stubFetch({ "/audit/reports/19": ENVIOS, "/audit/reports/01": STATUS, "/audit/reports": CATALOGO });
    renderPage("/auditoria/analitica?tipo=19");
    expect(await screen.findByText(/Só consulta/)).toBeTruthy();
    cleanup();
    renderPage("/auditoria/analitica?tipo=17");
    expect(await screen.findByText("Falta de material", { selector: "td, td *" })).toBeTruthy();
  });
});
