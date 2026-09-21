import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { QualityPage } from "../pages/operator/QualityPage";
import { AuthProvider } from "../auth/AuthContext";

// Dublê do canal realtime: é ele que dispara as recargas em segundo plano.
class MockEventSource {
  static instance: MockEventSource | null = null;
  private listeners = new Map<string, EventListener>();
  constructor(_url: string | URL, _options?: EventSourceInit) {
    MockEventSource.instance = this;
  }
  addEventListener(type: string, listener: EventListener) {
    this.listeners.set(type, listener);
  }
  emit(type: string, payload?: Record<string, unknown>) {
    const event = payload ? new MessageEvent(type, { data: JSON.stringify(payload) }) : new Event(type);
    this.listeners.get(type)?.(event);
  }
  close() {}
}

afterEach(() => {
  MockEventSource.instance = null;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

const OPERATOR_SESSION = {
  id: 3,
  name: "Inspetor Teste",
  role: "operador_dobra",
  management_access: false,
  operator_access: true,
  operator_sector: "Dobra",
  operator_resources: ["1303"],
};

const QUEUE_ITEM = {
  op: "00615903001",
  operacao: "20",
  descricao: "CHAPA FECHAMENTO PALHA 8",
  produto: "IPCX04014041P",
  recurso: "INSPEC",
  recurso_nome: "Inspeção",
  quantidade: 15,
  quantidade_planejada: 15,
  quantidade_aprovada: 0,
  inspecionadas: 0,
  pendentes: 15,
  data: "2026-09-03T13:00:00",
  inspecao_id: null,
  em_andamento: false,
};

const TEMPLATE = {
  id: 9,
  produto: "IPCX04014041P",
  revisao: 1,
  atualizado_por: "Supervisor",
  atualizado_em: "2026-09-01T08:00:00",
  cotas: [
    { id: 1, sequencia: 1, descricao: "Comprimento", padrao: "125,0 ± 0,5", unidade: "mm" },
    { id: 2, sequencia: 2, descricao: null, padrao: "80,0 ± 0,5", unidade: "mm" },
  ],
};

function inspection(overrides: Record<string, unknown> = {}) {
  return {
    id: 42,
    op: "00615903001",
    operacao: "20",
    produto: "IPCX04014041P",
    produto_descricao: "CHAPA FECHAMENTO PALHA 8",
    recurso: "INSPEC",
    quantidade_total: 15,
    pecas_registradas: 2,
    peca_atual: 3,
    ultima_peca: false,
    status: "EM_INSPECAO",
    operador: "Inspetor Teste",
    template: TEMPLATE,
    template_editavel: false,
    desenho: {
      id: 1,
      produto: "IPCX04014041P",
      filename: "CHAPA_FECHAMENTO_PALHA_8.pdf",
      versao: 1,
      size_bytes: 12345,
      enviado_em: "2026-09-01T08:00:00",
      enviado_por: "Supervisor",
    },
    pecas: [],
    ...overrides,
  };
}

interface BackendOptions {
  qualityAvailable?: boolean;
  queue?: unknown[];
  busca?: unknown;
  inspectionState?: Record<string, unknown>;
  onPiece?: (body: Record<string, unknown>) => Response;
}

function backend(options: BackendOptions = {}) {
  const calls: { path: string; method: string; body: unknown }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({ path, method, body });
    if (path.includes("/auth/session")) return json(OPERATOR_SESSION);
    if (path.includes("/operator/context")) {
      return json({ sector: "Dobra", route: "Dobra", resources: ["1303"], automatic_queue: false, workflow: "workbench" });
    }
    if (path.includes("/quality/context")) {
      return json({
        available: options.qualityAvailable ?? true,
        sector: (options.qualityAvailable ?? true) ? "Dobra" : null,
        resources: ["1303"],
        can_edit_template: false,
      });
    }
    if (path.includes("/quality/queue")) {
      return json({
        sector: "Dobra",
        items: options.queue ?? [QUEUE_ITEM],
        resumo: { aguardando: 12, aprovadas: 56, retrabalho: 8, refugo: 3 },
        recursos: ["INSPEC"],
        busca: options.busca ?? null,
      });
    }
    if (path.includes("/quality/inspections") && path.endsWith("/pieces") && method === "POST") {
      return options.onPiece ? options.onPiece(body) : json({ ok: true, message: "Peça 3 de 15 registrada.", code: "", data: inspection({ pecas_registradas: 3, peca_atual: 4 }) });
    }
    if (path.match(/\/quality\/inspections$/) && method === "POST") {
      return json({ ok: true, message: "Inspeção aberta.", code: "", data: inspection(options.inspectionState) });
    }
    if (path.includes("/quality/inspections/")) return json(inspection(options.inspectionState));
    if (path.includes("/operator/operators")) return json({ items: [{ cracha: "77", nome: "Inspetor", ativo: true }] });
    if (path.includes("/operator/workbench")) return json({ sector: "Dobra", resource: "1303", queue: [], production: [] });
    if (path.includes("/operator/history")) return json({ sector: "Dobra", resource: "1303", items: [], page: 1, page_size: 100, has_more: false });
    if (path.includes("/operator/stop-reasons")) return json({ items: [] });
    if (path.includes("/system/health")) return json({ status: "ok" });
    return json({ code: "not_found", message: "Não encontrado" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, calls };
}

function renderOperator() {
  render(<MemoryRouter initialEntries={["/operador"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
}

/**
 * Wave 6B — o posto não tem mais aba Qualidade: a entrada do operador é o
 * popup Setup/Qualidade do botão Iniciar. A inspeção dimensional da operação
 * ``INSPECAO`` continua existindo no backend e nesta tela, que é montada
 * diretamente aqui enquanto o ponto de entrada dela não for redefinido.
 */
async function openQuality() {
  render(
    <MemoryRouter initialEntries={["/operador"]}>
      <AuthProvider><QualityPage sector="Dobra" /></AuthProvider>
    </MemoryRouter>,
  );
  return screen.findByLabelText("Buscar OP, produto ou data");
}

describe("aba Qualidade do operador", () => {
  it("não existe mais no posto: o operador entra pelo Iniciar", async () => {
    backend();
    renderOperator();
    await screen.findByRole("heading", { name: "Dobra - 1303" });
    expect(screen.queryByRole("button", { name: "Qualidade" })).not.toBeInTheDocument();
    // O Setup continua sendo botão do posto: ele aponta o tempo de preparação.
    expect(screen.getByRole("button", { name: "Setup" })).toBeInTheDocument();
  });

  it("lista a fila com os quatro indicadores e abre a inspeção pela ação da linha", async () => {
    const { calls } = backend();
    await openQuality();

    expect(await screen.findByText("Aguardando inspeção")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("56")).toBeInTheDocument();

    const row = screen.getByRole("row", { name: /00615903001/ });
    expect(within(row).getByText("IPCX04014041P")).toBeInTheDocument();
    expect(within(row).getByText("15")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Inspecionar OP 00615903001" }));
    await screen.findByRole("heading", { name: "Checklist de cotas" });
    const abertura = calls.find((call) => call.method === "POST" && call.path.endsWith("/quality/inspections"));
    expect(abertura?.body).toEqual({ op: "00615903001" });
    // A tela da Qualidade nunca aciona a busca sob demanda de OP.
    expect(calls.some((call) => call.path.includes("/operations/") && call.path.includes("/sync"))).toBe(false);
  });

  it("mostra a explicação local quando a pesquisa não encontra a OP", async () => {
    backend({ queue: [], busca: { codigo: "qualidade_op_nao_aguardando", message: "OP ainda não está aguardando inspeção." } });
    await openQuality();
    fireEvent.change(await screen.findByLabelText("Buscar OP, produto ou data"), { target: { value: "00615903001" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar" }));
    expect(await screen.findByText("OP ainda não está aguardando inspeção.")).toBeInTheDocument();
  });
});

describe("apontamento peça a peça", () => {
  async function openInspection(
    options: BackendOptions = {},
    titulo = "Checklist de cotas",
  ) {
    const context = backend(options);
    await openQuality();
    fireEvent.click(await screen.findByRole("button", { name: "Inspecionar OP 00615903001" }));
    // Cada cenário espera o título que realmente pertence a ele: produto sem
    // template abre o cadastro de cotas, não o checklist.
    await screen.findByRole("heading", { name: titulo });
    return context;
  }

  it("apresenta OP, produto, progresso, cotas do template e o PDF embutido", async () => {
    await openInspection();
    expect(screen.getByText("00615903001")).toBeInTheDocument();
    expect(screen.getByText("CHAPA FECHAMENTO PALHA 8")).toBeInTheDocument();
    expect(screen.getByText("Peça 3 de 15")).toBeInTheDocument();
    expect(screen.getByText("125,0 ± 0,5 mm")).toBeInTheDocument();
    expect(screen.getByLabelText("Medida da cota 1")).toBeInTheDocument();

    const viewer = document.querySelector(".insp-drawing__viewer");
    expect(viewer).toHaveAttribute("type", "application/pdf");
    expect(viewer?.getAttribute("data")).toContain("/api/v1/quality/drawings/IPCX04014041P/file");
  });

  it("informa a ausência de desenho sem bloquear a inspeção", async () => {
    await openInspection({ inspectionState: { desenho: null } });
    expect(screen.getByText("Nenhum desenho/PDF disponível para este produto.")).toBeInTheDocument();
    expect(screen.getByLabelText("Medida da cota 1")).toBeInTheDocument();
  });

  it("mantém a RNC desabilitada com todas as cotas conformes e a habilita na não conformidade", async () => {
    await openInspection();
    const rnc = screen.getByRole("button", { name: "Abrir RNC" });
    expect(rnc).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Medida da cota 1"), { target: { value: "124,9" } });
    fireEvent.change(screen.getByLabelText("Status da cota 1"), { target: { value: "CONFORME" } });
    fireEvent.change(screen.getByLabelText("Medida da cota 2"), { target: { value: "80,1" } });
    fireEvent.change(screen.getByLabelText("Status da cota 2"), { target: { value: "CONFORME" } });
    expect(screen.getByRole("button", { name: "Abrir RNC" })).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Status da cota 2"), { target: { value: "NAO_CONFORME" } });
    expect(screen.getByRole("button", { name: "Abrir RNC" })).toBeEnabled();
    // Não conformidade impede a aprovação da peça.
    expect(screen.getByRole("button", { name: "Aprovada" })).toBeDisabled();
  });

  it("salva a peça com medidas, resultado e RNC e avança para a próxima", async () => {
    const { calls } = await openInspection();
    fireEvent.change(screen.getByLabelText("Medida da cota 1"), { target: { value: "124,9" } });
    fireEvent.change(screen.getByLabelText("Status da cota 1"), { target: { value: "CONFORME" } });
    fireEvent.change(screen.getByLabelText("Medida da cota 2"), { target: { value: "89,8" } });
    fireEvent.change(screen.getByLabelText("Status da cota 2"), { target: { value: "NAO_CONFORME" } });

    const salvar = screen.getByRole("button", { name: "Salvar e próxima peça" });
    expect(salvar).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Abrir RNC" }));
    fireEvent.change(await screen.findByLabelText("Motivo / descrição da não conformidade"), {
      target: { value: "Esquadro lateral fora do padrão" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Registrar RNC" }));

    fireEvent.click(await screen.findByRole("button", { name: "Retrabalho" }));
    fireEvent.click(screen.getByRole("button", { name: "Salvar e próxima peça" }));

    await waitFor(() => {
      expect(calls.some((call) => call.method === "POST" && call.path.endsWith("/pieces"))).toBe(true);
    });
    const enviado = calls.find((call) => call.method === "POST" && call.path.endsWith("/pieces"));
    expect(enviado?.body).toMatchObject({
      numero_peca: 3,
      resultado: "RETRABALHO",
      medidas: [
        { sequencia: 1, medida: "124,9", status: "CONFORME" },
        { sequencia: 2, medida: "89,8", status: "NAO_CONFORME" },
      ],
      rnc: { motivo: "Esquadro lateral fora do padrão" },
    });
  });

  it("na última peça pede o crachá e finaliza a inspeção", async () => {
    const { calls } = await openInspection({
      inspectionState: { quantidade_total: 3, pecas_registradas: 2, peca_atual: 3, ultima_peca: true },
      onPiece: () => json({ ok: true, message: "Inspeção concluída: 3 aprovada(s).", code: "inspecao_concluida", data: {} }),
    });
    fireEvent.change(screen.getByLabelText("Medida da cota 1"), { target: { value: "124,9" } });
    fireEvent.change(screen.getByLabelText("Status da cota 1"), { target: { value: "CONFORME" } });
    fireEvent.change(screen.getByLabelText("Medida da cota 2"), { target: { value: "80,1" } });
    fireEvent.change(screen.getByLabelText("Status da cota 2"), { target: { value: "CONFORME" } });
    fireEvent.click(screen.getByRole("button", { name: "Aprovada" }));

    fireEvent.click(screen.getByRole("button", { name: "Finalizar inspeção" }));
    fireEvent.change(await screen.findByLabelText("Crachá do operador"), { target: { value: "77" } });
    fireEvent.click(screen.getByRole("button", { name: "Adicionar operador" }));
    fireEvent.click(await screen.findByRole("button", { name: "Concluir inspeção" }));

    await screen.findByText("Inspeção concluída: 3 aprovada(s).");
    const enviado = calls.find((call) => call.method === "POST" && call.path.endsWith("/pieces"));
    expect(enviado?.body).toMatchObject({ numero_peca: 3, badges: ["77"] });
  });

  it("apresenta o cadastro das cotas quando o produto ainda não possui template", async () => {
    const { calls } = await openInspection(
      { inspectionState: { template: null, template_editavel: true } },
      "Cadastro das cotas do produto",
    );
    // Sem template o checklist vazio nunca chega a aparecer.
    expect(screen.queryByRole("heading", { name: "Checklist de cotas" })).not.toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Cota 1" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Cota 2" })).not.toBeInTheDocument();
    expect(screen.getByText("mm", { selector: ".insp-fixed-unit strong" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /unidade/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: /unidade/i })).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Padrão nominal da cota 1"), { target: { value: "125,0" } });
    fireEvent.change(screen.getByLabelText("Tolerância da cota 1"), { target: { value: "0,5" } });
    fireEvent.click(screen.getByRole("button", { name: "+ Adicionar cota" }));
    fireEvent.change(screen.getByLabelText("Padrão nominal da cota 2"), { target: { value: "80,0" } });
    fireEvent.change(screen.getByLabelText("Tolerância da cota 2"), { target: { value: "0,5" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar cotas do produto" }));

    await waitFor(() => {
      expect(calls.some((call) => call.method === "POST" && call.path.endsWith("/quality/templates"))).toBe(true);
    });
    const enviado = calls.find((call) => call.method === "POST" && call.path.endsWith("/quality/templates"));
    expect(enviado?.body).toMatchObject({
      produto: "IPCX04014041P",
      cotas: [
        { sequencia: 1, padrao: "125,0 ± 0,5" },
        { sequencia: 2, padrao: "80,0 ± 0,5" },
      ],
    });
  });

  it("nunca apaga o que o operador digitou, por mais recargas que ocorram", async () => {
    // Regressão: o checklist era zerado a cada recarga em segundo plano.
    // O que o operador digitou só pode ser limpo por ação dele.
    vi.stubGlobal("EventSource", MockEventSource);
    await openInspection();

    fireEvent.change(screen.getByLabelText("Medida da cota 1"), { target: { value: "124,9" } });
    fireEvent.change(screen.getByLabelText("Status da cota 1"), { target: { value: "CONFORME" } });
    fireEvent.click(screen.getByRole("button", { name: "Retrabalho" }));

    // Rajada de eventos: tick periódico e invalidações reais, várias vezes.
    for (let volta = 0; volta < 5; volta += 1) {
      act(() => MockEventSource.instance?.emit("refresh", { topic: "live_tick" }));
      act(() => MockEventSource.instance?.emit("refresh", { topic: "quality_piece_registered" }));
      act(() => MockEventSource.instance?.emit("refresh", {}));
    }

    await waitFor(() => {
      expect(screen.getByLabelText("Medida da cota 1")).toHaveValue("124,9");
    });
    expect(screen.getByLabelText("Status da cota 1")).toHaveValue("CONFORME");
    expect(screen.getByRole("button", { name: "Retrabalho" })).toHaveAttribute("aria-pressed", "true");

    // Digitar depois da rajada também permanece.
    fireEvent.change(screen.getByLabelText("Medida da cota 2"), { target: { value: "80,1" } });
    act(() => MockEventSource.instance?.emit("refresh", { topic: "live_tick" }));
    await waitFor(() => {
      expect(screen.getByLabelText("Medida da cota 2")).toHaveValue("80,1");
    });
  });

  it("limpa o checklist somente depois que a peça é gravada", async () => {
    await openInspection();
    fireEvent.change(screen.getByLabelText("Medida da cota 1"), { target: { value: "124,9" } });
    fireEvent.change(screen.getByLabelText("Status da cota 1"), { target: { value: "CONFORME" } });
    fireEvent.change(screen.getByLabelText("Medida da cota 2"), { target: { value: "80,1" } });
    fireEvent.change(screen.getByLabelText("Status da cota 2"), { target: { value: "CONFORME" } });
    fireEvent.click(screen.getByRole("button", { name: "Aprovada" }));
    fireEvent.click(screen.getByRole("button", { name: "Salvar e próxima peça" }));

    await waitFor(() => {
      expect(screen.getByLabelText("Medida da cota 1")).toHaveValue("");
    });
    expect(screen.getByLabelText("Medida da cota 2")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Aprovada" })).toHaveAttribute("aria-pressed", "false");
  });

  it("mostra o template como somente leitura para o operador comum", async () => {
    await openInspection();
    expect(screen.getByText(/alterar o padrão é atribuição de Supervisor ou Líder/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "+ Adicionar cota" })).not.toBeInTheDocument();
    expect(screen.getByText("125,0 ± 0,5 mm")).toBeInTheDocument();
  });
});

describe("regra transitória da inspeção (Wave 3)", () => {
  it("permite seguir sem inspeção deixando claro que nada de qualidade é registrado", async () => {
    const fila = {
      items: [{ op: "OP-500", operacao: "20", descricao: "Suporte", produto: "PECA-500", recurso: "DOBRA1", recurso_nome: "Gasparini", quantidade: 6, inspecionadas: 0, pendentes: 6, quantidade_planejada: 6, quantidade_aprovada: 0, data: null, inspecao_id: null, em_andamento: false }],
      resumo: { aguardando: 6, aprovadas: 0, retrabalho: 0, refugo: 0 },
      recursos: ["DOBRA1"],
      busca: null,
      sector: "Dobra",
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json({ id: 31, name: "Operador Dobra", role: "operador_dobra", management_access: false, operator_access: true, operator_sector: "Dobra", operator_resources: ["Gasparini"] });
      if (path.includes("/operator/context")) return json({ sector: "Dobra", route: "Dobra", resources: ["Gasparini"], automatic_queue: false, workflow: "workbench" });
      if (path.includes("/quality/context")) return json({ available: true, sector: "Dobra", resources: ["DOBRA1"], can_edit_template: false });
      if (path.includes("/operator/workbench")) return json({ sector: "Dobra", resource: "Gasparini", queue: [], production: [] });
      if (path.includes("/operator/history")) return json({ items: [], has_more: false });
      if (path.includes("/operator/stop-reasons") || path.includes("/operator/operators")) return json({ items: [] });
      if (path.includes("/system/health")) return json({ status: "ok" });
      if (path.includes("/quality/inspections/bypass") && init?.method === "POST") {
        return json({ ok: true, message: "Inspeção dispensada. A OP segue para a próxima etapa.", code: "qualidade_inspecao_dispensada" });
      }
      if (path.includes("/quality/queue")) return json(fila);
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter initialEntries={["/operador"]}>
        <AuthProvider><QualityPage sector="Dobra" /></AuthProvider>
      </MemoryRouter>,
    );
    expect(await screen.findByText("OP-500")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Seguir sem inspeção na OP OP-500" }));
    await screen.findByRole("heading", { name: "Seguir sem inspeção" });
    // O operador precisa ver que nada de qualidade será inventado.
    expect(screen.getByText(/Nenhuma peça será aprovada/)).toBeInTheDocument();

    const confirmar = screen.getByRole("button", { name: "Confirmar e seguir" });
    expect(confirmar).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Crachá de quem autoriza"), { target: { value: "9001" } });
    fireEvent.change(screen.getByLabelText("Motivo (opcional)"), { target: { value: "Operador treinado" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirmar e seguir" }));

    await screen.findByText("Inspeção dispensada. A OP segue para a próxima etapa.");
    const chamada = fetchMock.mock.calls.find(([path, init]) => String(path).includes("/quality/inspections/bypass") && init?.method === "POST");
    expect(JSON.parse(String(chamada?.[1]?.body))).toMatchObject({ op: "OP-500", badges: ["9001"], motivo: "Operador treinado" });
  });
});
