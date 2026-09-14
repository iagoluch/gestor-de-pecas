import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CuttingPage } from "../pages/operator/CuttingPage";

// Wave 6C — a tela de Corte apresenta TAREFA > PLANO/NESTING > OP > PRODUTO.
// Nenhuma ação nova: iniciar/parar/finalizar continuam os mesmos comandos.

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

const PLANO_001 = {
  programa: "001",
  ordem: 1,
  estado: "AGUARDANDO CORTE",
  chapas_total: 2,
  chapas_cortadas: 0,
  chapas_em_corte: 0,
  chapas_aguardando: 2,
  chapas_disponiveis_destaque: 0,
  libera_destaque: true,
  // Duas chapas físicas do MESMO programa: a repetição vem do SigmaNEST.
  repeticoes: [1, 2],
  nome_chapa: "CHAPA 3000x1500",
  quantidade_processo: 6,
  tempo_previsto_segundos: 600,
  plano_hash: "h-001-1",
  plano_hashes_aguardando: ["h-001-1", "h-001-2"],
  apontamento_ids_em_processo: [],
  ops: [
    { codigo_op: "1079689C001", produto_codigo: "PNT001", produto_descricao: "PRODUTO A", quantidade: 4 },
    { codigo_op: "1079689C002", produto_codigo: "PNT002", produto_descricao: "PRODUTO B", quantidade: 2 },
  ],
  chapas: [
    { plano_hash: "h-001-1", sequencia: 1, programa: "001", nome_chapa: "CHAPA 3000x1500", repeticao: 1, status: "Aguardando", tempo_previsto_segundos: 300, tempo_real_segundos: null },
    { plano_hash: "h-001-2", sequencia: 2, programa: "001", nome_chapa: "CHAPA 3000x1500", repeticao: 2, status: "Aguardando", tempo_previsto_segundos: 300, tempo_real_segundos: null },
  ],
};

const PLANO_002 = {
  programa: "002",
  ordem: 2,
  estado: "DISPONÍVEL PARA DESTAQUE",
  chapas_total: 1,
  chapas_cortadas: 1,
  chapas_em_corte: 0,
  chapas_aguardando: 0,
  chapas_disponiveis_destaque: 1,
  libera_destaque: true,
  repeticoes: [1],
  nome_chapa: "CHAPA 2000x1000",
  quantidade_processo: 3,
  tempo_previsto_segundos: 240,
  plano_hash: "h-002-1",
  plano_hashes_aguardando: [],
  apontamento_ids_em_processo: [],
  ops: [
    { codigo_op: "1079689C003", produto_codigo: "PNT003", produto_descricao: "PRODUTO C", quantidade: 3 },
  ],
  chapas: [
    { plano_hash: "h-002-1", sequencia: 3, programa: "002", nome_chapa: "CHAPA 2000x1000", repeticao: 1, status: "Finalizado", tempo_previsto_segundos: 240, tempo_real_segundos: 260 },
  ],
};

const TAREFA = {
  codigo_tarefa: "ZZT4503",
  plano_hash: "h-001-1",
  material: "A36",
  espessura: 6.35,
  status: "Aguardando",
  nesting_count: 3,
  quantidade_chapas: 3,
  quantidade_processo: 9,
  nestings_concluidos: 1,
  nestings_aguardando: 2,
  tempo_previsto_segundos: 840,
  tempo_real_segundos: 260,
  planos_count: 2,
  expansivel: true,
  ops_relacionadas: ["1079689C001", "1079689C002", "1079689C003"],
  ops_sem_plano: [],
  planos: [PLANO_001, PLANO_002],
  nestings: [...PLANO_001.chapas, ...PLANO_002.chapas],
};

function stubQueue(items: unknown[], extra?: (path: string, init?: RequestInit) => Response | null) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    const custom = extra?.(path, init);
    if (custom) return custom;
    if (path.includes("/operator/stop-reasons")) return json({ items: [] });
    if (path.includes("/cutting/queue")) return json({ resource: "Laser Ensis 3015", resource_state: null, items, sync: { ultima_sincronizacao: "2026-09-11T08:00:00" } });
    return json({ code: "not_found", message: "Não encontrado" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderCorte() {
  return render(<CuttingPage resource="Laser Ensis 3015" />);
}

function planoDe(programa: string) {
  const cabecalho = screen.getByText(programa);
  const bloco = cabecalho.closest("section.cutting-plan");
  if (!bloco) throw new Error(`bloco do plano ${programa} não encontrado`);
  return bloco as HTMLElement;
}

describe("hierarquia da tela de Corte", () => {
  it("renderiza tarefa, planos, OPs e produtos sem abrir outra tela", async () => {
    stubQueue([TAREFA]);
    renderCorte();

    expect(await screen.findByRole("heading", { name: "ZZT4503" })).toBeInTheDocument();
    expect(screen.getByText("001")).toBeInTheDocument();
    expect(screen.getByText("002")).toBeInTheDocument();

    const plano001 = planoDe("001");
    expect(within(plano001).getByText("OP 1079689C001")).toBeInTheDocument();
    expect(within(plano001).getByText("PNT001 — PRODUTO A")).toBeInTheDocument();
    expect(within(plano001).getByText("OP 1079689C002")).toBeInTheDocument();
    // A OP do plano 002 não vaza para o plano 001.
    expect(within(plano001).queryByText("OP 1079689C003")).not.toBeInTheDocument();
    expect(within(planoDe("002")).getByText("OP 1079689C003")).toBeInTheDocument();
  });

  it("recolhe e expande a tarefa mantendo o resumo visível", async () => {
    stubQueue([TAREFA]);
    renderCorte();

    const toggle = await screen.findByRole("button", { expanded: true });
    expect(screen.getByText("001")).toBeInTheDocument();

    fireEvent.click(toggle);

    await waitFor(() => expect(screen.queryByText("001")).not.toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "ZZT4503" })).toBeInTheDocument();
    expect(screen.getByRole("button", { expanded: false })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { expanded: false }));
    expect(await screen.findByText("001")).toBeInTheDocument();
  });

  it("mostra o estado de cada plano sem confundir corte com Destaque", async () => {
    stubQueue([TAREFA]);
    renderCorte();

    await screen.findByRole("heading", { name: "ZZT4503" });
    expect(within(planoDe("001")).getByText("AGUARDANDO CORTE")).toBeInTheDocument();
    expect(within(planoDe("002")).getByText("DISPONÍVEL PARA DESTAQUE")).toBeInTheDocument();
    expect(screen.queryByText(/aguardando destaque/i)).not.toBeInTheDocument();
  });

  it("mostra chapas e repetição vindas do SigmaNEST, sem assumir uma chapa por nesting", async () => {
    stubQueue([TAREFA]);
    renderCorte();

    await screen.findByRole("heading", { name: "ZZT4503" });
    const plano001 = planoDe("001");
    expect(within(plano001).getByText("0 de 2")).toBeInTheDocument();
    expect(within(plano001).getByText("1, 2")).toBeInTheDocument();
    expect(within(plano001).getAllByRole("row")).toHaveLength(3);
    expect(within(planoDe("002")).getByText("1 de 1")).toBeInTheDocument();
  });

  it("seleciona o plano ao iniciar o corte, com o mesmo comando de sempre", async () => {
    const fetchMock = stubQueue([TAREFA], (path, init) => {
      if (path.includes("/cutting/actions") && init?.method === "POST") {
        return json({ ok: true, message: "Nesting iniciado." });
      }
      return null;
    });
    renderCorte();

    await screen.findByRole("heading", { name: "ZZT4503" });
    // Somente o plano que ainda aguarda oferece o comando.
    const botoes = screen.getAllByRole("button", { name: "Iniciar corte" });
    expect(botoes).toHaveLength(1);
    await act(async () => { fireEvent.click(botoes[0]); });

    const chamada = fetchMock.mock.calls.find(([path, init]) => String(path).includes("/cutting/actions") && init?.method === "POST");
    expect(JSON.parse(String(chamada?.[1]?.body))).toMatchObject({
      resource: "Laser Ensis 3015", action: "Início", plan_hash: "h-001-1",
    });
    await screen.findByText("Nesting iniciado.");
  });

  it("apresenta várias tarefas, cada uma com seus próprios planos", async () => {
    const outra = {
      ...TAREFA,
      codigo_tarefa: "ZZT4504",
      planos_count: 1,
      planos: [{ ...PLANO_001, programa: "010", plano_hash: "h-010-1", plano_hashes_aguardando: ["h-010-1"], ops: [{ codigo_op: "1079689C010", produto_codigo: "PNT010", produto_descricao: "PRODUTO D", quantidade: 1 }], chapas: [{ ...PLANO_001.chapas[0], plano_hash: "h-010-1", programa: "010" }] }],
    };
    stubQueue([TAREFA, outra]);
    renderCorte();

    expect(await screen.findByRole("heading", { name: "ZZT4503" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "ZZT4504" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { expanded: true })).toHaveLength(2);
    expect(within(planoDe("010")).getByText("OP 1079689C010")).toBeInTheDocument();
  });

  it("informa carregamento, fila vazia e erro", async () => {
    stubQueue([]);
    const { unmount } = renderCorte();
    expect(screen.getByText("Carregando fila do Corte…")).toBeInTheDocument();
    expect(await screen.findByText("Nenhum plano na fila")).toBeInTheDocument();
    unmount();

    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes("/operator/stop-reasons")) return json({ items: [] });
      return json({ code: "cutting_unavailable", message: "Fila indisponível." }, 500);
    }));
    renderCorte();
    expect(await screen.findByText("Fila indisponível.")).toBeInTheDocument();
  });

  it("recarrega a fila depois de atualizar as tarefas", async () => {
    const fetchMock = stubQueue([TAREFA], (path, init) => {
      if (path.includes("/cutting/sync") && init?.method === "POST") {
        return json({ ok: true, message: "1 nova(s)", sync: {} });
      }
      return null;
    });
    renderCorte();

    await screen.findByRole("heading", { name: "ZZT4503" });
    const antes = fetchMock.mock.calls.filter(([path]) => String(path).includes("/cutting/queue")).length;
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Atualizar tarefas" })); });

    await waitFor(() => expect(
      fetchMock.mock.calls.filter(([path]) => String(path).includes("/cutting/queue")).length,
    ).toBeGreaterThan(antes));
    expect(await screen.findByText(/1 nova\(s\)/)).toBeInTheDocument();
  });

  it("deriva os planos quando a resposta ainda não traz a hierarquia", async () => {
    stubQueue([{
      codigo_tarefa: "ZZT-ANTIGA",
      plano_hash: "h-legado",
      status: "Aguardando",
      nesting_count: 2,
      nestings: [
        { plano_hash: "h-legado", sequencia: 1, programa: "700", status: "Aguardando", tempo_previsto_segundos: 60, tempo_real_segundos: null },
        { plano_hash: "h-legado-2", sequencia: 2, programa: "701", status: "Aguardando", tempo_previsto_segundos: 90, tempo_real_segundos: null },
      ],
    }]);
    renderCorte();

    await screen.findByRole("heading", { name: "ZZT-ANTIGA" });
    expect(within(planoDe("700")).getByText("Nenhuma OP vinculada a este plano.")).toBeInTheDocument();
    expect(planoDe("701")).toBeInTheDocument();
  });
});
