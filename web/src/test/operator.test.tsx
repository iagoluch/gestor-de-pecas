import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";

class SseStub {
  static instance: SseStub | null = null;
  private listeners = new Map<string, EventListener>();
  constructor(_url: string | URL, _options?: EventSourceInit) { SseStub.instance = this; }
  addEventListener(type: string, listener: EventListener) { this.listeners.set(type, listener); }
  emit(topic: string) { this.listeners.get("refresh")?.(new MessageEvent("refresh", { data: JSON.stringify({ topic }) })); }
  close() {}
}

afterEach(() => {
  SseStub.instance = null;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

describe("fluxo Web do operador", () => {
  it("encerra a sessão do operador e volta ao login", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json({ id: 2, name: "Operador Teste", role: "operador_dobra", management_access: false, operator_access: true, operator_sector: "Dobra", operator_resources: ["1303"] });
      if (path.includes("/operator/context")) return json({ sector: "Dobra", route: "Dobra", resources: ["1303"], automatic_queue: false, workflow: "workbench" });
      if (path.includes("/operator/stop-reasons") || path.includes("/operator/operators")) return json({ items: [] });
      if (path.includes("/operator/history")) return json({ items: [], has_more: false });
      if (path.includes("/operator/workbench")) return json({ sector: "Dobra", resource: "1303", queue: [], production: [] });
      if (path.includes("/auth/logout") && init?.method === "POST") return new Response(null, { status: 204 });
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter initialEntries={["/operador"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    // Posto com recurso único não pede escolha: o operador entra direto na
    // bancada do próprio recurso.
    await screen.findByRole("heading", { name: "Dobra - 1303" });
    expect(screen.queryByRole("heading", { name: "Selecione o recurso" })).not.toBeInTheDocument();
    expect(document.querySelector(".operator-profile > i")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sair" }));
    await screen.findByRole("heading", { name: "Entrar no Gestor" });
    expect(fetchMock.mock.calls.some(([path, init]) => String(path).includes("/auth/logout") && init?.method === "POST")).toBe(true);
  });

  it("restringe a navegação ao setor autenticado e envia somente a operação selecionada", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json({ id: 2, name: "Operador Teste", role: "operador_dobra", management_access: false, operator_access: true, operator_sector: "Dobra", operator_resources: ["1303", "2204", "Gasparini"] });
      if (path.includes("/operator/context")) return json({ sector: "Dobra", route: "Dobra", resources: ["1303", "2204", "Gasparini"], automatic_queue: false, workflow: "workbench" });
      if (path.includes("/system/health")) return json({ status: "ok" });
      if (path.includes("/operator/stop-reasons")) return json({ items: [{ codigo: "0029", nome: "Quebra de ferramenta" }, { codigo: "0030", nome: "Falta de material" }] });
      if (path.includes("/operator/history")) return json({ sector: "Dobra", resource: "1303", page: 1, page_size: 100, has_more: false, items: [{ id: 90, op: "OP-090", status: "Finalizado", operation: "10 - DOBRA", product: "PEÇA-90", qty: 2, good: 2, scrap: 0 }] });
      if (path.includes("/operator/workbench")) return json({ sector: "Dobra", resource: "1303", queue: [], production: [{ id: 91, op: "OP-091", status: "Parada", operation: "20 - DOBRA", product: "PEÇA-91", qty: 4, good: 0, scrap: 0, motivo_parada: "0029 - Quebra de ferramenta", stopped_since: "2026-08-20T10:00:00", status_elapsed: "00:03:21" }] });
      if (path.includes("/operator/operations/OP-101")) return json({ items: [{ id: 101, numero_operacao: "20", descricao_operacao: "DOBRA", visual_status: "current", visual_current: true }] });
      if (path.includes("/operator/actions") && init?.method === "POST") return json({ ok: true, message: "Início registrado com sucesso.", data: { status: "Em processo" } });
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter initialEntries={["/operador"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    await screen.findByRole("heading", { name: "Selecione o recurso" });
    expect(screen.getByText("Dobra", { selector: ".operator-sector-link strong" })).toBeInTheDocument();
    expect(screen.queryByText("Management View — Visão Geral")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "1303" }));
    await screen.findByRole("heading", { name: "Dobra - 1303" });
    expect(await screen.findByRole("heading", { name: "Histórico" })).toBeInTheDocument();
    expect(screen.getByText("Tempo parado: 00:03:21")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Ver mais" })).toHaveLength(3);
    fireEvent.change(screen.getByLabelText("Código da OP"), { target: { value: "OP-101" } });
    fireEvent.click(screen.getByRole("button", { name: "Carregar roteiro" }));
    await screen.findByRole("button", { name: "20 - DOBRA — Atual" });
    await screen.findByText("OP encontrada. Etapa atual: 20 - DOBRA.");
    // A parada pertence ao apontamento ativo do recurso. Com ele já em Parada,
    // o caminho é Retomar: registrar uma segunda parada é recusado pelo
    // backend (`recurso_ja_parado`) e a tela não oferece a ação.
    expect(screen.getByRole("button", { name: "Parada" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Iniciar" }));
    await screen.findByText("Início registrado com sucesso.");
    const actionCall = fetchMock.mock.calls.find(([path, init]) => String(path).includes("/operator/actions") && init?.method === "POST");
    expect(actionCall).toBeTruthy();
    expect(JSON.parse(String(actionCall?.[1]?.body))).toMatchObject({ action: "Início", resource: "1303", op: "OP-101", operation_id: 101 });
  });

  it("habilita qualquer etapa apontável do Workbench, inclusive inspeção, e mantém o marco terminal fora do seletor", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json({ id: 2, name: "Operador", role: "operador_dobra", management_access: false, operator_access: true, operator_sector: "Dobra", operator_resources: ["Gasparini"] });
      if (path.includes("/operator/context")) return json({ sector: "Dobra", route: "Dobra", resources: ["Gasparini"], automatic_queue: false, workflow: "workbench" });
      if (path.includes("/system/health")) return json({ status: "ok" });
      if (path.includes("/operator/stop-reasons") || path.includes("/operator/operators")) return json({ items: [] });
      if (path.includes("/operator/history")) return json({ items: [], has_more: false });
      if (path.includes("/operator/workbench")) return json({ queue: [], production: [] });
      if (path.includes("/operator/operations/OP-ROTA")) return json({ items: [
        { id: 1, numero_operacao: "10", descricao_operacao: "CORTE", visual_status: "current", visual_current: true, actionable: false, selectable: true, requires_confirmation: false },
        { id: 2, numero_operacao: "20", descricao_operacao: "DOBRA", visual_status: "pending", actionable: false, selectable: true, requires_confirmation: true },
        { id: 3, numero_operacao: "30", descricao_operacao: "USINAGEM", visual_status: "pending", actionable: false, selectable: true, requires_confirmation: true },
        { id: 4, numero_operacao: "40", descricao_operacao: "INSPECAO", visual_status: "pending", actionable: false, selectable: true, requires_confirmation: true },
        // O marco terminal é leitura do roteiro: o backend nunca o devolve
        // selecionável, e por isso ele não pode virar destino de apontamento.
        { id: 5, numero_operacao: "99", descricao_operacao: "FINALIZADA", visual_status: "pending", actionable: false, selectable: false, requires_confirmation: false },
      ] });
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = render(<MemoryRouter initialEntries={["/operador"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    await screen.findByRole("heading", { name: "Dobra - Gasparini" });
    fireEvent.change(screen.getByLabelText("Código da OP"), { target: { value: "OP-ROTA" } });
    fireEvent.click(screen.getByRole("button", { name: "Carregar roteiro" }));

    expect(await screen.findByText("OP encontrada. Etapa atual: 10 - CORTE. Ainda não disponível para Dobra.")).toBeInTheDocument();
    // O dropdown de operação foi removido: os cards do roteiro são o seletor.
    expect(container.querySelector(".operator-operation-field")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Operação")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "10 - CORTE — Atual" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "20 - DOBRA — Próxima" })).not.toBeDisabled();
    expect(screen.getByRole("button", { name: "30 - USINAGEM — Próxima" })).not.toBeDisabled();
    expect(screen.getByRole("button", { name: "40 - INSPECAO — Próxima" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "99 - FINALIZADA — Próxima" })).toBeDisabled();
    expect(container.querySelectorAll(".operator-route__item--current")).toHaveLength(1);
    expect(container.querySelectorAll(".operator-route__item--done")).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Iniciar" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Finalizar" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Setup" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Retrabalho" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Parada" })).not.toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "20 - DOBRA — Próxima" }));
    await screen.findByRole("heading", { name: "Confirmar operação" });
    const confirmation = screen.getByRole("dialog");
    expect(within(confirmation).getByText("10 - CORTE")).toBeInTheDocument();
    expect(within(confirmation).getByText("20 - DOBRA")).toBeInTheDocument();
    fireEvent.click(within(confirmation).getByRole("button", { name: "Cancelar" }));

    fireEvent.click(screen.getByRole("button", { name: "40 - INSPECAO — Próxima" }));
    expect(within(await screen.findByRole("dialog")).getByText("40 - INSPECAO")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));

    // O marco terminal não abre confirmação nenhuma: não há etapa para apontar.
    fireEvent.click(screen.getByRole("button", { name: "99 - FINALIZADA — Próxima" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("pede confirmação para apontar etapa diferente da atual e preserva a atual ao cancelar", async () => {
    const roteiro = [
      { id: 1, numero_operacao: "10", descricao_operacao: "CORTE", visual_status: "done", selectable: false, actionable: false, requires_confirmation: false },
      { id: 2, numero_operacao: "20", descricao_operacao: "DOBRA", visual_status: "current", visual_current: true, selectable: true, actionable: true, requires_confirmation: false },
      { id: 3, numero_operacao: "30", descricao_operacao: "DOBRA ESPECIAL", visual_status: "pending", selectable: true, actionable: false, requires_confirmation: true },
      { id: 4, numero_operacao: "40", descricao_operacao: "PINTURA", visual_status: "pending", selectable: true, actionable: false, requires_confirmation: true },
    ];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json({ id: 11, name: "Operador", role: "operador_dobra", management_access: false, operator_access: true, operator_sector: "Dobra", operator_resources: ["Gasparini"] });
      if (path.includes("/operator/context")) return json({ sector: "Dobra", route: "Dobra", resources: ["Gasparini"], automatic_queue: false, workflow: "workbench" });
      if (path.includes("/operator/stop-reasons") || path.includes("/operator/operators")) return json({ items: [] });
      if (path.includes("/operator/history")) return json({ items: [], has_more: false });
      if (path.includes("/operator/workbench")) return json({ queue: [], production: [] });
      if (path.includes("/operator/operations/OP-OVERRIDE")) return json({ items: roteiro });
      if (path.includes("/operator/actions") && init?.method === "POST") return json({ ok: true, message: "Início registrado com sucesso.", data: {} });
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("EventSource", SseStub);

    const { container } = render(<MemoryRouter initialEntries={["/operador"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    await screen.findByRole("heading", { name: "Dobra - Gasparini" });
    fireEvent.change(screen.getByLabelText("Código da OP"), { target: { value: "OP-OVERRIDE" } });
    fireEvent.click(screen.getByRole("button", { name: "Carregar roteiro" }));

    // Etapa atual selecionada por padrão, com as cores semânticas preservadas.
    await screen.findByRole("button", { name: "20 - DOBRA — Atual" });
    expect(container.querySelectorAll(".operator-route__item--done")).toHaveLength(1);
    expect(container.querySelectorAll(".operator-route__item--current")).toHaveLength(1);
    expect(container.querySelectorAll(".operator-route__item--selected")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "20 - DOBRA — Atual" })).toHaveAttribute("aria-pressed", "true");
    // Somente a etapa concluída permanece bloqueada; qualquer etapa
    // operacional aberta do roteiro pode ser selecionada com confirmação.
    expect(screen.getByRole("button", { name: "10 - CORTE — Concluída" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "40 - PINTURA — Próxima" })).toBeEnabled();

    // Selecionar outra etapa permitida abre a confirmação, sem nenhum evento.
    fireEvent.click(screen.getByRole("button", { name: "30 - DOBRA ESPECIAL — Próxima" }));
    await screen.findByRole("heading", { name: "Confirmar operação" });
    const confirmacao = within(container.querySelector(".operator-route-confirm") as HTMLElement);
    expect(confirmacao.getByText("OP-OVERRIDE")).toBeInTheDocument();
    expect(confirmacao.getByText("20 - DOBRA")).toBeInTheDocument();
    expect(confirmacao.getByText("30 - DOBRA ESPECIAL")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([path, init]) => String(path).includes("/operator/actions") && init?.method === "POST")).toBe(false);

    // Cancelar preserva a operação atual.
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Confirmar operação" })).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "20 - DOBRA — Atual" })).toHaveAttribute("aria-pressed", "true");

    // Confirmar troca a seleção e o apontamento segue a operação escolhida.
    fireEvent.click(screen.getByRole("button", { name: "30 - DOBRA ESPECIAL — Próxima" }));
    fireEvent.click(await screen.findByRole("button", { name: "Sim, apontar esta operação" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "30 - DOBRA ESPECIAL — Próxima" })).toHaveAttribute("aria-pressed", "true"));

    // O refresh em tempo real substitui o snapshot do roteiro, mas não pode
    // desfazer a escolha que o operador acabou de confirmar.
    const routeCallsBeforeRefresh = fetchMock.mock.calls.filter(([path]) => String(path).includes("/operator/operations/OP-OVERRIDE")).length;
    await act(async () => { SseStub.instance?.emit("operator_action"); });
    await waitFor(() => expect(fetchMock.mock.calls.filter(([path]) => String(path).includes("/operator/operations/OP-OVERRIDE")).length).toBeGreaterThan(routeCallsBeforeRefresh));
    expect(screen.getByRole("button", { name: "30 - DOBRA ESPECIAL — Próxima" })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "Iniciar" }));
    await screen.findByText("Início registrado com sucesso.");
    const call = fetchMock.mock.calls.find(([path, init]) => String(path).includes("/operator/actions") && init?.method === "POST");
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ action: "Início", op: "OP-OVERRIDE", operation_id: 3 });
  });

  it.each([
    ["Parada", "Retomar"],
    ["Setup", "Retornar"],
  ])("envia a ação contextual %s como %s", async (status, expectedAction) => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json({ id: 2, name: "Operador Teste", role: "operador_dobra", management_access: false, operator_access: true, operator_sector: "Dobra", operator_resources: ["1303"] });
      if (path.includes("/operator/context")) return json({ sector: "Dobra", route: "Dobra", resources: ["1303"], automatic_queue: false, workflow: "workbench" });
      if (path.includes("/operator/stop-reasons")) return json({ items: [] });
      if (path.includes("/operator/operators")) return json({ items: [] });
      if (path.includes("/operator/history")) return json({ items: [], has_more: false });
      if (path.includes("/operator/workbench")) return json({ sector: "Dobra", resource: "1303", queue: [], production: [{ id: 91, catalogo_operacao_id: 91, op: "OP-091", status, operation: "20 - DOBRA", product: "PEÇA-91", qty: 4, good: 0, scrap: 0 }] });
      if (path.includes("/operator/operations/OP-091")) return json({ items: [{ id: 91, numero_operacao: "20", descricao_operacao: "DOBRA", visual_status: "current", visual_current: true }] });
      if (path.includes("/operator/actions") && init?.method === "POST") return json({ ok: true, message: `${expectedAction} registrado com sucesso.`, data: { status: "Em processo" } });
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter initialEntries={["/operador"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    await screen.findByRole("heading", { name: "Dobra - 1303" });
    fireEvent.change(screen.getByLabelText("Código da OP"), { target: { value: "OP-091" } });
    fireEvent.click(screen.getByRole("button", { name: "Carregar roteiro" }));
    await screen.findByRole("button", { name: "20 - DOBRA — Atual" });
    fireEvent.click(await screen.findByRole("button", { name: expectedAction }));
    await screen.findByText(`${expectedAction} registrado com sucesso.`);

    const actionCall = fetchMock.mock.calls.find(([path, init]) => String(path).includes("/operator/actions") && init?.method === "POST");
    expect(JSON.parse(String(actionCall?.[1]?.body))).toMatchObject({ action: expectedAction, resource: "1303", op: "OP-091", operation_id: 91 });
  });

  it("exibe planejado e realizado individualmente para cada nesting do Corte", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json({ id: 3, name: "Operador Corte", role: "operador_corte", management_access: false, operator_access: true, operator_sector: "Corte" });
      if (path.includes("/operator/context")) return json({ sector: "Corte", route: "Corte", resources: ["Laser Ensis 3015"], automatic_queue: true, workflow: "cutting" });
      if (path.includes("/system/health")) return json({ status: "ok" });
      if (path.includes("/operator/stop-reasons")) return json({ items: [] });
      if (path.includes("/cutting/queue")) return json({ resource: "Laser Ensis 3015", resource_state: null, items: [{ codigo_tarefa: "T-CORTE", programa: "P-01, P-02", material: "AÇO", status: "Aguardando", nesting_count: 2, nestings_concluidos: 0, nestings_aguardando: 2, tempo_previsto_segundos: 300, nestings: [{ plano_hash: "a", sequencia: 1, programa: "P-01", status: "Aguardando", tempo_previsto_segundos: 120, tempo_real_segundos: null }, { plano_hash: "b", sequencia: 2, programa: "P-02", status: "Aguardando", tempo_previsto_segundos: 180, tempo_real_segundos: 45 }] }] });
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    }));

    render(<MemoryRouter initialEntries={["/operador"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    await screen.findByRole("heading", { name: "Corte - Laser Ensis 3015" });
    // A tarefa chega recolhida — expande para ver os planos.
    const toggle = (await screen.findByRole("heading", { name: "T-CORTE" })).closest("button");
    if (!toggle) throw new Error("toggle da tarefa T-CORTE não encontrado");
    fireEvent.click(toggle);
    // Cada nesting vive dentro do seu plano; o tempo continua individual.
    expect(await screen.findByText("P-01")).toBeInTheDocument();
    expect(screen.getByText("P-02")).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "00:02:00" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "00:00:45" })).toBeInTheDocument();
  });

  it("permite registrar parada sem OP carregada", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json({ id: 4, name: "Operador Dobra", role: "operador_dobra", management_access: false, operator_access: true, operator_sector: "Dobra" });
      if (path.includes("/operator/context")) return json({ sector: "Dobra", route: "Dobra", resources: ["1303"], automatic_queue: false, workflow: "workbench" });
      if (path.includes("/operator/stop-reasons")) return json({ items: [{ codigo: "0029", nome: "Quebra de ferramenta", grupo_codigo: "0004" }, { codigo: "0030", nome: "Falta de material", grupo_codigo: "0004" }] });
      if (path.includes("/operator/operators")) return json({ items: [] });
      if (path.includes("/operator/workbench")) return json({ sector: "Dobra", resource: "1303", queue: [], production: [] });
      if (path.includes("/operator/history")) return json({ items: [], has_more: false });
      if (path.includes("/operator/actions") && init?.method === "POST") return json({ ok: true, message: "Parada registrada com sucesso.", code: "parada_recurso_sem_op" });
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter initialEntries={["/operador"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    await screen.findByRole("heading", { name: "Dobra - 1303" });
    fireEvent.click(screen.getByRole("button", { name: "Parada" }));
    // A busca do motivo filtra a lista pelo texto digitado.
    fireEvent.change(screen.getByLabelText("Buscar motivo"), { target: { value: "quebra" } });
    expect(screen.getByRole("option", { name: "0029 - Quebra de ferramenta" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "0030 - Falta de material" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Buscar motivo"), { target: { value: "0029" } });
    await waitFor(() => expect(screen.getByRole("option", { name: "0029 - Quebra de ferramenta" })).toHaveAttribute("aria-selected", "true"));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar parada" }));
    await screen.findByText("Parada registrada com sucesso.");
    const call = fetchMock.mock.calls.find(([path, init]) => String(path).includes("/operator/actions") && init?.method === "POST");
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ action: "Parada", resource: "1303", op: null, operation_id: null });
  });

  it("retoma parada registrada sem OP carregada", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json({ id: 4, name: "Operador Dobra", role: "operador_dobra", management_access: false, operator_access: true, operator_sector: "Dobra" });
      if (path.includes("/operator/context")) return json({ sector: "Dobra", route: "Dobra", resources: ["1303"], automatic_queue: false, workflow: "workbench" });
      if (path.includes("/operator/stop-reasons") || path.includes("/operator/operators")) return json({ items: [] });
      if (path.includes("/operator/workbench")) {
        return json({
          sector: "Dobra",
          resource: "1303",
          resource_state: { categoria: "parada", motivo: "0029 - Quebra de ferramenta", op: null },
          queue: [],
          production: [],
        });
      }
      if (path.includes("/operator/history")) return json({ items: [], has_more: false });
      if (path.includes("/operator/actions") && init?.method === "POST") return json({ ok: true, message: "Recurso retomado com sucesso.", code: "retomada_recurso_sem_op" });
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter initialEntries={["/operador"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    await screen.findByRole("heading", { name: "Dobra - 1303" });
    await screen.findByText(/Recurso parado — 0029 - Quebra de ferramenta/);
    // Sem OP carregada não existe apontamento: a retomada é do próprio recurso.
    fireEvent.click(screen.getByRole("button", { name: "Retomar" }));
    await screen.findByText("Recurso retomado com sucesso.");
    const call = fetchMock.mock.calls.find(([path, init]) => String(path).includes("/operator/actions") && init?.method === "POST");
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ action: "Retomar", resource: "1303", op: null, operation_id: null });
  });

  // ------------------------------------------------------------------
  // Wave 6B — o portão Setup/Qualidade é a entrada do botão Iniciar.
  // ------------------------------------------------------------------
  function gateBackend(options: { liberado?: boolean; configuravel?: boolean; setupRegistrado?: boolean; recusaFinalizar?: boolean } = {}) {
    const calls: { path: string; method: string; body: unknown }[] = [];
    const gate = {
      aplicavel: true,
      liberado: Boolean(options.liberado),
      status: "PENDENTE",
      peca_produzida: false,
      setup_obrigatorio: true,
      setup_registrado: options.setupRegistrado ?? true,
      inspecao_concluida: false,
      bloqueio_ativo: false,
      gate_estruturado: true,
      code: "primeira_peca_gate_obrigatorio",
      message: "Aponte o Setup desta operação para conferir a primeira peça antes de finalizar.",
      pendencias: ["setup"],
    };
    let setupApontado = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      const corpo = init?.body ? JSON.parse(String(init.body)) : null;
      calls.push({ path, method, body: corpo });
      if (path.includes("/operator/actions") && method === "POST" && corpo?.action === "Setup") {
        setupApontado = true;
      }
      if (path.includes("/auth/session")) return json({ id: 7, name: "Operador Dobra", role: "operador_dobra", management_access: false, operator_access: true, operator_sector: "Dobra", operator_resources: ["1303"] });
      if (path.includes("/operator/context")) return json({ sector: "Dobra", route: "Dobra", resources: ["1303"], automatic_queue: false, workflow: "workbench" });
      if (path.includes("/system/health")) return json({ status: "ok" });
      if (path.includes("/operator/stop-reasons") || path.includes("/operator/operators")) return json({ items: [] });
      if (path.includes("/operator/history")) return json({ items: [], has_more: false });
      if (path.includes("/operator/workbench")) {
        // Depois do Setup o posto fica em Setup: é desse estado que a OP
        // retoma a produção com `Retornar`.
        const production = setupApontado
          ? [{ id: 1, op: "OP-GATE", status: "Setup", operation: "20 - DOBRA", catalogo_operacao_id: 42, qty: 10, good: 0, scrap: 0 }]
          : [];
        return json({ sector: "Dobra", resource: "1303", queue: [], production });
      }
      if (path.includes("/operator/drawings")) return json({ available: false, message: "Nenhum desenho disponível para esta peça." });
      if (path.includes("/operator/first-piece") && method === "POST") {
        return json({ ok: true, message: "Primeira peça aprovada. Lote liberado para produção.", code: "primeira_peca_conforme", data: { ...gate, liberado: true } });
      }
      if (path.includes("/operator/first-piece")) {
        return json({
          op: "OP-GATE",
          ...gate,
          registro: null,
          checklist: {
            produto: "PECA-GATE",
            configuravel: Boolean(options.configuravel),
            template: options.configuravel ? null : {
              id: 1,
              produto: "PECA-GATE",
              revisao: 1,
              atualizado_por: null,
              atualizado_em: null,
              cotas: [{ id: 11, sequencia: 1, descricao: "Altura", padrao: "12,0 +/- 0,2", unidade: "mm", referencia: 12, margem: 0.2, limite_inferior: 11.8, limite_superior: 12.2, conformidade_automatica: true }],
            },
          },
        });
      }
      if (path.includes("/operator/actions") && method === "POST") {
        const acao = String(JSON.parse(String(init?.body ?? "{}")).action ?? "");
        if (acao === "Setup") {
          return json({ ok: true, message: "Setup registrado com sucesso.", data: { id: 1, status: "Setup" } });
        }
        if (acao === "Retornar") {
          return json({ ok: true, message: "Retorno registrado com sucesso.", data: { id: 1, status: "Em processo" } });
        }
        return json({ ok: true, message: "Início registrado com sucesso.", data: { id: 1, status: "Em processo" } });
      }
      if (path.includes("/operator/operations/OP-GATE")) {
        return json({ items: [{
          id: 42,
          numero_operacao: "20",
          descricao_operacao: "DOBRA",
          visual_status: "current",
          visual_current: true,
          actionable: true,
          selectable: true,
          requires_confirmation: false,
          produto_codigo: "PECA-GATE",
          quantidade_planejada: 10,
          pode_finalizar: options.liberado ?? false,
          exige_gate_primeira_peca: !options.liberado,
          primeira_peca: gate,
        }] });
      }
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    return { calls };
  }

  async function abrirPortao(options: { configuravel?: boolean; setupRegistrado?: boolean } = {}) {
    const context = gateBackend(options);
    render(<MemoryRouter initialEntries={["/operador"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    await screen.findByRole("heading", { name: "Dobra - 1303" });
    fireEvent.change(screen.getByLabelText("Código da OP"), { target: { value: "OP-GATE" } });
    fireEvent.click(screen.getByRole("button", { name: "Carregar roteiro" }));
    await screen.findByRole("button", { name: "20 - DOBRA — Atual" });
    fireEvent.click(screen.getByRole("button", { name: "Setup" }));
    await screen.findByRole("heading", { name: "Setup e Qualidade" });
    // O conteúdo do popup chega do backend: espere o checklist (ou o cadastro
    // de cotas) antes de interagir.
    if (options.configuravel) {
      await screen.findByRole("heading", { name: "Cadastro das cotas do produto" });
    } else {
      await screen.findByLabelText("Medida da cota 1");
    }
    return context;
  }

  it("abre o Setup/Qualidade pelo botão Setup e não mostra card de primeira peça", async () => {
    const { calls } = await abrirPortao();

    expect(screen.queryByRole("heading", { name: "Primeira peça" })).not.toBeInTheDocument();
    expect(screen.getByText("12,0 +/- 0,2")).toBeInTheDocument();
    expect(screen.getByText("11.8 a 12.2 mm")).toBeInTheDocument();
    // O Setup continua sendo apontamento de estado: o tempo de preparação é
    // registrado e o checklist abre em seguida, no mesmo clique.
    const setup = calls.find((call) => call.method === "POST" && call.path.includes("/operator/actions"));
    expect(setup?.body).toMatchObject({ action: "Setup", op: "OP-GATE" });
  });

  it("não bloqueia o Iniciar na Caldeiraria: o portão é do Finalizar", async () => {
    const { calls } = gateBackend();
    render(<MemoryRouter initialEntries={["/operador"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    await screen.findByRole("heading", { name: "Dobra - 1303" });
    fireEvent.change(screen.getByLabelText("Código da OP"), { target: { value: "OP-GATE" } });
    fireEvent.click(screen.getByRole("button", { name: "Carregar roteiro" }));
    await screen.findByRole("button", { name: "20 - DOBRA — Atual" });

    fireEvent.click(screen.getByRole("button", { name: "Iniciar" }));

    await screen.findByText("Início registrado com sucesso.");
    expect(screen.queryByRole("heading", { name: "Setup e Qualidade" })).not.toBeInTheDocument();
    const inicio = calls.find((call) => call.method === "POST" && call.path.includes("/operator/actions"));
    expect(inicio?.body).toMatchObject({ action: "Início", op: "OP-GATE" });
  });

  it("recusa o Finalizar antes da conferência e manda apontar o Setup", async () => {
    gateBackend({ recusaFinalizar: true });
    render(<MemoryRouter initialEntries={["/operador"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    await screen.findByRole("heading", { name: "Dobra - 1303" });
    fireEvent.change(screen.getByLabelText("Código da OP"), { target: { value: "OP-GATE" } });
    fireEvent.click(screen.getByRole("button", { name: "Carregar roteiro" }));
    await screen.findByRole("button", { name: "20 - DOBRA — Atual" });

    // O aviso do posto já orienta antes mesmo de tentar.
    expect(screen.getByText(/Aponte o Setup para conferir a primeira peça/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Finalizar" }));

    // O clique entrega a orientação; nem o popup do checklist nem o diálogo de
    // finalização abrem antes da primeira peça aprovada.
    expect(await screen.findByText(/Aponte o Setup desta operação/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Setup e Qualidade" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Finalizar produção" })).not.toBeInTheDocument();
  });

  it("cancelar o popup não aprova a primeira peça nem finaliza a OP", async () => {
    const { calls } = await abrirPortao();

    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancelar" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    // O Setup apontado continua valendo — ele é tempo de máquina, não
    // aprovação —, mas nada foi inspecionado nem finalizado.
    const posts = calls.filter((call) => call.method === "POST");
    expect(posts.every((call) => (call.body as { action?: string } | null)?.action === "Setup")).toBe(true);
    expect(calls.some((call) => call.method === "POST" && call.path.includes("/first-piece"))).toBe(false);
  });

  it("mede a cota, libera o lote e retoma a produção sem clique manual", async () => {
    const { calls } = await abrirPortao();

    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Medida da cota 1"), { target: { value: "12,1" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Liberar lote" }));

    await screen.findByText("Retorno registrado com sucesso.");
    const checklist = calls.find((call) => call.method === "POST" && call.path.includes("/operator/first-piece"));
    expect(checklist?.body).toMatchObject({
      action: "checklist",
      op: "OP-GATE",
      measures: [{ sequencia: 1, medida: "12,1" }],
    });
    // A OP volta sozinha para a produção: o operador não clica em Iniciar.
    const retorno = calls.filter((call) => call.method === "POST" && call.path.includes("/operator/actions")).pop();
    expect(retorno?.body).toMatchObject({ action: "Retornar", op: "OP-GATE" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("não pede confirmação de Setup dentro do popup", async () => {
    // O Setup é apontamento de estado do botão do posto; o popup não repete
    // essa confirmação para não existirem duas fontes de verdade.
    await abrirPortao();

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("pede o crachá do responsável quando a peça reprovada vai para refugo", async () => {
    await abrirPortao();

    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Medida da cota 1"), { target: { value: "13,5" } });
    fireEvent.change(within(dialog).getByLabelText("Destino da peça reprovada"), { target: { value: "REFUGO" } });

    expect(within(dialog).getByLabelText("Crachá do responsável que autoriza o refugo")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Chamar responsável" })).toBeInTheDocument();
    // A chamada só avisa: sem o crachá, a autorização continua bloqueada.
    expect(within(dialog).getByRole("button", { name: "Liberar lote" })).toBeDisabled();
  });

  it("oferece o cadastro das cotas quando o produto ainda não tem checklist", async () => {
    await abrirPortao({ configuravel: true });

    expect(await screen.findByRole("heading", { name: "Cadastro das cotas do produto" })).toBeInTheDocument();
    expect(screen.getByLabelText("Padrão da cota 1")).toBeInTheDocument();
  });

  it("mostra Solda Aço por número de estação e não oferece Setup", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json({ id: 5, name: "Soldador", role: "estacao1aco", management_access: false, operator_access: true, operator_sector: "Solda Aço" });
      // Wave 6F: cada login de Solda Aço é uma estação fixa. O contexto
      // entrega uma única estação, diz que ela não é escolhida na tela
      // (`fixed_resource`) e que o setor não possui Setup (`has_setup`).
      if (path.includes("/operator/context")) return json({ sector: "Solda Aço", route: "Solda Aço", resources: ["Estação 1"], fixed_resource: true, station_profile_required: false, has_setup: false, automatic_queue: false, workflow: "workbench" });
      if (path.includes("/operator/stop-reasons")) return json({ items: [] });
      if (path.includes("/operator/operators")) return json({ items: [] });
      if (path.includes("/operator/workbench")) return json({ sector: "Solda Aço", resource: "Estação 1", queue: [], production: [] });
      if (path.includes("/operator/history")) return json({ items: [], has_more: false });
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    }));

    render(<MemoryRouter initialEntries={["/operador"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    await screen.findByRole("heading", { name: "Solda Aço - Estação 1" });
    expect(screen.queryByRole("heading", { name: "Selecione o recurso" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Voltar" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Ações operacionais")).toHaveClass("operator-actions");
    expect(screen.queryByRole("button", { name: "Setup" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retrabalho" })).toBeInTheDocument();
  });

  it("finaliza na Solda direto, sem portão de primeira peça e sem selecionar o marco terminal", async () => {
    // Regressão do posto de Solda Aço: sem Setup e sem checklist de cotas, o
    // portão da primeira peça (quando ainda se aplicava a esse setor) não
    // tinha entrada na tela e `pode_finalizar` ficava permanentemente falso
    // na etapa real — o único botão Finalizar habilitado era o do marco
    // terminal, que não fecha apontamento nenhum. Decisão do usuário
    // (15/09/2026): Solda e Pintura têm esquema de qualidade próprio e não
    // participam do portão — o backend manda `primeira_peca.aplicavel: false`
    // e o Finalizar da etapa real precisa funcionar direto, sem popup.
    const gateNaoAplicavel = {
      aplicavel: false,
      liberado: true,
      status: "CONFORME",
      peca_produzida: false,
      setup_obrigatorio: false,
      setup_registrado: false,
      inspecao_concluida: false,
      bloqueio_ativo: false,
      gate_estruturado: false,
      code: "",
      message: "Esta operação não está sujeita à regra da primeira peça.",
      pendencias: [],
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      if (path.includes("/auth/session")) return json({ id: 61, name: "Soldador", role: "estacao6aco", management_access: false, operator_access: true, operator_sector: "Solda Aço" });
      if (path.includes("/operator/context")) return json({ sector: "Solda Aço", route: "Solda Aço", resources: ["Estação 6"], fixed_resource: true, has_setup: false, automatic_queue: false, workflow: "workbench" });
      if (path.includes("/operator/stop-reasons") || path.includes("/operator/operators")) return json({ items: [] });
      if (path.includes("/operator/history")) return json({ items: [], has_more: false });
      if (path.includes("/operator/workbench")) return json({ sector: "Solda Aço", resource: "Estação 6", queue: [], production: [] });
      if (path.includes("/operator/drawings")) return json({ available: false, message: "Nenhum desenho disponível." });
      if (path.includes("/operator/operations/OP-SOLDA")) return json({ items: [
        { id: 10, numero_operacao: "10", descricao_operacao: "SOLDA", visual_status: "current", visual_current: true, actionable: true, selectable: true, requires_confirmation: false, quantidade_planejada: 5, pode_finalizar: true, exige_gate_primeira_peca: false, primeira_peca: gateNaoAplicavel },
        { id: 99, numero_operacao: "99", descricao_operacao: "FINALIZADA", visual_status: "pending", actionable: false, selectable: false, requires_confirmation: false, pode_finalizar: false },
      ] });
      if (method === "POST") return json({ ok: true, message: "Finalizado." });
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    }));

    render(<MemoryRouter initialEntries={["/operador"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    await screen.findByRole("heading", { name: "Solda Aço - Estação 6" });
    fireEvent.change(screen.getByLabelText("Código da OP"), { target: { value: "OP-SOLDA" } });
    fireEvent.click(screen.getByRole("button", { name: "Carregar roteiro" }));
    await screen.findByRole("button", { name: "10 - SOLDA — Atual" });

    // O marco terminal continua visível como leitura, mas não é selecionável.
    expect(screen.getByRole("button", { name: "99 - FINALIZADA — Próxima" })).toBeDisabled();
    // E o Finalizar da etapa real vai direto para a finalização, sem popup.
    const finalizar = screen.getByRole("button", { name: "Finalizar" });
    expect(finalizar).toBeEnabled();
    fireEvent.click(finalizar);
    await screen.findByRole("heading", { name: "Finalizar produção" });
  });

  it("recusa escolher estação de Solda Aço quando o login não tem perfil fixo", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json({ id: 6, name: "Soldador", role: "estacao1aco", management_access: false, operator_access: true, operator_sector: "Solda Aço" });
      if (path.includes("/operator/context")) return json({ sector: "Solda Aço", route: "Solda Aço", resources: ["Estação 1", "Estação 2"], fixed_resource: false, station_profile_required: true, has_setup: false, automatic_queue: false, workflow: "workbench" });
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    }));

    render(<MemoryRouter initialEntries={["/operador"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    // A estação é atributo do login, não uma escolha do operador: sem vínculo,
    // a tela explica em vez de oferecer um seletor.
    expect(await screen.findByText("Perfil de Solda Aço sem estação fixa")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Selecione o recurso" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Estação 1" })).not.toBeInTheDocument();
  });

  it("consome a OP originada no TOTVS pelo mesmo contrato de fila, sem marca de origem", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json({ id: 7, name: "Operador Usinagem", role: "operador_usinagem", management_access: false, operator_access: true, operator_sector: "Usinagem" });
      if (path.includes("/operator/context")) return json({ sector: "Usinagem", route: "Usinagem", resources: ["Romi D 1000"], automatic_queue: false, workflow: "workbench" });
      if (path.includes("/operator/stop-reasons")) return json({ items: [] });
      if (path.includes("/operator/operators")) return json({ items: [] });
      if (path.includes("/operator/history")) return json({ items: [], has_more: false });
      if (path.includes("/operator/workbench")) return json({
        sector: "Usinagem",
        resource: "Romi D 1000",
        production: [],
        queue: [{ catalogo_operacao_id: 172, op: "A9716901001", status: "Aguardando", operation: "20 - USINAGEM", numero_operacao: "20", product: "PNT002002003", description: "BRACO ARTICULACAO", qty: 10, good: 0, scrap: 0, virtual_queue: true }],
      });
      if (path.includes("/operator/operations/A9716901001")) return json({ items: [{ id: 172, numero_operacao: "20", descricao_operacao: "USINAGEM", visual_status: "current", visual_current: true, quantidade_planejada: 10, saldo_quantidade_boa: 10 }] });
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter initialEntries={["/operador"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    await screen.findByRole("heading", { name: "Usinagem - Romi D 1000" });
    expect(await screen.findByText("OP: A9716901001")).toBeInTheDocument();
    expect(screen.getByText("BRACO ARTICULACAO")).toBeInTheDocument();
    // A tela não exibe nenhuma marca de origem corporativa para o operador.
    expect(screen.queryByText(/TOTVS/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("OP: A9716901001"));
    await screen.findByRole("button", { name: "20 - USINAGEM — Atual" });
    expect(fetchMock.mock.calls.some(([path]) => String(path).includes("/operator/operations/A9716901001"))).toBe(true);
  });

  it("busca a OP ausente e carrega o roteiro sem o operador abrir o ERP", async () => {
    let synced = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json({ id: 9, name: "Operador Usinagem", role: "operador_usinagem", management_access: false, operator_access: true, operator_sector: "Usinagem" });
      if (path.includes("/operator/context")) return json({ sector: "Usinagem", route: "Usinagem", resources: ["Romi D 1000"], automatic_queue: false, workflow: "workbench" });
      if (path.includes("/operator/stop-reasons")) return json({ items: [] });
      if (path.includes("/operator/operators")) return json({ items: [] });
      if (path.includes("/operator/history")) return json({ items: [], has_more: false });
      if (path.includes("/operator/workbench")) return json({ sector: "Usinagem", resource: "Romi D 1000", production: [], queue: [] });
      if (path.includes("/operator/operations/PCMIXQ01001/sync") && init?.method === "POST") {
        synced = true;
        return json({ op: "PCMIXQ01001", items: [], sync: { status: "sincronizada", message: "OP carregada.", found: true } });
      }
      if (path.includes("/operator/operations/PCMIXQ01001")) {
        return synced
          ? json({ items: [{ id: 501, numero_operacao: "20", descricao_operacao: "USINAGEM", visual_status: "current", visual_current: true }], sync: { source: "local", pending: false, remote_available: true } })
          : json({ items: [], sync: { source: "miss", pending: true, remote_available: true } });
      }
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter initialEntries={["/operador"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    await screen.findByRole("heading", { name: "Usinagem - Romi D 1000" });
    fireEvent.change(screen.getByLabelText(/Código da OP/i), { target: { value: "PCMIXQ01001" } });
    fireEvent.click(screen.getByRole("button", { name: "Carregar roteiro" }));

    // O roteiro aparece sozinho: o operador não abriu nenhuma tela do ERP.
    await screen.findByRole("button", { name: "20 - USINAGEM — Atual" });
    expect(fetchMock.mock.calls.some(([path, init]) => String(path).includes("/operator/operations/PCMIXQ01001/sync") && init?.method === "POST")).toBe(true);
  });

  it("informa OP inexistente sem expor detalhe técnico ao operador", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json({ id: 10, name: "Operador Usinagem", role: "operador_usinagem", management_access: false, operator_access: true, operator_sector: "Usinagem" });
      if (path.includes("/operator/context")) return json({ sector: "Usinagem", route: "Usinagem", resources: ["Romi D 1000"], automatic_queue: false, workflow: "workbench" });
      if (path.includes("/operator/stop-reasons")) return json({ items: [] });
      if (path.includes("/operator/operators")) return json({ items: [] });
      if (path.includes("/operator/history")) return json({ items: [], has_more: false });
      if (path.includes("/operator/workbench")) return json({ sector: "Usinagem", resource: "Romi D 1000", production: [], queue: [] });
      if (path.includes("/operator/operations/ZZ999/sync") && init?.method === "POST") {
        return json({ op: "ZZ999", items: [], sync: { status: "nao_encontrada", message: "OP não encontrada no TOTVS.", found: false } });
      }
      if (path.includes("/operator/operations/ZZ999")) return json({ items: [], sync: { source: "miss", pending: true, remote_available: true } });
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter initialEntries={["/operador"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    await screen.findByRole("heading", { name: "Usinagem - Romi D 1000" });
    fireEvent.change(screen.getByLabelText(/Código da OP/i), { target: { value: "ZZ999" } });
    fireEvent.click(screen.getByRole("button", { name: "Carregar roteiro" }));

    await screen.findByText("OP não encontrada no TOTVS.");
    expect(screen.queryByText(/SOAP|Traceback|http/i)).not.toBeInTheDocument();
  });

  it("explica o setor sem posto cadastrado em vez de exibir painel vazio", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json({ id: 8, name: "Operador Montagem", role: "operador_montagem", management_access: false, operator_access: true, operator_sector: "Montagem" });
      if (path.includes("/operator/context")) return json({ sector: "Montagem", route: "Montagem", resources: [], automatic_queue: false, workflow: "workbench" });
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    }));

    render(<MemoryRouter initialEntries={["/operador"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    await screen.findByRole("heading", { name: "Selecione o recurso" });
    expect(await screen.findByText("Nenhum posto configurado para este setor")).toBeInTheDocument();
    expect(screen.getByText("Montagem", { selector: ".operator-sector-link strong" })).toBeInTheDocument();
  });

  it("retoma o Destaque parado sem tarefa carregada", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json({ id: 9, name: "Destacador", role: "operador_destaque", management_access: false, operator_access: true, operator_sector: "Destaque" });
      if (path.includes("/operator/context")) return json({ sector: "Destaque", route: "Destaque", resources: [], automatic_queue: false, workflow: "highlight" });
      if (path.includes("/operator/stop-reasons")) return json({ items: [] });
      if (path.includes("/highlight/queue")) {
        return json({
          items: [],
          count: 0,
          parciais: 0,
          completas: 0,
          planos_disponiveis: 0,
          resource_state: { categoria: "parada", motivo: "0029 - Quebra de ferramenta", op: null },
        });
      }
      if (path.includes("/highlight/actions") && init?.method === "POST") return json({ ok: true, message: "Recurso retomado com sucesso.", code: "retomada_recurso_sem_op" });
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter initialEntries={["/operador"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    await screen.findByText(/Posto parado — 0029 - Quebra de ferramenta/);
    // Sem tarefa carregada não existe destaque para retomar pelo Início.
    fireEvent.click(screen.getByRole("button", { name: "Retomar" }));
    await screen.findByText("Recurso retomado com sucesso.");
    const call = fetchMock.mock.calls.find(([path, init]) => String(path).includes("/highlight/actions") && init?.method === "POST");
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ action: "Retomar", task_code: null });
  });

  it("confere as OPs por checklist antes de finalizar o Destaque", async () => {
    const operacoes = [
      { id: 1, codigo_op: "OP-1001", id_peca: "PECA-A", quantidade_atual: 3, setor_destino_atual: "Aguardando Dobra" },
      { id: 2, codigo_op: "OP-1002", id_peca: "PECA-B", quantidade_atual: 5, setor_destino_atual: "Almoxarifado" },
    ];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json({ id: 9, name: "Destacador", role: "operador_destaque", management_access: false, operator_access: true, operator_sector: "Destaque" });
      if (path.includes("/operator/context")) return json({ sector: "Destaque", route: "Destaque", resources: [], automatic_queue: false, workflow: "highlight" });
      if (path.includes("/operator/stop-reasons")) return json({ items: [] });
      if (path.includes("/highlight/queue")) return json({ items: [], count: 0, parciais: 0, completas: 0, planos_disponiveis: 0 });
      if (path.includes("/highlight/tasks/T-100")) return json({
        task: { id: 7, codigo_tarefa: "T-100", material: "A36", espessura: 6.35 },
        operations: operacoes,
        state: { estado: "inicio" },
        timing: { availability: "ok", execution_seconds: 60, stopped_seconds: 0 },
        plans: [
          { plano_hash: "hash-a", programa: "8501", nome_chapa: "CHAPA 3000 x 1500", sequencia: 1, repeticao: 1, maquina: "Laser Ensis 3015", quantidade_processo: 4, status_corte: "Finalizado", estado_destaque: "aguardando" },
          { plano_hash: "hash-b", programa: "8501", nome_chapa: "CHAPA 3000 x 1500", sequencia: 2, repeticao: 2, maquina: "Laser Ensis 3015", quantidade_processo: 4, status_corte: "Aguardando", estado_destaque: "aguardando" },
          { plano_hash: "hash-c", programa: "8502", nome_chapa: "CHAPA 3000 x 1500", sequencia: 3, repeticao: 1, maquina: "Laser Ensis 3015", quantidade_processo: 4, status_corte: "Finalizado", estado_destaque: "inicio" },
        ],
        progress: { situacao: "PARCIAL", chapas_total: 3, chapas_cortadas: 2, chapas_destacadas: 0, chapas_disponiveis: 2, progresso_corte: "2 de 3 planos cortados" },
        history: [{ id: 3, estado: "inicio", operador: "Destacador", data_hora: "2026-08-27T10:00:00" }],
      });
      if (path.includes("/highlight/actions") && init?.method === "POST") return json({ ok: true, message: "Destaque finalizado." });
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter initialEntries={["/operador"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    fireEvent.change(await screen.findByLabelText("Buscar tarefa"), { target: { value: "T-100" } });
    fireEvent.click(screen.getByRole("button", { name: "Buscar" }));

    // Wave 3: o Destaque não tem "Fila de Ordem" de máquina; ele mostra os
    // planos da tarefa, cada um com a sua situação de Corte e de Destaque.
    await screen.findByRole("heading", { name: "Planos da tarefa" });
    expect(screen.queryByRole("heading", { name: "Fila de Ordem" })).not.toBeInTheDocument();
    expect(screen.getByText("Corte parcial · 2 de 3 planos cortados")).toBeInTheDocument();
    // O plano nunca aparece solto: a tarefa pai encabeça cada bloco.
    expect(screen.getAllByText("Tarefa T-100").length).toBeGreaterThan(0);
    // Só a chapa já cortada e ainda não iniciada pode ser destacada.
    expect(screen.getAllByRole("button", { name: "Destacar este plano" })).toHaveLength(1);
    // Histórico do Destaque disponível na própria tela.
    expect(screen.getByRole("heading", { name: "Histórico" })).toBeInTheDocument();

    // Wave 4: enquanto o Corte da tarefa está incompleto, o fim da tarefa
    // inteira permanece bloqueado. O que se conclui é o plano já destacado.
    expect(screen.getByRole("button", { name: "Fim" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Concluir plano" }));
    const confirmar = await screen.findByRole("button", { name: "Confirmar fim" });
    // O escopo declarado no diálogo é o plano escolhido, não a tarefa inteira.
    expect(within(screen.getByRole("dialog")).getByText("Plano 8502 · chapa 1")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Crachá do operador"), { target: { value: "9001" } });
    // Sem conferir as OPs, a finalização continua bloqueada.
    expect(confirmar).toBeDisabled();

    // A busca filtra o checklist por peça/OP (a tabela da página segue intacta).
    fireEvent.change(screen.getByLabelText("Buscar peça ou OP"), { target: { value: "PECA-B" } });
    const checklist = within(screen.getByRole("group", { name: "Conferência das OPs" }));
    expect(checklist.queryByText("OP-1001")).not.toBeInTheDocument();
    expect(checklist.getByText("OP-1002")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Buscar peça ou OP"), { target: { value: "" } });

    // Marcar todas libera a confirmação.
    fireEvent.click(screen.getByRole("button", { name: "Marcar todas" }));
    expect(await screen.findByRole("button", { name: "Confirmar fim" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Confirmar fim" }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([path, init]) => String(path).includes("/highlight/actions") && init?.method === "POST")).toBe(true));
    const acao = fetchMock.mock.calls.find(([path, init]) => String(path).includes("/highlight/actions") && init?.method === "POST");
    expect(JSON.parse(String(acao?.[1]?.body))).toMatchObject({ action: "Fim", task_code: "T-100", plan_hash: "hash-c" });
  });

  it("mostra a tarefa nova do Corte sozinha, sem pesquisa nem refresh de página", async () => {
    let tarefas: Array<Record<string, unknown>> = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json({ id: 12, name: "Cortador", role: "operador_corte", management_access: false, operator_access: true, operator_sector: "Corte" });
      if (path.includes("/operator/context")) return json({ sector: "Corte", route: "Corte", resources: ["Laser Ensis 3015"], automatic_queue: true, workflow: "cutting" });
      if (path.includes("/operator/stop-reasons")) return json({ items: [] });
      if (path.includes("/cutting/queue")) return json({ resource: "Laser Ensis 3015", resource_state: null, items: tarefas });
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("EventSource", SseStub);

    render(<MemoryRouter initialEntries={["/operador"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    await screen.findByRole("heading", { name: "Corte - Laser Ensis 3015" });
    expect(await screen.findByText("Nenhum plano na fila")).toBeInTheDocument();
    // A pesquisa não é mais o mecanismo que descobre/importa a tarefa.
    expect(screen.queryByRole("button", { name: "Buscar" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Filtrar a fila")).toBeInTheDocument();

    // O planejamento é materializado no banco do Gestor pelo ciclo de fundo.
    tarefas = [{ codigo_tarefa: "T-NOVA", plano_hash: "h1", programa: "9001", material: "A36", status: "Aguardando", nesting_count: 1, nestings_concluidos: 0, nestings_aguardando: 1, tempo_previsto_segundos: 120 }];
    await act(async () => { SseStub.instance?.emit("cutting_queue"); });

    // Nenhuma pesquisa, nenhum recarregamento: a tarefa aparece sozinha.
    expect(await screen.findByText("T-NOVA")).toBeInTheDocument();
    expect(fetchMock.mock.calls.every(([path]) => !String(path).includes("search="))).toBe(true);

    // A partir daqui, digitar é só filtrar o que já está disponível.
    fireEvent.change(screen.getByLabelText("Filtrar a fila"), { target: { value: "9001" } });
    await waitFor(() => expect(fetchMock.mock.calls.some(([path]) => String(path).includes("/cutting/queue") && String(path).includes("search=9001"))).toBe(true));
  });

  it("mostra as tarefas liberadas pelo Corte sem fila numerada de máquina", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json({ id: 21, name: "Destacador", role: "operador_destaque", management_access: false, operator_access: true, operator_sector: "Destaque" });
      if (path.includes("/operator/context")) return json({ sector: "Destaque", route: "Destaque", resources: [], automatic_queue: false, workflow: "highlight" });
      if (path.includes("/operator/stop-reasons")) return json({ items: [] });
      if (path.includes("/highlight/queue")) return json({
        items: [
          { tarefa_id: 1, codigo_tarefa: "T001", material: "A36", espessura: 6.35, situacao: "PARCIAL", chapas_total: 4, chapas_cortadas: 2, chapas_destacadas: 0, chapas_disponiveis: 2, progresso_corte: "2 de 4 planos cortados", planos: [] },
          { tarefa_id: 2, codigo_tarefa: "T002", material: "INOX", espessura: 3, situacao: "COMPLETA", chapas_total: 3, chapas_cortadas: 3, chapas_destacadas: 1, chapas_disponiveis: 2, progresso_corte: "3 de 3 planos cortados", planos: [] },
        ],
        count: 2, parciais: 1, completas: 1, planos_disponiveis: 4,
      });
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    }));

    render(<MemoryRouter initialEntries={["/operador"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    expect(await screen.findByText("Tarefa T001")).toBeInTheDocument();
    expect(screen.getByText("Tarefa T002")).toBeInTheDocument();
    expect(screen.getByText("2 de 4 planos cortados")).toBeInTheDocument();
    expect(screen.getByText("Corte concluído")).toBeInTheDocument();
    expect(screen.getByText("Corte parcial")).toBeInTheDocument();
    // Nada de "Fila de Ordem" nem de numeração de máquina.
    expect(screen.queryByText(/Fila de Ordem/)).not.toBeInTheDocument();
  });

  it("permite atualizar as tarefas do Corte e mostra a última sincronização", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json({ id: 22, name: "Cortador", role: "operador_corte", management_access: false, operator_access: true, operator_sector: "Corte" });
      if (path.includes("/operator/context")) return json({ sector: "Corte", route: "Corte", resources: ["Laser Ensis 3015"], automatic_queue: true, workflow: "cutting" });
      if (path.includes("/operator/stop-reasons")) return json({ items: [] });
      if (path.includes("/cutting/sync") && init?.method === "POST") {
        return json({ ok: true, message: "3 nova(s), 2 atualizada(s)", aderiu_a_ciclo_em_andamento: false, sync: {} });
      }
      if (path.includes("/cutting/queue")) return json({
        resource: "Laser Ensis 3015", resource_state: null, items: [],
        sync: { ultima_sincronizacao: "2026-09-04T15:02:00", executando: false, ciclos: 4, erro: null, automatica: true },
      });
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter initialEntries={["/operador"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    await screen.findByRole("heading", { name: "Corte - Laser Ensis 3015" });
    // O horário é do backend, não do último refresh do React.
    expect(await screen.findByText((texto) => texto.startsWith("Última sincronização:") && texto.includes("04/09/2026"))).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Atualizar tarefas" }));
    expect(await screen.findByText((texto) => texto.includes("3 nova(s), 2 atualizada(s)"))).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([path, init]) => String(path).includes("/cutting/sync") && init?.method === "POST")).toBe(true);
  });

  it("mantém a fila local quando a sincronização do Corte falha", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json({ id: 23, name: "Cortador", role: "operador_corte", management_access: false, operator_access: true, operator_sector: "Corte" });
      if (path.includes("/operator/context")) return json({ sector: "Corte", route: "Corte", resources: ["Laser Ensis 3015"], automatic_queue: true, workflow: "cutting" });
      if (path.includes("/operator/stop-reasons")) return json({ items: [] });
      if (path.includes("/cutting/sync") && init?.method === "POST") {
        return json({ code: "sync_failed", message: "falha" }, 503);
      }
      if (path.includes("/cutting/queue")) return json({
        resource: "Laser Ensis 3015", resource_state: null,
        items: [{ codigo_tarefa: "T-LOCAL", programa: "9001", material: "A36", status: "Aguardando", nesting_count: 1, quantidade_chapas: 1, nestings_concluidos: 0, nestings_aguardando: 1, tempo_previsto_segundos: 120, nestings: [] }],
        sync: { ultima_sincronizacao: "2026-09-04T15:02:00" },
      });
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    }));

    render(<MemoryRouter initialEntries={["/operador"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    await screen.findByRole("heading", { name: "Corte - Laser Ensis 3015" });
    expect(await screen.findByText("T-LOCAL")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Atualizar tarefas" }));
    expect(await screen.findByText(/Não foi possível atualizar as tarefas/)).toBeInTheDocument();
    // A fila anterior continua na tela; nada foi apagado.
    expect(screen.getByText("T-LOCAL")).toBeInTheDocument();
    expect(screen.queryByText(/Traceback|ODBC|SQL/)).not.toBeInTheDocument();
  });

  it("abre o histórico do Corte sem alterar a fila ativa", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json({ id: 10, name: "Cortador", role: "operador_corte", management_access: false, operator_access: true, operator_sector: "Corte" });
      if (path.includes("/operator/context")) return json({ sector: "Corte", route: "Corte", resources: ["Laser Ensis 3015"], automatic_queue: true, workflow: "cutting" });
      if (path.includes("/operator/stop-reasons")) return json({ items: [] });
      if (path.includes("/cutting/history")) return json({
        resource: "Laser Ensis 3015", status: "Finalizado",
        items: [{
          codigo_tarefa: "T3492", programa: "8634", material: "ASTM A36",
          nesting_count: 2, nestings_concluidos: 2,
          // O histórico é uma linha por chapa física: cada nesting carrega os
          // próprios tempos, chapa, repetição e máquina.
          nestings: [
            { plano_hash: "h1", sequencia: 1, programa: "8634", nome_chapa: "CHAPA 3000 x 1500", repeticao: 1, status: "Finalizado", quantidade_processo: 6, maquina: "Laser Ensis 3015", data_programa: "2026-08-30T17:00:00", data_inicio: "2026-08-31T08:33:33", data_fim: "2026-08-31T08:33:35", tempo_real_segundos: 2 },
            { plano_hash: "h2", sequencia: 2, programa: "8634", nome_chapa: "CHAPA 3000 x 1500", repeticao: 2, status: "Finalizado", quantidade_processo: 6, maquina: "Laser Ensis 3015", data_programa: "2026-08-30T17:00:00", data_inicio: "2026-08-31T08:33:35", data_fim: "2026-08-31T08:33:37", tempo_real_segundos: 2 },
          ],
          ops_relacionadas: ["00617399002", "00617399003"],
          data_inicio: "2026-08-31T08:33:33", data_fim: "2026-08-31T08:33:37", tempo_real_segundos: 4,
        }],
      });
      if (path.includes("/cutting/queue")) return json({ resource: "Laser Ensis 3015", resource_state: null, items: [] });
      return json({ code: "not_found", message: "Não encontrado" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter initialEntries={["/operador"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    await screen.findByRole("heading", { name: "Corte - Laser Ensis 3015" });
    // O histórico só é consultado quando o operador pede.
    expect(fetchMock.mock.calls.some(([path]) => String(path).includes("/cutting/history"))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Histórico" }));
    // Uma linha por chapa cortada, cada uma com a própria repetição e duração.
    const linhas = await screen.findAllByRole("row", { name: /T3492/ });
    expect(linhas).toHaveLength(2);
    expect(within(linhas[0]).getByText("CHAPA 3000 x 1500 · 1")).toBeInTheDocument();
    expect(within(linhas[1]).getByText("CHAPA 3000 x 1500 · 2")).toBeInTheDocument();
    expect(within(linhas[0]).getByText("00:00:02")).toBeInTheDocument();
    expect(screen.getAllByText("00617399002, 00617399003")).toHaveLength(2);
  });
});
