import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";
import { TV_ROTATION_SECONDS } from "../hooks/useTvRotation";
import type { WeldingMacroRow, WeldingManagementSnapshot, WeldingOrderRow } from "../types/welding";

/**
 * Wave 6D — tela gerencial da Solda e o ciclo automático da TV.
 *
 * A tela é de leitura: sem comando, sem seleção de estação e sem login por
 * estação. Os testes cobrem as seis colunas, os três estados, a ausência de
 * modelo e de estação em linguagem humana, múltiplas estações/OPs, atualização
 * automática e a alternância Andon → Solda → Andon sem nenhum clique.
 */

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

  emit(type: string, payload: Record<string, unknown>) {
    this.listeners.get(type)?.(new MessageEvent(type, { data: JSON.stringify(payload) }));
  }
}

function basis(value: string | null, label: string | null, availability = "disponivel") {
  return { value, label, availability };
}

function row(overrides: Partial<WeldingOrderRow> & { op: string }): WeldingOrderRow {
  return {
    operacao: "10",
    produto: { codigo: "SPCX04002086P", descricao: "CONJUNTO SOLDADO ACOPLADOR", quantidade: 4 },
    maquina: { codigo: "S CEN", nome: "SOLDA CENTRAL 710", operacao: "SOLDA CENTRAL" },
    modelo: { value: null, availability: "nao_configurado" },
    estacao: { value: "Estação 1", availability: "disponivel" },
    datas: {
      emissao: null,
      prazo: "2026-09-20T12:00:00",
      inicio_planejado: "2026-09-14T08:00:00",
      fim_planejado: "2026-09-20T12:00:00",
      inicio_real: null,
      fim_real: null,
      criacao: basis("2026-09-10T09:00:00", "Geração da OP no planejamento", "parcial"),
      referencia_prazo: basis("2026-09-20T12:00:00", "Prazo de entrega"),
    },
    status: {
      value: "A VENCER",
      availability: "disponivel",
      reason: "A OP continua dentro da janela de prazo.",
    },
    ...overrides,
  };
}

function snapshot(rows: WeldingOrderRow[] = [row({ op: "A9716901001" })]): WeldingManagementSnapshot {
  const stations = new Map<string | null, WeldingOrderRow[]>();
  for (const item of rows) {
    const key = item.estacao.value ?? null;
    stations.set(key, [...(stations.get(key) ?? []), item]);
  }
  const states = rows.map((item) => item.status.value);
  return {
    setor: "Solda",
    generated_at: "2026-09-11T10:30:00",
    availability: rows.length ? "disponivel" : "sem_registros",
    resumo: {
      ops: new Set(rows.map((item) => item.op)).size,
      linhas: rows.length,
      estacoes: Array.from(stations.keys()).filter(Boolean).length,
      a_vencer: states.filter((state) => state === "A VENCER").length,
      atrasadas: states.filter((state) => state === "ATRASADA").length,
      finalizadas: states.filter((state) => state === "FINALIZADA").length,
      sem_prazo: states.filter((state) => state === null).length,
      sem_modelo: rows.filter((item) => !item.modelo.value).length,
      sem_estacao: rows.filter((item) => !item.estacao.value).length,
    },
    macros: Array.from(
      rows.reduce((acc, item) => {
        const nome = item.produto.descricao ?? item.produto.codigo;
        const atual = acc.get(nome) ?? {
          nome,
          codigo: item.produto.codigo,
          availability: nome ? "disponivel" : "nao_configurado",
          a_vencer: 0, atrasadas: 0, finalizadas: 0, sem_prazo: 0, total: 0,
        };
        const chave = { "A VENCER": "a_vencer", ATRASADA: "atrasadas", FINALIZADA: "finalizadas" }[
          item.status.value ?? ""
        ] ?? "sem_prazo";
        return acc.set(nome, { ...atual, [chave]: atual[chave as "a_vencer"] + 1, total: atual.total + 1 });
      }, new Map<string | null, WeldingMacroRow>()).values(),
    ),
    estacoes: Array.from(stations.entries()).map(([nome, ops]) => ({
      nome,
      availability: nome ? "disponivel" : "sem_registros",
      op_count: ops.length,
      ops,
    })),
    simulation_only: false,
  };
}

function session(role: "gestor" | "andon") {
  return new Response(JSON.stringify({
    id: role === "andon" ? 2 : 1,
    name: role === "andon" ? "TV Fábrica" : "Gestor",
    role,
    management_access: role === "gestor",
    andon_access: true,
    operator_access: false,
  }), { status: 200, headers: { "content-type": "application/json" } });
}

function json(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function apiMock(welding: WeldingManagementSnapshot, role: "gestor" | "andon" = "gestor") {
  return vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.includes("/auth/session")) return session(role);
    if (path.includes("/api/v1/welding")) return json(welding);
    if (path.includes("/api/v1/andon")) return json(andonSnapshot());
    return new Response(null, { status: 404 });
  });
}

/** Andon mínimo: o ciclo da TV precisa das duas visões, não do Andon inteiro. */
function andonSnapshot() {
  const metric = { value: null, availability: "dados_insuficientes", unit: "%", reason: "Sem dados." };
  return {
    period: {},
    generated_at: "2026-09-11T10:30:00",
    clock: { now: "2026-09-11T10:30:00", running: false },
    current_shift: { value: null, availability: "nao_configurado", reason: "Turnos por recurso" },
    summary: {
      resources: 0, production: 0, downtime: 0, setup: 0, rework: 0, queue: 0,
      activity_without_op: 0, out_of_shift: 0, no_demand: 0, unknown: 0,
      oee: metric, availability: metric, performance: metric, ftt: metric,
    },
    sectors: [],
    resource_count: 0,
    simulation_only: false,
    availability: "sem_registros",
    sources: { physical_state: "eventos_estado_recurso" },
  };
}

function renderApp(fetchMock: ReturnType<typeof vi.fn>, path = "/welding-management") {
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
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Acompanhamento gerencial da Solda", () => {
  it("apresenta as colunas da PCP e a OP com a identidade do catálogo", async () => {
    const { container } = renderApp(apiMock(snapshot()));

    await screen.findByRole("heading", { name: /acompanhamento da solda/i });
    const headers = Array.from(container.querySelectorAll(".welding-table thead th")).map(
      (cell) => cell.textContent,
    );
    // A estação saiu da linha e virou o cabeçalho do agrupamento colapsável.
    expect(headers).toEqual(["OP", "Produto / Conjunto", "Máquina / Modelo", "Data", "Status"]);
    expect(container.querySelector(".welding-station__name")?.textContent).toBe("Estação 1");
    // O produto também aparece no acompanhamento por MACRO, então a busca é
    // dentro da tabela por estação: é ela que esta asserção descreve.
    const porEstacao = within(container.querySelector(".welding-table") as HTMLElement);
    expect(porEstacao.getByText("A9716901001")).toBeInTheDocument();
    expect(porEstacao.getByText("CONJUNTO SOLDADO ACOPLADOR")).toBeInTheDocument();
    expect(porEstacao.getByText("SOLDA CENTRAL 710")).toBeInTheDocument();
  });

  it("cruza MACRO com a situação de prazo em uma tabela pivô, sem reclassificar nada", async () => {
    const rows = [
      row({ op: "OP-1", status: { value: "ATRASADA", availability: "disponivel", reason: "" } }),
      row({ op: "OP-2", status: { value: "A VENCER", availability: "disponivel", reason: "" } }),
      row({ op: "OP-3", status: { value: "FINALIZADA", availability: "disponivel", reason: "" } }),
    ];
    const { container } = renderApp(apiMock(snapshot(rows)));

    await screen.findByRole("heading", { name: /acompanhamento por macro/i });
    const linha = container.querySelector(".welding-macro-table tbody tr") as HTMLElement;
    expect(linha.querySelector("th strong")?.textContent).toBe("CONJUNTO SOLDADO ACOPLADOR");
    // Atrasado, a vencer, finalizado, sem prazo, total — a ordem em que a PCP lê a linha.
    const cells = Array.from(linha.querySelectorAll("td")).map((cell) => cell.textContent);
    expect(cells).toEqual(["1", "1", "1", "0", "3"]);
    const tones = Array.from(linha.querySelectorAll("td[data-tone]")).map(
      (cell) => cell.getAttribute("data-tone"),
    );
    expect(tones).toEqual(["late", "due", "done"]);
    // A pizza usa os mesmos três tons da tabela, sem cor nova.
    const wedges = Array.from(container.querySelectorAll(".welding-pie path[data-tone]")).map(
      (path) => path.getAttribute("data-tone"),
    );
    expect(wedges).toEqual(["late", "due", "done"]);
    // A barra 100% empilhada por MACRO idem.
    const bars = Array.from(container.querySelectorAll(".welding-barchart__bar i[data-tone]")).map(
      (bar) => bar.getAttribute("data-tone"),
    );
    expect(bars).toEqual(["late", "due", "done"]);
  });

  it("é gerencial: nenhum comando de posto e nenhum seletor de estação", async () => {
    const { container } = renderApp(apiMock(snapshot()));

    await screen.findByRole("heading", { name: /acompanhamento da solda/i });
    // As sub-abas e o dropdown de estação são navegação da própria leitura; o
    // que não pode existir aqui é comando de posto.
    expect(screen.queryByRole("button", { name: /iniciar|finalizar|parar|retomar|apontar/i })).not.toBeInTheDocument();
    expect(container.querySelectorAll("select")).toHaveLength(0);
  });

  it("organiza a leitura gerencial em sub-abas, com a visão geral aberta", async () => {
    renderApp(apiMock(snapshot()));

    await screen.findByRole("heading", { name: /acompanhamento da solda/i });
    const abas = screen.getAllByRole("tab");
    expect(abas.map((aba) => aba.textContent)).toEqual(["Visão geral", "Atrasos0", "Entregas0"]);
    expect(abas[0]).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toContainElement(abas[0].ownerDocument.querySelector(".welding-macros"));
  });

  it("lista as OPs atrasadas por tempo de vencimento na sub-aba de atrasos", async () => {
    const late = (op: string, prazo: string) => row({
      op,
      status: { value: "ATRASADA", availability: "disponivel", reason: "A janela de prazo da OP já venceu e a Solda não foi concluída." },
      datas: { ...row({ op }).datas, prazo, fim_planejado: prazo, referencia_prazo: basis(prazo, "Prazo de entrega") },
    });
    // generated_at = 2026-09-11T10:30 — o atraso é medido contra a leitura do
    // backend, não contra o relógio do navegador.
    const { container } = renderApp(apiMock(snapshot([
      late("OP-ATRASO-1", "2026-09-09T10:00:00"),
      late("OP-ATRASO-10", "2026-09-01T10:00:00"),
    ])));

    await screen.findByRole("heading", { name: /acompanhamento da solda/i });
    fireEvent.click(screen.getByRole("tab", { name: /atrasos/i }));
    const ops = Array.from(container.querySelectorAll(".welding-card .welding-op strong")).map(
      (cell) => cell.textContent,
    );
    expect(ops).toEqual(["OP-ATRASO-10", "OP-ATRASO-1"]);
    expect(screen.getByText("10 dias")).toBeInTheDocument();
    expect(screen.getByText("2 dias")).toBeInTheDocument();
  });

  it("mede a entrega pelo apontamento real na sub-aba de entregas", async () => {
    const done = row({
      op: "OP-ENTREGUE",
      status: { value: "FINALIZADA", availability: "disponivel", reason: "Solda concluída e apontada pelo posto." },
      datas: {
        ...row({ op: "x" }).datas,
        inicio_real: "2026-09-11T06:00:00",
        fim_real: "2026-09-11T09:00:00",
      },
    });
    renderApp(apiMock(snapshot([done])));

    await screen.findByRole("heading", { name: /acompanhamento da solda/i });
    fireEvent.click(screen.getByRole("tab", { name: /entregas/i }));
    expect(screen.getByRole("heading", { name: /últimas entregas/i })).toBeInTheDocument();
    expect(screen.getByText("OP-ENTREGUE")).toBeInTheDocument();
    // Três horas entre o início e o fim do apontamento: nada é estimado.
    expect(screen.getAllByText("3h").length).toBeGreaterThan(0);
  });

  it("explica a ausência de entrega em vez de mostrar tempo inventado", async () => {
    renderApp(apiMock(snapshot()));

    await screen.findByRole("heading", { name: /acompanhamento da solda/i });
    fireEvent.click(screen.getByRole("tab", { name: /entregas/i }));
    expect(screen.getByText("Nenhuma solda concluída e apontada nesta leitura.")).toBeInTheDocument();
  });

  it("mostra os três estados de acompanhamento com o motivo de cada um", async () => {
    const rows = [
      row({ op: "OP-A-VENCER" }),
      row({
        op: "OP-ATRASADA",
        estacao: { value: "Estação 2", availability: "disponivel" },
        status: {
          value: "ATRASADA",
          availability: "disponivel",
          reason: "Sem apontamento na semana em que a OP foi criada.",
        },
      }),
      row({
        op: "OP-FINALIZADA",
        estacao: { value: "Estação 3", availability: "disponivel" },
        status: {
          value: "FINALIZADA",
          availability: "disponivel",
          reason: "Solda concluída e apontada pelo posto.",
        },
      }),
    ];
    const { container } = renderApp(apiMock(snapshot(rows)));

    await screen.findByText("OP-FINALIZADA");
    expect(screen.getByText("A VENCER")).toBeInTheDocument();
    expect(screen.getByText("ATRASADA")).toBeInTheDocument();
    expect(screen.getByText("FINALIZADA")).toBeInTheDocument();
    expect(screen.getByText("Sem apontamento na semana em que a OP foi criada.")).toBeInTheDocument();
    expect(container.querySelector(".welding-badge--late")).toBeInTheDocument();
    expect(container.querySelector(".welding-badge--done")).toBeInTheDocument();
    expect(container.querySelector(".welding-badge--due")).toBeInTheDocument();
  });

  it("explica a OP sem prazo em vez de chamá-la de a vencer", async () => {
    const semPrazo = row({
      op: "OP-SEM-PRAZO",
      datas: {
        ...row({ op: "x" }).datas,
        prazo: null,
        fim_planejado: null,
        referencia_prazo: basis(null, null, "dados_insuficientes"),
      },
      status: {
        value: null,
        availability: "dados_insuficientes",
        reason: "O planejamento ainda não informou o prazo desta OP.",
      },
    });
    renderApp(apiMock(snapshot([semPrazo])));

    await screen.findByText("OP-SEM-PRAZO");
    expect(screen.getByText("Prazo não informado")).toBeInTheDocument();
    expect(screen.getByText("Prazo ainda não informado pelo planejamento.")).toBeInTheDocument();
    expect(screen.queryByText("A VENCER")).not.toBeInTheDocument();
  });

  it("informa a ausência do modelo em linguagem humana, sem inventar valor", async () => {
    renderApp(apiMock(snapshot()));

    await screen.findByText("A9716901001");
    expect(screen.getByText("Modelo não identificado.")).toBeInTheDocument();
    expect(screen.queryByText(/nao_configurado|null|undefined/i)).not.toBeInTheDocument();
  });

  it("mostra o modelo real quando o cadastro informa", async () => {
    renderApp(apiMock(snapshot([
      row({ op: "A9716901001", modelo: { value: "TRC 710", availability: "disponivel" } }),
    ])));

    await screen.findByText("A9716901001");
    expect(screen.getByText("TRC 710")).toBeInTheDocument();
    expect(screen.queryByText("Modelo não identificado.")).not.toBeInTheDocument();
  });

  it("mostra a estação observada quando ela existe", async () => {
    renderApp(apiMock(snapshot([
      row({ op: "A9716901001", estacao: { value: "Estação 7", availability: "disponivel" } }),
    ])));

    await screen.findByText("A9716901001");
    expect(screen.getByText("Estação 7")).toBeInTheDocument();
    expect(screen.queryByText("Estação ainda não definida.")).not.toBeInTheDocument();
  });

  it("explica a estação ausente sem derivá-la da máquina", async () => {
    renderApp(apiMock(snapshot([
      row({ op: "A9716901001", estacao: { value: null, availability: "sem_registros" } }),
    ])));

    await screen.findByText("A9716901001");
    expect(screen.getByText("Estação ainda não definida.")).toBeInTheDocument();
    // A máquina do roteiro continua visível e não vira estação.
    expect(screen.getByText("SOLDA CENTRAL 710")).toBeInTheDocument();
  });

  it("agrupa as OPs da mesma estação em um dropdown por estação", async () => {
    const rows = [
      row({ op: "OP-01" }),
      row({ op: "OP-02" }),
      row({ op: "OP-03", estacao: { value: "Estação 4", availability: "disponivel" } }),
    ];
    const { container } = renderApp(apiMock(snapshot(rows)));

    await screen.findByText("OP-03");
    const grupos = Array.from(container.querySelectorAll("details.welding-station"));
    expect(grupos).toHaveLength(2);
    const primeira = grupos[0] as HTMLElement;
    expect(primeira.querySelectorAll("tbody tr")).toHaveLength(2);
    expect(within(primeira).getByText("Estação 1")).toBeInTheDocument();
    expect(within(primeira).getByText("2 OPs")).toBeInTheDocument();
    expect(within(grupos[1] as HTMLElement).getByText("1 OP")).toBeInTheDocument();
  });

  it("fecha os dropdowns de estação quando há muitas estações, para não poluir a visão", async () => {
    const rows = ["Estação 1", "Estação 2", "Estação 3"].map((estacao, index) => row({
      op: `OP-0${index}`,
      estacao: { value: estacao, availability: "disponivel" },
    }));
    const { container } = renderApp(apiMock(snapshot(rows)));

    await screen.findByText("OP-02");
    const grupos = Array.from(container.querySelectorAll("details.welding-station"));
    expect(grupos).toHaveLength(3);
    expect(grupos.every((grupo) => !(grupo as HTMLDetailsElement).open)).toBe(true);
    // Duas estações ainda cabem abertas: o fechamento é do volume, não da regra.
    const poucas = renderApp(apiMock(snapshot(rows.slice(0, 2))));
    await within(poucas.container).findByText("OP-01");
    expect(
      Array.from(poucas.container.querySelectorAll("details.welding-station"))
        .every((grupo) => (grupo as HTMLDetailsElement).open),
    ).toBe(true);
  });

  it("mantém a leitura em uma tabela com rolagem própria", async () => {
    const { container } = renderApp(apiMock(snapshot()));

    await screen.findByText("A9716901001");
    const scroll = container.querySelector(".welding-table-scroll");
    expect(scroll).toBeInTheDocument();
    expect(scroll?.querySelector(".welding-table")).toBeInTheDocument();
  });

  it("explica a ausência de OPs sem mostrar estado técnico", async () => {
    renderApp(apiMock(snapshot([])));

    await screen.findByRole("heading", { name: /acompanhamento da solda/i });
    expect(screen.getByText("Nenhuma ordem de conjunto soldado para acompanhar.")).toBeInTheDocument();
    expect(screen.queryByText(/sem_registros/i)).not.toBeInTheDocument();
  });

  it("recarrega a projeção quando o canal em tempo real avisa", async () => {
    const fetchMock = apiMock(snapshot());
    renderApp(fetchMock);

    await screen.findByText("A9716901001");
    const antes = fetchMock.mock.calls.filter(([input]) => String(input).includes("/api/v1/welding")).length;
    act(() => MockEventSource.instances[0].open());
    act(() => MockEventSource.instances[0].emit("refresh", { topic: "operator_action" }));
    await waitFor(() => {
      const depois = fetchMock.mock.calls.filter(([input]) => String(input).includes("/api/v1/welding")).length;
      expect(depois).toBeGreaterThan(antes);
    });
  });

  it("entra pela aba gerencial de Solda sem criar aplicação separada", async () => {
    const { container } = renderApp(apiMock(snapshot()), "/inicio/solda");

    await screen.findByRole("heading", { name: /acompanhamento da solda/i });
    expect(container.querySelector(".app-shell")).not.toBeInTheDocument();
    expect(container.querySelector(".welding-page")).toBeInTheDocument();
  });
});

describe("Ciclo automático da TV", () => {
  it("compõe a tela em modo TV no perfil dedicado", async () => {
    const { container } = renderApp(apiMock(snapshot(), "andon"));

    await screen.findByRole("heading", { name: /acompanhamento da solda/i });
    expect(container.querySelector(".welding-page--tv")).toBeInTheDocument();
    expect(container.querySelector(".sidebar")).not.toBeInTheDocument();
  });

  it("no modo TV mostra só o acompanhamento por MACRO, sem tabela por estação, sub-abas nem rolagem", async () => {
    const { container } = renderApp(apiMock(snapshot(), "andon"), "/welding-management");

    await screen.findByRole("heading", { name: /acompanhamento da solda/i });
    expect(container.querySelector(".welding-macros")).toBeInTheDocument();
    expect(container.querySelector(".welding-pie")).toBeInTheDocument();
    expect(container.querySelectorAll(".welding-macro-table tbody tr").length).toBeGreaterThan(0);
    expect(container.querySelector(".welding-barchart")).toBeInTheDocument();
    expect(container.querySelector(".welding-table-scroll")).not.toBeInTheDocument();
    expect(screen.queryAllByRole("tab")).toHaveLength(0);
    expect(container.querySelector(".welding-footer")).not.toBeInTheDocument();
  });

  it("usa a composição gerencial quando um gestor abre a mesma rota", async () => {
    const { container } = renderApp(apiMock(snapshot()));

    await screen.findByRole("heading", { name: /acompanhamento da solda/i });
    expect(container.querySelector(".welding-page--manager")).toBeInTheDocument();
  });

  it("alterna Andon → Solda → Andon a cada 10 segundos, sem nenhum clique", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { container } = renderApp(apiMock(snapshot(), "andon"), "/andon");

    await screen.findByRole("heading", { name: /andon geral/i });
    expect(container.querySelector(".andon-page--tv")).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(TV_ROTATION_SECONDS * 1000);
    });
    await screen.findByRole("heading", { name: /acompanhamento da solda/i });
    expect(container.querySelector(".andon-page")).not.toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(TV_ROTATION_SECONDS * 1000);
    });
    await screen.findByRole("heading", { name: /andon geral/i });
    expect(container.querySelector(".welding-page")).not.toBeInTheDocument();

    // Terceira volta: o ciclo não para depois de uma alternância.
    await act(async () => {
      vi.advanceTimersByTime(TV_ROTATION_SECONDS * 1000);
    });
    await screen.findByRole("heading", { name: /acompanhamento da solda/i });
  });

  it("não troca de tela antes dos 10 segundos", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderApp(apiMock(snapshot(), "andon"), "/andon");

    await screen.findByRole("heading", { name: /andon geral/i });
    await act(async () => {
      vi.advanceTimersByTime((TV_ROTATION_SECONDS - 1) * 1000);
    });
    expect(screen.getByRole("heading", { name: /andon geral/i })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /acompanhamento da solda/i })).not.toBeInTheDocument();
  });

  it("não alterna a tela do gestor, que continua navegando por conta própria", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderApp(apiMock(snapshot()), "/andon");

    await screen.findByRole("heading", { name: /andon geral/i });
    await act(async () => {
      vi.advanceTimersByTime(TV_ROTATION_SECONDS * 3 * 1000);
    });
    expect(screen.getByRole("heading", { name: /andon geral/i })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /acompanhamento da solda/i })).not.toBeInTheDocument();
  });
});
