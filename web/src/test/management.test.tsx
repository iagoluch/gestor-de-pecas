import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";
import { FilterBar } from "../components/FilterBar";
import { SearchInput } from "../components/SearchInput";
import { SectionCard } from "../components/SectionCard";
import { StatusBadge } from "../components/StatusBadge";
import { PageFrame } from "../components/PageFrame";
import { managementRoutes, sectionById } from "../config/navigation";
import { FilterProvider, useManagementFilters } from "../filters/FilterContext";
import { AnalyticsCapacityPage, AnalyticsOeePage, AnalyticsReliabilityPage } from "../pages/analytics/AnalyticsPages";
import { OperationsOverviewPage, OperationsResourcesPage } from "../pages/operations/OperationsPages";
import { ProductionOrdersPage } from "../pages/production/ProductionPages";
import { ManagementOverviewPage } from "../pages/ManagementOverviewPage";
import { HomeSectorsPage } from "../pages/home/HomePages";

afterEach(() => vi.restoreAllMocks());

function managementInsightsFixture() {
  const metric = { value: null, availability: "dados_insuficientes", unit: "%", reason: "Sem base oficial" };
  const explanation = (key: "oee" | "availability" | "performance" | "ftt", label: string) => ({
    key,
    label,
    metric,
    period: {},
    components: [{ key: "production", label: "Produção", value: 3600, unit: "s" }],
    largest_impact: { cause: "Falta de material", impact_value: 1800, impact_unit: "s" },
    causes: [{ cause: "Falta de material", impact_value: 1800, impact_unit: "s" }],
    resources: [{ resource: "DOBRA-01", impact_value: 1800, impact_unit: "s" }],
    evidence: [{ source: "eventos_estado_recurso", kind: "parada", source_id: "17", resource: "DOBRA-01", op: "OP-17", reason: "Falta de material", start: "2026-08-24T10:00:00", duration_seconds: 1800, details: {} }],
    calculation_policy: "backend_only",
    simulation_only: false,
    limitation: "Sem base oficial",
  });
  return {
    periodo: {},
    generated_at: "2026-08-24T10:30:00",
    exceptions: [{
      id: "stop-17",
      type: "current_unplanned_downtime",
      severity: "alta",
      priority: 3,
      entity_type: "resource",
      entity_id: "DOBRA-01",
      title: "DOBRA-01 está em parada não programada",
      summary: "Parada em andamento: Falta de material.",
      justification: "Estado físico atual do recurso.",
      period: {},
      sector: "Dobra",
      resource: "DOBRA-01",
      op: "OP-17",
      operation: "20",
      cause: "Falta de material",
      impact_value: 1800,
      impact_unit: "s",
      evidence: [{ source: "eventos_estado_recurso", kind: "parada", source_id: "17", resource: "DOBRA-01", op: "OP-17", reason: "Falta de material", start: "2026-08-24T10:00:00", duration_seconds: 1800, details: {} }],
    }],
    exception_count: 1,
    losses: [{ rank: 1, type: "physical_downtime", cause: "Falta de material", impact_value: 1800, impact_unit: "s", evidence: [] }],
    critical_resources: [{ rank: 1, resource: "DOBRA-01", impact_value: 1800, impact_unit: "s", criterion: "tempo_fisico_de_parada_no_periodo", evidence: [] }],
    kpi_explanations: {
      oee: explanation("oee", "OEE"),
      availability: explanation("availability", "Disponibilidade"),
      performance: explanation("performance", "Performance"),
      ftt: explanation("ftt", "FTT / Qualidade"),
    },
    limitations: [],
    policies: { calculation: "backend_only", priority: "fatos", resource_ranking: "tempo", thresholds: "sem limites arbitrários" },
    availability: "disponivel",
    simulation_only: false,
  };
}

describe("contrato gerencial Web", () => {
  it("permite abrir um card pelo conteúdo sem desviar o botão interno", () => {
    const onNavigate = vi.fn();
    const onInternalAction = vi.fn();
    render(
      <SectionCard title="Resumo" navigation={{ label: "Abrir resumo", onNavigate }}>
        <p>Leitura do resumo</p>
        <button type="button" onClick={onInternalAction}>Ver detalhe</button>
      </SectionCard>,
    );

    fireEvent.click(screen.getByText("Leitura do resumo"));
    expect(onNavigate).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "Ver detalhe" }));
    expect(onInternalAction).toHaveBeenCalledOnce();
    expect(onNavigate).toHaveBeenCalledOnce();
    expect(screen.getByRole("button", { name: "Abrir resumo" })).toBeInTheDocument();
  });

  it("mantém as telas gerenciais e inclui as sub-abas do Andon", () => {
    expect(managementRoutes).toHaveLength(38);
    expect(new Set(managementRoutes.map((route) => route.path)).size).toBe(38);
    // Wave 6D: o acompanhamento gerencial da Solda entrou como sub-aba dos
    // Painéis Operacionais, ao lado do Andon, sem aplicação nem navegação
    // paralela. Reorganização 15/09/2026: Andon/Solda/Metas/Pausas
    // saíram da Tela inicial para a seção própria "Painéis Operacionais".
    // Pedido do usuário (21/09/2026): a aba "Solda" saiu do menu — a tela
    // (`/welding-management`) continua existindo, só não é mais navegável.
    expect(managementRoutes).toContainEqual(expect.objectContaining({ label: "Andon", path: "/inicio/andon", sectionId: "panels" }));
    expect(managementRoutes).not.toContainEqual(expect.objectContaining({ label: "Solda" }));
    expect(managementRoutes).toContainEqual(expect.objectContaining({ label: "Metas", path: "/inicio/metas", sectionId: "panels" }));
    expect(managementRoutes).toContainEqual(expect.objectContaining({ label: "Pausas", path: "/inicio/pausas", sectionId: "panels" }));
    // Chamadas reúne configuração e histórico técnico, por isso fica no
    // IagoDev, nunca no Dev Observatory (somente leitura).
    expect(managementRoutes).toContainEqual(expect.objectContaining({ label: "Chamadas", path: "/inicio/chamadas", sectionId: "dev" }));
    // Wave 5: a designação do responsável pelo retrabalho da primeira peça é
    // configuração gerencial e vive no cadastro de crachás que já existia.
    // Reorganização 15/09/2026: Crachás e Cadastro viraram exclusivos da
    // conta admin, agrupados na seção "IagoDev".
    expect(managementRoutes).toContainEqual(expect.objectContaining({ label: "Crachás", path: "/inicio/crachas", sectionId: "dev" }));
    // Cadastro de usuários (14/09/2026): exclusivo da conta admin, mesma
    // tela de login que os funcionários usam.
    expect(managementRoutes).toContainEqual(expect.objectContaining({ label: "Cadastro", path: "/inicio/cadastro", sectionId: "dev" }));
    // Turnos automáticos (15/09/2026): H1/expediente/H2 e futuros, exclusivo
    // da conta admin — muda o corte automático de apontamento da fábrica
    // inteira, não é preferência de gestão comum.
    expect(managementRoutes).toContainEqual(expect.objectContaining({ label: "Turnos", path: "/inicio/turnos", sectionId: "dev" }));
    expect(managementRoutes).toContainEqual(expect.objectContaining({ label: "Confiabilidade", path: "/analises/confiabilidade", sectionId: "analytics" }));
    expect(managementRoutes).toContainEqual(expect.objectContaining({ label: "IA", path: "/inicio/ia", sectionId: "home" }));
  });

  it("usa os ícones oficiais em busca e status textual nos badges", () => {
    const onChange = vi.fn();
    const { container } = render(<><SearchInput value="" onChange={onChange} /><StatusBadge value="Produção" /></>);
    expect(container.querySelector(".search-input img")).toBeInTheDocument();
    expect(screen.getByText("Produção")).toHaveClass("status-badge--success");
  });

  it("aplica filtros no contexto sem calcular indicadores", () => {
    function Probe() {
      const { query } = useManagementFilters();
      return <output>{query}</output>;
    }
    render(<FilterProvider><FilterBar /><Probe /></FilterProvider>);
    fireEvent.change(screen.getByLabelText("Setor"), { target: { value: "Corte" } });
    fireEvent.click(screen.getByRole("button", { name: "Aplicar" }));
    expect(screen.getByRole("status")).toHaveTextContent("setor=Corte");
  });

  it("usa calendário em português e aceita data no formato dd/mm/aaaa", () => {
    function Probe() {
      const { query } = useManagementFilters();
      return <output>{query}</output>;
    }
    render(<FilterProvider><FilterBar /><Probe /></FilterProvider>);
    const start = screen.getByLabelText("Início");
    fireEvent.click(start);
    expect(screen.getByRole("dialog", { name: "Calendário de Início" })).toBeInTheDocument();
    expect(screen.getByText("Do")).toBeInTheDocument();
    expect(screen.getByText("2ª")).toBeInTheDocument();
    fireEvent.change(start, { target: { value: "15/07/2026" } });
    fireEvent.keyDown(start, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Aplicar" }));
    expect(screen.getByRole("status")).toHaveTextContent("inicio=2026-07-15T00%3A00%3A00");
  });

  it("mantém o OEE atual disponível quando a evolução não possui pontos", async () => {
    const response = {
      oee: { value: 82.431, availability: "disponivel", unit: "%", reason: null },
      value: 82.431,
      availability: "disponivel",
      reason: null,
      components: {
        oee: { value: 82.431, availability: "disponivel", unit: "%", reason: null },
        availability: { value: 91.27, availability: "disponivel", unit: "%", reason: null },
        performance: { value: 90.51, availability: "disponivel", unit: "%", reason: null },
        ftt: { value: 99.72, availability: "disponivel", unit: "%", reason: null },
      },
      evolution: {
        points: [],
        availability: "dados_insuficientes",
        reason: "Dados insuficientes para exibir a evolução do OEE no período selecionado.",
      },
    };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(response), {
      status: 200,
      headers: { "content-type": "application/json" },
    })));

    render(<MemoryRouter><FilterProvider><AnalyticsOeePage /></FilterProvider></MemoryRouter>);

    expect(await screen.findByText("82,4%")).toBeInTheDocument();
    expect(screen.getByText("Dados insuficientes para exibir a evolução do OEE no período selecionado.")).toBeInTheDocument();
    expect(screen.queryByText(/não representa aprovação corporativa/i)).not.toBeInTheDocument();
    // Wave 2: o card explicativo virou leitura gerencial de perda, e nenhum
    // texto de implementação do backend ocupa a tela de gestão.
    expect(screen.queryByText(/Valor canônico calculado pelo backend/)).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Onde o OEE está sendo perdido" })).toBeInTheDocument();
    expect(screen.getByText("8,7 p.p. de perda no período.")).toBeInTheDocument();
    expect(screen.getByText("9,5 p.p. de perda no período.")).toBeInTheDocument();
    expect(screen.getByText("0,3 p.p. de perda no período.")).toBeInTheDocument();
  });

  it("renderiza a evolução canônica quando o backend fornece pontos", async () => {
    const response = {
      oee: { value: 84.2, availability: "disponivel", unit: "%", reason: null },
      value: 84.2,
      availability: "disponivel",
      reason: null,
      components: {
        oee: { value: 84.2, availability: "disponivel", unit: "%", reason: null },
        availability: { value: 90, availability: "disponivel", unit: "%", reason: null },
        performance: { value: 94, availability: "disponivel", unit: "%", reason: null },
        ftt: { value: 99.5, availability: "disponivel", unit: "%", reason: null },
      },
      extended_metrics: {
        ae: { value: 79.1, availability: "disponivel", unit: "%", reason: null },
        productivity: { value: 85.6, availability: "disponivel", unit: "%", reason: null },
        utilization: { value: 92.3, availability: "disponivel", unit: "%", reason: null },
      },
      losses_breakdown: {
        fora_de_turno_segundos: 0,
        parada_planejada_segundos: 0,
        parada_nao_planejada_segundos: 0,
        ritmo_segundos: 0,
        refugo_quantidade: 0,
        retrabalho_quantidade: 0,
      },
      evolution: {
        points: [
          {
            at: "2026-08-18T00:00:00", value: 80.1, unit: "%",
            components: {
              oee: { value: 80.1, availability: "disponivel", unit: "%" },
              availability: { value: 88.2, availability: "disponivel", unit: "%" },
              performance: { value: 91.4, availability: "disponivel", unit: "%" },
              ftt: { value: 99.3, availability: "disponivel", unit: "%" },
            },
          },
          {
            at: "2026-08-19T00:00:00", value: 82.6, unit: "%",
            components: {
              oee: { value: 82.6, availability: "disponivel", unit: "%" },
              availability: { value: 90, availability: "disponivel", unit: "%" },
              performance: { value: 92.2, availability: "disponivel", unit: "%" },
              ftt: { value: 99.5, availability: "disponivel", unit: "%" },
            },
          },
          {
            at: "2026-08-20T00:00:00", value: 84.2, unit: "%",
            components: {
              oee: { value: 84.2, availability: "disponivel", unit: "%" },
              availability: { value: 91, availability: "disponivel", unit: "%" },
              performance: { value: 93, availability: "disponivel", unit: "%" },
              ftt: { value: 99.6, availability: "disponivel", unit: "%" },
            },
          },
        ],
        availability: "disponivel",
        reason: null,
        total_buckets: 3,
        available_points: 3,
      },
    };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(response), {
      status: 200,
      headers: { "content-type": "application/json" },
    })));

    render(<MemoryRouter><FilterProvider><AnalyticsOeePage /></FilterProvider></MemoryRouter>);

    expect(await screen.findByRole("img", { name: /Evolução do OEE com 3 pontos/i })).toBeInTheDocument();
    expect(screen.getByText("Último ponto: 84,2%")).toBeInTheDocument();
    expect(screen.queryByText("Dados insuficientes")).not.toBeInTheDocument();
    const firstPoint = screen.getByLabelText(/18\/08\/2026.*OEE 80,1%.*Disponibilidade 88,2%.*Performance 91,4%.*FTT\/Qualidade 99,3%/i);
    fireEvent.mouseEnter(firstPoint);
    const tooltip = screen.getByRole("tooltip", { name: "Detalhes de 18/08/2026" });
    expect(tooltip).toHaveTextContent("OEE: 80,1%");
    expect(tooltip).toHaveTextContent("Disp.: 88,2%");
    expect(tooltip).toHaveTextContent("Perf.: 91,4%");
    expect(tooltip).toHaveTextContent("FTT/Qua.: 99,3%");
    fireEvent.mouseLeave(firstPoint);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    const lastPoint = screen.getByLabelText(/20\/08\/2026.*OEE 84,2%/i);
    fireEvent.focus(lastPoint);
    expect(screen.getByRole("tooltip", { name: "Detalhes de 20/08/2026" })).toBeInTheDocument();
    fireEvent.blur(lastPoint);
  });

  it("autentica e abre a Management View com resposta do backend", async () => {
    const overview = {
      periodo: {},
      production: { good: 0, scrap: 0, rework: 0, ops: 0, resources: 0, availability: "sem_registros", reason: "Nenhum registro de quantidade", source: "eventos_quantidade_producao" },
      production_plan: { value: null, availability: "nao_configurado", reason: "Integração corporativa pendente" },
      kpis: {
        availability: { value: null, availability: "dados_insuficientes", reason: "Sem base" },
        performance: { value: null, availability: "dados_insuficientes", reason: "Sem base" },
        ftt: { value: null, availability: "dados_insuficientes", reason: "Sem base" },
        oee: { value: null, availability: "dados_insuficientes", reason: "Sem base" },
      },
      sectors: [],
      time_composition: { items: [], total_seconds: 0, availability: "sem_registros" },
      audit: { open_issues: [] },
      data_quality: {},
      insights: managementInsightsFixture(),
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/auth/session")) return new Response(JSON.stringify({ code: "not_authenticated", message: "Sessão ausente" }), { status: 401, headers: { "content-type": "application/json" } });
      if (path.includes("/auth/login") && init?.method === "POST") return new Response(JSON.stringify({ id: 1, name: "Gestor Teste", role: "gestor", management_access: true, operator_access: false }), { status: 200, headers: { "content-type": "application/json" } });
      if (path.includes("/auth/logout") && init?.method === "POST") return new Response(null, { status: 204 });
      if (path.includes("/management/overview")) return new Response(JSON.stringify(overview), { status: 200, headers: { "content-type": "application/json" } });
      return new Response(JSON.stringify({ code: "not_found", message: "Não encontrado" }), { status: 404, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter initialEntries={["/login"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    await screen.findByRole("heading", { name: "Entrar no Gestor" });
    fireEvent.change(screen.getByLabelText("Usuário"), { target: { value: "Gestor Teste" } });
    fireEvent.change(screen.getByLabelText("Senha"), { target: { value: "segredo-local" } });
    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Tela inicial — Visão Geral" })).toBeInTheDocument());
    await screen.findByRole("heading", { name: "Planejado × realizado — acumulado" });
    expect(screen.getByText("Gestor Teste")).toBeInTheDocument();
    expect(document.querySelector(".profile-card > i")).not.toBeInTheDocument();
    expect(screen.getAllByText("Dados insuficientes").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Sem registros").length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: "O que precisa de atenção" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Maiores perdas" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Recursos com maior impacto" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Abrir análise das exceções" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Abrir análise das maiores perdas" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Abrir análise dos recursos com maior impacto" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Abrir Produção: Planejado versus Realizado" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Abrir Consulta Operacional: Tempo MES" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Abrir Consulta Operacional: Recursos" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Abrir Auditoria: Inconsistências" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /OEE: Dados insuficientes.*Ver explicação/i }));
    expect(screen.getByRole("dialog", { name: "Entenda o OEE" })).toBeInTheDocument();
    expect(screen.getByText("Componentes do resultado")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Rastrear OP" })).toHaveAttribute("href", "/rastreabilidade/linha-do-tempo?op=OP-17");
    fireEvent.click(screen.getByRole("button", { name: "Fechar explicação" }));

    fireEvent.click(screen.getByRole("button", { name: /Ver análise relacionada a DOBRA-01 está em parada não programada/i }));
    await screen.findByRole("heading", { name: "Análises — Paradas & Setup" });
    fireEvent.click(screen.getByRole("button", { name: "Sair" }));
    await screen.findByRole("heading", { name: "Entrar no Gestor" });
    expect(fetchMock.mock.calls.some(([path, init]) => String(path).includes("/auth/logout") && init?.method === "POST")).toBe(true);
  });
});

function jsonOnce(body: unknown) {
  return vi.fn(async (input: RequestInfo | URL) => {
    void input;
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  });
}

/** Frases que descrevem a implementação do sistema não pertencem a um KPI de
 *  gestão. Elas podem existir em documentação, tooltip ou log. */
const TEXTOS_TECNICOS = [
  /Valor canônico calculado pelo backend/i,
  /Protheus \/ TOTVS/i,
  /Gestor de Peças$/,
  /Não multiplicado/i,
  /Canônica \+ fallback/i,
  /Manual ≠ programada/i,
  /Setup é produtivo/i,
  /eventos_estado_recurso/i,
  /Excel \(\.xlsx\)/i,
  /Nenhum valor faltante é convertido em zero/i,
];

describe("IA-01 — um destino, um nome", () => {
  it.each(managementRoutes.map((route) => [route.path, route] as const))("%s: h1 e título do documento vêm do menu", (path, route) => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ enabled: true }), { status: 200, headers: { "content-type": "application/json" } })));
    const expected = `${sectionById(route.sectionId).label} — ${route.label}`;
    const { unmount } = render(
      <MemoryRouter initialEntries={[path]}><FilterProvider>
        <PageFrame sectionId={route.sectionId} title="Título local divergente" subtitle="" filters={false}>conteúdo</PageFrame>
      </FilterProvider></MemoryRouter>,
    );
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(expected);
    expect(document.title).toBe(`${expected} · Gestor de Peças`);
    unmount();
    expect(document.title).toBe("Gestor de Peças");
  });
});

describe("GE-13 — KPI sem meta canônica", () => {
  function overviewWith(limitations: Array<{ code: string; message: string }>, exceptions: unknown[] = []) {
    const insights = { ...managementInsightsFixture(), limitations, exceptions, exception_count: exceptions.length };
    return {
      periodo: {},
      production: { good: 0, scrap: 0, rework: 0, ops: 0, resources: 0, availability: "sem_registros", reason: null, source: "x" },
      production_plan: { value: null, availability: "nao_configurado", reason: null },
      kpis: {
        oee: { value: 0, availability: "disponivel", unit: "%" },
        availability: { value: 80, availability: "disponivel", unit: "%" },
        performance: { value: 36.6, availability: "disponivel", unit: "%" },
        ftt: { value: null, availability: "dados_insuficientes", unit: "%", reason: "Sem inspeções no período" },
      },
      sectors: [],
      time_composition: { items: [], total_seconds: 0, availability: "sem_registros" },
      audit: { open_issues: [] },
      data_quality: {},
      insights,
    };
  }

  function renderOverview(body: unknown) {
    vi.stubGlobal("fetch", jsonOnce(body));
    render(<MemoryRouter><FilterProvider><ManagementOverviewPage /></FilterProvider></MemoryRouter>);
  }

  it("sem fonte de metas, zero e percentual dizem 'Sem meta definida'; sem dado mostra o motivo", async () => {
    renderOverview(overviewWith([{ code: "kpi_targets_not_configured", message: "Nenhuma fonte de metas" }]));
    const performance = await screen.findByRole("button", { name: /Performance: 36,6%/ });
    expect(performance).toHaveTextContent("Sem meta definida");
    expect(screen.getByRole("button", { name: /OEE: 0%/ })).toHaveTextContent("Sem meta definida");
    const ftt = screen.getByRole("button", { name: /FTT \/ Qualidade: Dados insuficientes/ });
    expect(ftt).toHaveTextContent("Sem inspeções no período");
    expect(ftt).not.toHaveTextContent("Sem meta definida");
  });

  it("com meta configurada, o card não nega a meta e o desvio aparece como exceção do backend", async () => {
    renderOverview(overviewWith([], [{
      ...managementInsightsFixture().exceptions[0],
      id: "target-performance",
      type: "configured_kpi_target",
      title: "Performance abaixo da meta configurada",
      summary: "Valor atual 36.60% e meta 60.00%.",
    }]));
    await screen.findByRole("button", { name: /Performance: 36,6%/ });
    expect(screen.queryByText("Sem meta definida")).not.toBeInTheDocument();
    expect(screen.getByText("Performance abaixo da meta configurada")).toBeInTheDocument();
  });

  it("Setores sem registro: um único vazio, na tabela, e nenhum destaque zerado sem setor", async () => {
    vi.stubGlobal("fetch", jsonOnce({
      items: [],
      highlights: [{ key: "best_good", label: "Maior produção boa", value: 0, unit: "pcs", sector: null }],
    }));
    const { container } = render(<MemoryRouter><FilterProvider><HomeSectorsPage /></FilterProvider></MemoryRouter>);
    expect(await screen.findAllByText("Sem registros para o filtro selecionado")).toHaveLength(1);
    expect(container.querySelector(".metric-card")).toBeNull();
    expect(screen.queryByText("Maior produção boa")).not.toBeInTheDocument();
  });
});

describe("KPIs gerenciais da Wave 2", () => {
  it("na Visão Geral, exibe os recursos de um setor por vez", async () => {
    vi.stubGlobal("EventSource", class {
      addEventListener() {}
      close() {}
    });
    vi.stubGlobal("fetch", jsonOnce({
      periodo: {},
      agora: "2026-09-16T10:00:00",
      summary: { resources: 2, active_operations: 0, by_category: {} },
      resources: [
        { recurso: "DOBRA1", setor: "Dobra", categoria: "fila", ops_ativas: [], quantidade_ops_ativas: 0 },
        { recurso: "SOLDA1", setor: "Solda", categoria: "fila", ops_ativas: [], quantidade_ops_ativas: 0 },
      ],
    }));

    render(<MemoryRouter><FilterProvider><OperationsOverviewPage /></FilterProvider></MemoryRouter>);
    const sectorSelect = await screen.findByRole("combobox", { name: "Selecionar setor" });
    expect(sectorSelect).toHaveValue("Dobra");
    expect(screen.getByText("Dobra1")).toBeInTheDocument();
    expect(screen.queryByText("Solda1")).not.toBeInTheDocument();

    fireEvent.change(sectorSelect, { target: { value: "Solda" } });
    expect(screen.getByText("Solda1")).toBeInTheDocument();
    expect(screen.queryByText("Dobra1")).not.toBeInTheDocument();
  });

  it("mantém os dados na tela quando uma atualização falha e sinaliza que podem estar desatualizados", async () => {
    const refreshListeners: Array<(event: MessageEvent) => void> = [];
    vi.stubGlobal("EventSource", class {
      addEventListener(type: string, listener: (event: MessageEvent) => void) {
        if (type === "refresh") refreshListeners.push(listener);
      }
      close() {}
    });
    let calls = 0;
    vi.stubGlobal("fetch", vi.fn(async () => {
      calls += 1;
      if (calls > 1) {
        return new Response(JSON.stringify({ detail: "indisponível" }), { status: 503, headers: { "content-type": "application/json" } });
      }
      return new Response(JSON.stringify({
        periodo: {},
        agora: "2026-09-16T10:00:00",
        summary: { resources: 1, active_operations: 0, by_category: {} },
        resources: [{ recurso: "DOBRA1", setor: "Dobra", categoria: "fila", ops_ativas: [], quantidade_ops_ativas: 0 }],
      }), { status: 200, headers: { "content-type": "application/json" } });
    }));

    render(<MemoryRouter><FilterProvider><OperationsOverviewPage /></FilterProvider></MemoryRouter>);
    expect(await screen.findByText("Dobra1")).toBeInTheDocument();

    refreshListeners.forEach((listener) => listener(new MessageEvent("refresh", { data: JSON.stringify({ topic: "operations" }) })));

    expect(await screen.findByText(/Os dados exibidos podem estar desatualizados/)).toBeInTheDocument();
    expect(screen.getByText("Dobra1")).toBeInTheDocument();
  });

  it("a Consulta Operacional mostra estado e parada, não a fonte do dado", async () => {
    vi.stubGlobal("fetch", jsonOnce({
      periodo: {},
      agora: "2026-09-04T10:00:00",
      summary: {
        resources: 6,
        active_operations: 3,
        by_category: { producao: 4, parada: 2 },
        longest_stop: { resource: "Laser 02", sector: "Corte", reason: "Falta de material", seconds: 2280 },
      },
      items: [],
      page: { total: 6, page: 1, page_size: 200, pages: 1 },
    }));

    const { container } = render(<MemoryRouter><FilterProvider><OperationsResourcesPage /></FilterProvider></MemoryRouter>);
    await screen.findByText("Recursos no filtro");
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText("Maior parada aberta")).toBeInTheDocument();
    expect(screen.getByText("00:38:00")).toBeInTheDocument();
    expect(screen.getByText("Laser 02 — Falta de material")).toBeInTheDocument();
    for (const padrao of TEXTOS_TECNICOS) {
      expect(container.textContent ?? "").not.toMatch(padrao);
    }
  });

  it("a Produção mostra plano, realizado e saldo em vez da origem do dado", async () => {
    vi.stubGlobal("fetch", jsonOnce({
      periodo: {},
      availability: "disponivel",
      items: [
        { apontamento_id: 1, op: "OP-1", quantidade_planejada: 100, quantidade_boa: 60, refugo: 5, retrabalho: 0, status: "Em processo" },
        { apontamento_id: 2, op: "OP-2", quantidade_planejada: 100, quantidade_boa: 100, refugo: 0, retrabalho: 0, status: "Finalizado" },
      ],
      count: 2,
      page: { total: 2, page: 1, page_size: 200, pages: 1 },
    }));

    const { container } = render(<MemoryRouter><FilterProvider><ProductionOrdersPage /></FilterProvider></MemoryRouter>);
    await screen.findByText("Quantidade planejada");
    expect(screen.getByText("200")).toBeInTheDocument();
    expect(screen.getByText("160")).toBeInTheDocument();
    expect(screen.getByText("Saldo a produzir")).toBeInTheDocument();
    // Wave 4: o planejado é atendido por peças boas + refugo. O refugo consome
    // saldo (65 + 100 = 165 atendidas), logo restam 35 e não 40.
    expect(screen.getByText("35")).toBeInTheDocument();
    expect(screen.getByText(/165 atendidas \(boas \+ refugo\)/)).toBeInTheDocument();
    for (const padrao of TEXTOS_TECNICOS) {
      expect(container.textContent ?? "").not.toMatch(padrao);
    }
  });

  it("apresenta MTBF e MTTR quando existem quebras classificadas", async () => {
    vi.stubGlobal("fetch", jsonOnce({
      periodo: {},
      mtbf_segundos: 67320,
      mttr_segundos: 1620,
      falhas: 3,
      reparos_concluidos: 3,
      tempo_operacional_segundos: 201960,
      tempo_reparo_segundos: 4860,
      por_recurso: [{ recurso: "Laser 02", falhas: 2, tempo_reparo_segundos: 3600, mttr_segundos: 1800 }],
      motivos: [{ motivo: "MANUTENÇÃO CORRETIVA", quantidade: 3 }],
      taxonomia: "Falha é manutenção corretiva.",
      availability: "disponivel",
      reason: "3 falha(s) de equipamento sobre 56,1 h de tempo operacional.",
    }));

    render(<MemoryRouter><FilterProvider><AnalyticsReliabilityPage /></FilterProvider></MemoryRouter>);
    await screen.findByText("MTBF");
    expect(screen.getByText("18h 42m")).toBeInTheDocument();
    expect(screen.getByText("00:27:00")).toBeInTheDocument();
    expect(screen.getByText("Equipamento mais crítico")).toBeInTheDocument();
    expect(screen.getAllByText("Laser 02").length).toBeGreaterThan(0);
  });

  it("período sem falha não vira número inventado", async () => {
    vi.stubGlobal("fetch", jsonOnce({
      periodo: {},
      mtbf_segundos: null,
      mttr_segundos: null,
      falhas: 0,
      reparos_concluidos: 0,
      tempo_operacional_segundos: 36000,
      tempo_reparo_segundos: 0,
      por_recurso: [],
      motivos: [],
      taxonomia: "Falha é manutenção corretiva.",
      availability: "sem_registros",
      reason: "Nenhuma falha de equipamento registrada no período.",
    }));

    render(<MemoryRouter><FilterProvider><AnalyticsReliabilityPage /></FilterProvider></MemoryRouter>);
    await screen.findByText("MTBF");
    expect(screen.getAllByText("Sem registros").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Nenhuma falha de equipamento registrada no período.").length).toBeGreaterThan(0);
    expect(screen.getByText("Nenhuma quebra no período")).toBeInTheDocument();
  });

  it("capacidade sem calendário permanece não configurada, sem estimativa", async () => {
    vi.stubGlobal("fetch", jsonOnce({
      periodo: {},
      items: [{ codigo: "DOBRA1", nome: "Gasparini", tipo_setor: "Dobra", capacidade_segundos: null, carga_segundos: 3600, capacidade_restante_segundos: null, utilizacao_percentual: null, fila: 0 }],
      unidade: "tempo",
      availability: "nao_configurado",
      reason: "Nenhum recurso do filtro possui calendário/turno produtivo cadastrado: sem ele não existe tempo disponível para comparar.",
      recursos: 1,
      recursos_com_calendario: 0,
      recursos_sem_calendario: 1,
      total_capacity_seconds: null,
      total_load_seconds: null,
      total_remaining_seconds: null,
      utilizacao_percentual: null,
      bottleneck_resource: null,
      bottleneck_utilizacao_percentual: null,
    }));

    render(<MemoryRouter><FilterProvider><AnalyticsCapacityPage /></FilterProvider></MemoryRouter>);
    await screen.findByText("Utilização do período");
    expect(screen.getAllByText("Não configurado").length).toBeGreaterThan(0);
    expect(screen.getByText("Não determinado")).toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
  });

  it("capacidade com calendário publica utilização temporal e gargalo", async () => {
    vi.stubGlobal("fetch", jsonOnce({
      periodo: {},
      items: [
        { codigo: "DOBRA1", nome: "Gasparini", tipo_setor: "Dobra", capacidade_segundos: 28800, carga_segundos: 14400, capacidade_restante_segundos: 14400, utilizacao_percentual: 50, fila: 2 },
      ],
      unidade: "tempo",
      availability: "disponivel",
      reason: "Utilização temporal sobre o calendário produtivo cadastrado.",
      recursos: 1,
      recursos_com_calendario: 1,
      recursos_sem_calendario: 0,
      total_capacity_seconds: 28800,
      total_load_seconds: 14400,
      total_remaining_seconds: 14400,
      utilizacao_percentual: 50,
      bottleneck_resource: "DOBRA1",
      bottleneck_utilizacao_percentual: 50,
    }));

    render(<MemoryRouter><FilterProvider><AnalyticsCapacityPage /></FilterProvider></MemoryRouter>);
    await screen.findByText("Utilização do período");
    expect(screen.getAllByText("50%").length).toBeGreaterThan(0);
    expect(screen.getAllByText("4h").length).toBeGreaterThan(0);
    expect(screen.getByText("Gargalo")).toBeInTheDocument();
    expect(screen.getAllByText("DOBRA1").length).toBeGreaterThan(0);
  });

  it("o filtro de setor continua chegando na consulta gerencial", async () => {
    const fetchMock = jsonOnce({
      periodo: {},
      agora: "2026-09-04T10:00:00",
      summary: { resources: 0, active_operations: 0, by_category: {}, longest_stop: null },
      items: [],
      page: { total: 0, page: 1, page_size: 200, pages: 0 },
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter initialEntries={["/consulta-operacional/recursos?setor=Corte"]}><FilterProvider><OperationsResourcesPage /></FilterProvider></MemoryRouter>);
    await waitFor(() => expect(fetchMock.mock.calls.some(([path]) => String(path).includes("setor=Corte"))).toBe(true));
  });
});
