import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";
import type { AndonResource, AndonSnapshot } from "../types/andon";

class MockEventSource {
  static instances: MockEventSource[] = [];
  readonly listeners = new Map<string, EventListener>();
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();

  constructor(_url: string | URL, _options?: EventSourceInit) {
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: EventListener) {
    this.listeners.set(type, listener);
  }

  open() {
    this.onopen?.();
  }

  fail() {
    this.onerror?.();
  }

  emit(type: string, payload: Record<string, unknown>) {
    this.listeners.get(type)?.(new MessageEvent(type, { data: JSON.stringify(payload) }));
  }
}

const unavailableMetric = {
  value: null,
  availability: "dados_insuficientes" as const,
  unit: "%",
  reason: "Dados insuficientes para este indicador.",
};

function resource(code: string, sector: string, state: AndonSnapshot["sectors"][number]["resources"][number]["state"]["category"], reason?: string): AndonResource {
  const panel = sector === "Corte" ? "Corte" : ["Dobra", "Usinagem", "Serra"].includes(sector) ? "Caldeiraria" : sector;
  const group = sector === "Corte" ? (code.includes("PLASMA") ? "Plasma" : "Laser") : sector;
  return {
    code,
    name: `Máquina ${code}`,
    sector,
    panel,
    group,
    state: {
      category: state,
      label: {
        producao: "Produção",
        parada: "Parada",
        setup: "Setup",
        retrabalho: "Retrabalho",
        fila: "Fila",
        atividade_sem_op: "Atividade sem OP",
        fora_turno: "Fora de turno",
        sem_demanda: "Sem demanda",
        desconhecido: "Desconhecido",
      }[state],
      display_label: state === "parada" ? reason : undefined,
      started_at: "2026-08-24T14:00:00",
      duration_seconds: 120,
      reason,
      source: "eventos_estado_recurso",
    },
    operation: state === "producao" ? {
      op: "OP-154872",
      operation: "20",
      product: "PROD-01",
      product_description: "Suporte estrutural",
      good_quantity: 18,
      planned_quantity: 24,
    } : null,
    active_operations: state === "producao" ? 1 : 0,
    metrics: {
      oee: unavailableMetric,
      availability: unavailableMetric,
      performance: unavailableMetric,
      ftt: unavailableMetric,
    },
  };
}

function snapshot(states: Array<ReturnType<typeof resource>> = [
  resource("LASER1", "Corte", "producao"),
  resource("PLASMA", "Corte", "setup"),
  resource("DOBRA-01", "Dobra", "producao"),
  resource("DOBRA-02", "Dobra", "parada", "Falta de material"),
  resource("CNC-01", "Usinagem", "setup"),
  resource("CNC-02", "Usinagem", "retrabalho"),
  resource("SOLDA-01", "Solda", "atividade_sem_op"),
  resource("PINTURA-01", "Pintura", "producao"),
], selectedPanel?: string): AndonSnapshot {
  const panelNames = selectedPanel ? [selectedPanel] : ["Corte", "Caldeiraria", "Solda", "Pintura"];
  const sectors = panelNames.map((name) => {
    const resources = states.filter((item) => item.panel === name);
    const groupNames = Array.from(new Set(resources.map((item) => item.group ?? name)));
    return {
      name,
      resource_count: resources.length,
      groups: groupNames.map((group) => ({ name: group, resources: resources.filter((item) => (item.group ?? name) === group) })),
      resources,
    };
  });
  return {
    period: {},
    generated_at: "2026-08-24T14:53:00",
    clock: { now: "2026-08-24T14:53:00", running: false },
    current_shift: { value: null, availability: "nao_configurado", reason: "Turnos por recurso" },
    summary: {
      resources: states.length,
      production: states.filter((item) => item.state.category === "producao").length,
      downtime: states.filter((item) => item.state.category === "parada").length,
      setup: states.filter((item) => item.state.category === "setup").length,
      rework: states.filter((item) => item.state.category === "retrabalho").length,
      queue: states.filter((item) => item.state.category === "fila").length,
      activity_without_op: states.filter((item) => item.state.category === "atividade_sem_op").length,
      out_of_shift: states.filter((item) => item.state.category === "fora_turno").length,
      no_demand: states.filter((item) => item.state.category === "sem_demanda").length,
      unknown: states.filter((item) => item.state.category === "desconhecido").length,
      oee: unavailableMetric,
      availability: unavailableMetric,
      performance: unavailableMetric,
      ftt: unavailableMetric,
    },
    sectors,
    resource_count: states.length,
    simulation_only: false,
    availability: states.length ? "disponivel" : "sem_registros",
    sources: { physical_state: "eventos_estado_recurso" },
  };
}

function authResponse() {
  return new Response(JSON.stringify({
    id: 1,
    name: "Gestor Andon",
    role: "gestor",
    management_access: true,
    andon_access: true,
    operator_access: false,
  }), { status: 200, headers: { "content-type": "application/json" } });
}

function renderAndon(fetchMock: ReturnType<typeof vi.fn>, path = "/andon") {
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("EventSource", MockEventSource);
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider><App /></AuthProvider>
    </MemoryRouter>,
  );
}

afterEach(() => {
  MockEventSource.instances = [];
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Andon Geral Web", () => {
  it("aceita sessão dedicada sem acesso gerencial ou produtivo", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes("/auth/session")) {
        return new Response(JSON.stringify({
          id: 2,
          name: "Andon",
          role: "andon",
          management_access: false,
          andon_access: true,
          operator_access: false,
        }), { status: 200, headers: { "content-type": "application/json" } });
      }
      if (path.includes("/api/v1/andon")) return new Response(JSON.stringify(snapshot()), { status: 200, headers: { "content-type": "application/json" } });
      return new Response(null, { status: 404 });
    });
    const { container } = renderAndon(fetchMock);

    await screen.findByRole("heading", { name: /andon geral/i });
    expect(container.querySelector(".sidebar")).not.toBeInTheDocument();
    expect(container.querySelector(".operator-shell")).not.toBeInTheDocument();
    expect(container.querySelector(".andon-page--tv")).toBeInTheDocument();
  });

  it("abre em rota própria exibindo somente os cartões do Andon", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes("/auth/session")) return authResponse();
      if (path.includes("/api/v1/andon")) return new Response(JSON.stringify(snapshot()), { status: 200, headers: { "content-type": "application/json" } });
      return new Response(null, { status: 404 });
    });
    const { container } = renderAndon(fetchMock);

    await screen.findByRole("heading", { name: /andon geral/i });
    expect(container.querySelector(".sidebar")).not.toBeInTheDocument();
    expect(container.querySelector(".page-tabs")).not.toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(container.querySelector(".andon-header")).not.toBeInTheDocument();
    expect(container.querySelector(".andon-summary")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tela cheia" })).not.toBeInTheDocument();
    expect(container.querySelector(".andon-page--manager")).toBeInTheDocument();
  });

  it("redireciona a entrada gerencial para a visão geral dedicada", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes("/auth/session")) return authResponse();
      if (path.includes("/api/v1/andon")) return new Response(JSON.stringify(snapshot()), { status: 200, headers: { "content-type": "application/json" } });
      return new Response(null, { status: 404 });
    });
    const { container } = renderAndon(fetchMock, "/inicio/andon");

    await screen.findByRole("heading", { name: /andon geral/i });
    expect(container.querySelector(".app-shell")).not.toBeInTheDocument();
    expect(container.querySelector(".andon-page--single-view")).toBeInTheDocument();
  });

  it("renderiza os quatro painéis, subgrupos, estados, OP e indicadores por recurso", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/auth/session")) return authResponse();
      return new Response(JSON.stringify(snapshot()), { status: 200, headers: { "content-type": "application/json" } });
    });
    const { container } = renderAndon(fetchMock);

    await waitFor(() => expect(container.querySelector('[data-sector="Caldeiraria"]')).toBeInTheDocument());
    for (const label of ["Produção", "Setup", "Retrabalho", "Atividade sem OP"]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    expect(screen.getByText("Falta de material")).toBeInTheDocument();
    expect(screen.queryByText("Parada")).not.toBeInTheDocument();
    expect(screen.getAllByText("OP-154872 • 20").length).toBeGreaterThan(0);
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
    expect(container.querySelector('[data-state="parada"]')).toHaveClass("andon-card--parada");
    expect(container.querySelector('[data-state="retrabalho"]')).toHaveClass("andon-card--retrabalho");
    expect(container.querySelector('[data-state="setup"]')).toHaveClass("andon-card--setup");
    const panels = Array.from(container.querySelectorAll(".andon-sector-panel"));
    const columns = Array.from(container.querySelectorAll(".andon-board__column"));
    const panelNames = (root: Element) => Array.from(root.querySelectorAll(".andon-sector-panel h2")).map((title) => title.textContent);
    expect(columns).toHaveLength(2);
    expect(panelNames(columns[0])).toEqual(["Corte", "Solda"]);
    expect(panelNames(columns[1])).toEqual(["Caldeiraria", "Pintura"]);
    expect(panels.map((panel) => panel.querySelector("h2")?.textContent).sort()).toEqual([
      "Caldeiraria", "Corte", "Pintura", "Solda",
    ]);
    expect(screen.getByRole("region", { name: "Corte — Laser" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Corte — Plasma" })).toBeInTheDocument();
    for (const panel of panels) {
      const sector = panel.querySelector("h2")?.textContent;
      expect(Array.from(panel.querySelectorAll(".andon-card")).every((card) => card.getAttribute("data-sector") === sector)).toBe(true);
    }
    expect(container.querySelectorAll('.andon-card[data-active="true"] .andon-card__oee')).toHaveLength(8);
  });

  it("adapta a densidade quando vários recursos estão ativos em todos os setores", async () => {
    const activeResources = [
      resource("LASER-01", "Corte", "producao"),
      resource("PLASMA-01", "Corte", "setup"),
      resource("DOBRA-01", "Dobra", "producao"),
      resource("DOBRA-02", "Dobra", "parada", "Aguardando material"),
      resource("USINA-01", "Usinagem", "setup"),
      resource("USINA-02", "Usinagem", "retrabalho"),
      resource("SERRA-01", "Serra", "producao"),
      ...Array.from({ length: 7 }, (_, index) => resource(`SOLDA-${String(index + 1).padStart(2, "0")}`, "Solda", index === 2 ? "parada" : "producao", index === 2 ? "Aguardando ponte" : undefined)),
      resource("PINTURA-01", "Pintura", "producao"),
      resource("PINTURA-02", "Pintura", "setup"),
      resource("PINTURA-03", "Pintura", "atividade_sem_op"),
    ];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/auth/session")) return authResponse();
      return new Response(JSON.stringify(snapshot(activeResources)), { status: 200, headers: { "content-type": "application/json" } });
    });
    const { container } = renderAndon(fetchMock);

    await waitFor(() => expect(container.querySelectorAll(".andon-card")).toHaveLength(activeResources.length));
    expect(container.querySelector('[data-panel="Corte"]')).toHaveAttribute("data-density", "normal");
    expect(container.querySelector('[data-panel="Caldeiraria"]')).toHaveAttribute("data-density", "medium");
    expect(container.querySelector('[data-panel="Solda"]')).toHaveAttribute("data-density", "high");
    expect(container.querySelector('[data-panel="Pintura"]')).toHaveAttribute("data-density", "normal");
    expect(within(container.querySelector('[data-panel="Solda"]') as HTMLElement).getByText("RECURSOS ATIVOS").parentElement).toHaveTextContent("(7)");
    expect(container.querySelectorAll('.andon-card[data-active="true"] .andon-card__oee')).toHaveLength(activeResources.length);
    expect(screen.getAllByText("OP-154872 • 20").length).toBeGreaterThan(1);
    expect(screen.getByText("Aguardando material")).toBeInTheDocument();
  });

  it("compõe duas colunas independentes e reserva a capacidade de cada painel", async () => {
    const activeResources = [
      resource("LASER-01", "Corte", "producao"),
      ...Array.from({ length: 5 }, (_, index) => resource(`USINA-0${index + 1}`, "Usinagem", "producao")),
      resource("SERRA-01", "Serra", "producao"),
      resource("SOLDA-01", "Solda", "producao"),
      resource("SOLDA-02", "Solda", "setup"),
      resource("PINTURA-01", "Pintura", "producao"),
    ];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/auth/session")) return authResponse();
      return new Response(JSON.stringify(snapshot(activeResources)), { status: 200, headers: { "content-type": "application/json" } });
    });
    const { container } = renderAndon(fetchMock);

    await waitFor(() => expect(container.querySelectorAll(".andon-card")).toHaveLength(activeResources.length));
    const [left, right] = Array.from(container.querySelectorAll(".andon-board__column"));
    // Corte acima de Solda, Caldeiraria acima de Pintura, colunas independentes.
    expect(left.querySelector('[data-panel="Corte"]')?.compareDocumentPosition(left.querySelector('[data-panel="Solda"]') as Node))
      .toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(right.querySelector('[data-panel="Caldeiraria"]')?.compareDocumentPosition(right.querySelector('[data-panel="Pintura"]') as Node))
      .toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(left.querySelector('[data-panel="Caldeiraria"]')).toBeNull();
    expect(right.querySelector('[data-panel="Solda"]')).toBeNull();
    // A Caldeiraria reserva as cinco posições simultâneas de Usinagem.
    expect(container.querySelector('[data-panel="Caldeiraria"]')).toHaveStyle({ "--andon-panel-rows": "5" });
    expect(container.querySelector('[data-panel="Corte"]')).toHaveStyle({ "--andon-panel-rows": "1" });
    // Cada estação de Solda ganha o próprio quadro identificado.
    const solda = container.querySelector('[data-panel="Solda"]') as HTMLElement;
    expect(solda).toHaveAttribute("data-group-flow", "wrap");
    expect(solda.querySelectorAll(".andon-resource-group")).toHaveLength(2);
    expect(within(solda).getByRole("heading", { name: "Máquina SOLDA-01", level: 3 })).toBeInTheDocument();
    expect(within(solda).getByRole("heading", { name: "Máquina SOLDA-02", level: 3 })).toBeInTheDocument();
  });

  it("mantém exclusivamente a visão geral, sem seletor setorial ou cabeçalho informativo", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes("/auth/session")) return authResponse();
      return new Response(JSON.stringify(snapshot()), { status: 200, headers: { "content-type": "application/json" } });
    });
    const { container } = renderAndon(fetchMock);

    await waitFor(() => expect(container.querySelector('[data-sector="Corte"]')).toBeInTheDocument());
    expect(screen.queryByLabelText("Setor do Andon")).not.toBeInTheDocument();
    expect(container.querySelector(".andon-overview-header")).not.toBeInTheDocument();
    expect(container.querySelector(".andon-header__brand")).not.toBeInTheDocument();
    expect(container.querySelectorAll(".andon-sector-panel")).toHaveLength(4);
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("?setor="))).toBe(false);
  });

  it("identifica valores fictícios somente no modo de simulação", async () => {
    const simulated = snapshot();
    simulated.simulation_only = true;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/auth/session")) return authResponse();
      return new Response(JSON.stringify(simulated), { status: 200, headers: { "content-type": "application/json" } });
    });
    const { container } = renderAndon(fetchMock);

    await screen.findByRole("heading", { name: /andon geral/i });
    expect(container.querySelector(".andon-page")).toHaveAttribute("data-simulation", "true");
  });

  it("apresenta atividade diária e atividade s/OP sem inventar OP ou produto", async () => {
    const daily = resource("SOLDA-01", "Solda", "atividade_sem_op");
    daily.state.display_label = "Atividade diária";
    daily.state.activity_description = "Limpeza e organização do posto";
    const withoutOrder = resource("SOLDA-02", "Solda", "atividade_sem_op");
    withoutOrder.state.display_label = "Atividade s/OP";
    withoutOrder.state.activity_description = "Apoio à montagem";
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/auth/session")) return authResponse();
      return new Response(JSON.stringify(snapshot([daily, withoutOrder])), { status: 200, headers: { "content-type": "application/json" } });
    });
    renderAndon(fetchMock);

    expect(await screen.findByText("Atividade diária")).toBeInTheDocument();
    expect(screen.getByText("Atividade s/OP")).toBeInTheDocument();
    expect(screen.getByText("Limpeza e organização do posto")).toBeInTheDocument();
    expect(screen.getByText("Apoio à montagem")).toBeInTheDocument();
    expect(screen.queryByText(/Sem OP/i)).not.toBeInTheDocument();
  });

  it("abre os indicadores completos do recurso ao clicar no OEE sem calcular valores no frontend", async () => {
    const producing = resource("DOBRA-01", "Dobra", "producao");
    producing.metrics = {
      oee: { value: 82.4, availability: "disponivel", unit: "%", reason: "OEE disponibilizado pelo backend." },
      availability: { value: 91.3, availability: "disponivel", unit: "%" },
      performance: { value: 88.6, availability: "disponivel", unit: "%" },
      ftt: unavailableMetric,
    };
    const simulated = snapshot([producing]);
    simulated.simulation_only = true;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/auth/session")) return authResponse();
      return new Response(JSON.stringify(simulated), { status: 200, headers: { "content-type": "application/json" } });
    });
    renderAndon(fetchMock);

    expect(await screen.findByText("82,4%")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Ver indicadores de Máquina DOBRA-01" }));
    const dialog = screen.getByRole("dialog", { name: "Indicadores de Máquina DOBRA-01" });
    expect(within(dialog).getByText("82,4%")).toBeInTheDocument();
    expect(within(dialog).getByText("91,3%")).toBeInTheDocument();
    expect(within(dialog).getByText("88,6%")).toBeInTheDocument();
    expect(within(dialog).getByText("Dados insuficientes para este indicador.")).toBeInTheDocument();
    expect(within(dialog).getByText(/dados fictícios de pré-visualização/i)).toBeInTheDocument();
    expect(within(dialog).getByText("OP-154872")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Indicadores de Máquina DOBRA-01" })).not.toBeInTheDocument();
  });

  it("usa uma única conexão realtime e refaz o snapshot após invalidação", async () => {
    let current = snapshot([resource("DOBRA-01", "Dobra", "producao")]);
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/auth/session")) return authResponse();
      return new Response(JSON.stringify(current), { status: 200, headers: { "content-type": "application/json" } });
    });
    const { container } = renderAndon(fetchMock);
    await screen.findByText("Produção");
    const previousCard = container.querySelector('[data-state="producao"]');
    expect(MockEventSource.instances).toHaveLength(1);
    const andonCalls = () => fetchMock.mock.calls.filter(([input]) => String(input).includes("/api/v1/andon")).length;
    expect(andonCalls()).toBe(1);

    act(() => MockEventSource.instances[0].open());
    await act(async () => {
      MockEventSource.instances[0].emit("refresh", { topic: "live_tick" });
      await Promise.resolve();
    });
    expect(andonCalls()).toBe(1);
    current = snapshot([resource("DOBRA-01", "Dobra", "parada", "Aguardando ponte")]);
    act(() => MockEventSource.instances[0].emit("refresh", { topic: "operator_action" }));
    await waitFor(() => expect(container.querySelector('[data-state="parada"]')).toBeInTheDocument());
    expect(screen.getByText("Aguardando ponte")).toBeInTheDocument();
    expect(container.querySelector('[data-state="parada"]')).not.toBe(previousCard);

    current = snapshot([
      resource("DOBRA-01", "Dobra", "parada", "Aguardando ponte"),
      resource("SOLDA-03", "Solda", "producao"),
    ]);
    act(() => MockEventSource.instances[0].emit("refresh", { topic: "operator_action" }));
    await waitFor(() => expect(container.querySelector('[data-group="Solda"]')).toBeInTheDocument());

    current = snapshot([]);
    act(() => MockEventSource.instances[0].emit("refresh", { topic: "operator_action" }));
    await waitFor(() => expect(container.querySelectorAll(".andon-card")).toHaveLength(0));

    act(() => MockEventSource.instances[0].fail());
    expect(container.querySelectorAll(".andon-card")).toHaveLength(0);
  });

  it("mantém o último snapshot quando um refresh falha", async () => {
    let fail = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/auth/session")) return authResponse();
      if (fail) return new Response(JSON.stringify({ code: "unavailable", message: "Backend indisponível" }), { status: 503, headers: { "content-type": "application/json" } });
      return new Response(JSON.stringify(snapshot([resource("SERRA-01", "Serra", "setup")])), { status: 200, headers: { "content-type": "application/json" } });
    });
    const { container } = renderAndon(fetchMock);
    await waitFor(() => expect(container.querySelector('[data-state="setup"]')).toBeInTheDocument());
    fail = true;
    act(() => MockEventSource.instances[0].emit("refresh", { topic: "data" }));
    await screen.findByRole("alert");
    expect(screen.getByText(/último snapshot válido permanece visível/i)).toBeInTheDocument();
    expect(container.querySelector('[data-state="setup"]')).toBeInTheDocument();
  });

  it("trata fábrica sem recursos com empty state explícito", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/auth/session")) return authResponse();
      return new Response(JSON.stringify(snapshot([])), { status: 200, headers: { "content-type": "application/json" } });
    });
    const { container } = renderAndon(fetchMock);
    expect((await screen.findAllByText("Nenhum recurso ativo")).length).toBe(4);
    expect(container.querySelectorAll(".andon-card")).toHaveLength(0);
  });
});
