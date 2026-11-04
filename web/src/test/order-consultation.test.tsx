import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";

const NA_TEXT = "Tempo padrão não cadastrado no Protheus. A engenharia de manufatura ajusta direto no ERP.";

function json(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: { "content-type": "application/json" } });
}

const SESSION = { id: 1, name: "Conta PCP", role: "admin", management_access: true, andon_access: true, operator_access: false };

const SEARCH = { items: [{ codigo_op: "OP-100", produto_codigo: "PROD-1", produto_descricao: "Suporte lateral", quantidade: 10, status_pcp: "liberada" }], count: 1 };

function consultation(canAdd: boolean) {
  return {
    system: { situacao: "ja_passou", apontamentos: 3, iniciados: 2, primeira_entrada: "2026-10-05T08:00:00", ultima_atividade: "2026-10-06T10:00:00", coletada_em: "2026-10-04T07:00:00" },
    order: {
      codigo_op: "OP-100", produto_codigo: "PROD-1", produto_descricao: "Suporte lateral", quantidade: 10, unidade: "UN",
      status_pcp: "liberada", filial: "04", data_emissao: "2026-10-01T08:00:00", data_liberacao: null,
      inicio_planejado: "2026-10-05T08:00:00", fim_planejado: "2026-10-06T17:00:00", prioridade: 500,
    },
    route: [
      { id: 1, ordem: 1, numero_operacao: "10", descricao: "Cortar chapa", setor: "Corte", recurso_codigo: "LASER1", recurso_nome: "Laser 1",
        tempo_padrao: { segundos: 42.5, disponivel: true, nota: null }, situacao: "Não iniciada", origem: "protheus", ativo: true, marco_terminal: false, inspecao_qualidade: false },
      { id: 2, ordem: 2, numero_operacao: "20", descricao: "Dobrar aba", setor: "Dobra", recurso_codigo: "DOBRA01", recurso_nome: "Dobradeira 1",
        tempo_padrao: { segundos: null, disponivel: false, nota: NA_TEXT }, situacao: "Não iniciada", origem: "protheus", ativo: true, marco_terminal: false, inspecao_qualidade: false },
      { id: 3, ordem: 3, numero_operacao: "G01", descricao: "Rebarbar manual", setor: "Rebarbação", recurso_codigo: "REB01", recurso_nome: "Bancada 1",
        tempo_padrao: { segundos: null, disponivel: false, nota: NA_TEXT }, situacao: "Não iniciada", origem: "gestor", ativo: true, marco_terminal: false, inspecao_qualidade: false },
    ],
    history: [
      { id: 9, quando: "2026-10-02T10:00:00", usuario_id: 1, usuario_nome: "Maria PCP", entidade: "roteiro_etapa", chave: "OP-100", acao: "criar", antes: null,
        depois: { numero_operacao: "G01", descricao_operacao: "Rebarbar manual", motivo: "Peça saiu com rebarba" } },
    ],
    permissions: { can_add_step: canAdd },
    add_options: canAdd
      ? {
        after_operations: [
          { id: 1, numero_operacao: "10", descricao: "Cortar chapa" },
          { id: 2, numero_operacao: "20", descricao: "Dobrar aba" },
        ],
        resources: [{ codigo: "REB01", nome: "Bancada 1", setor: "Rebarbação" }, { codigo: "SOLDA1", nome: "Solda 1", setor: "Solda" }],
      }
      : null,
  };
}

type Handler = (path: string, init?: RequestInit) => Response | undefined;

function stubFetch(canAdd: boolean, handler: Handler = () => undefined) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.includes("/auth/session")) return json(SESSION);
    const custom = handler(path, init);
    if (custom) return custom;
    if (path.includes("/order-consultation/search")) return json(SEARCH);
    if (path.endsWith("/order-consultation/OP-100")) return json(consultation(canAdd));
    return json({ code: "not_found", message: "Não encontrado" }, 404);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/producao/ordens"]}>
      <AuthProvider><App /></AuthProvider>
    </MemoryRouter>,
  );
}

async function openOrder() {
  fireEvent.change(await screen.findByLabelText("Buscar OP", {}, { timeout: 3000 }), { target: { value: "OP-1" } });
  fireEvent.click(await screen.findByRole("option", { name: /OP-100/ }, { timeout: 3000 }));
  await screen.findByText("Rebarbar manual", { selector: "td, td *" }, { timeout: 3000 });
}

const postCalls = (mock: ReturnType<typeof vi.fn>) =>
  mock.mock.calls.filter(([, init]) => (init as RequestInit | undefined)?.method === "POST");

beforeEach(() => {
  document.cookie = "gestor_csrf=csrf-teste; path=/";
});
afterEach(() => vi.restoreAllMocks());

describe("Consulta de OP", () => {
  it("mostra que a OP já passou pelo sistema", async () => {
    stubFetch(false);
    renderPage();
    await openOrder();
    expect(screen.getByText("Já passou pelo sistema.")).toBeTruthy();
  });

  it("OP que o Gestor não tem: consulta o Protheus e diz que ainda não passou pelo sistema", async () => {
    const mock = stubFetch(false, (path) => {
      if (path.includes("/order-consultation/search")) return json({ items: [], count: 0 });
      if (path.endsWith("/order-consultation/OP-999/protheus")) {
        return json({ op: "OP-999", estava_no_gestor: false, protheus: { status: "nao_encontrada", consultado: true, message: "x" }, system: { situacao: "so_protheus", apontamentos: 0, iniciados: 0, primeira_entrada: null, ultima_atividade: null, coletada_em: null } });
      }
      return undefined;
    });
    renderPage();
    fireEvent.change(await screen.findByLabelText("Buscar OP", {}, { timeout: 3000 }), { target: { value: "OP-999" } });
    fireEvent.click(await screen.findByRole("button", { name: /no Protheus/ }, { timeout: 3000 }));
    await screen.findByText(/não encontrada no Protheus e nunca passou pelo sistema/i, {}, { timeout: 3000 });
    expect(postCalls(mock)).toHaveLength(1);
  });

  it("busca a OP, mostra cabeçalho e roteiro na ordem, com n/a explicado e selo do Gestor", async () => {
    const mock = stubFetch(false);
    renderPage();
    await openOrder();

    expect(mock.mock.calls.some(([path]) => String(path).includes("/order-consultation/search?q=OP-1"))).toBe(true);
    expect(screen.getByRole("heading", { name: "OP OP-100" })).toBeTruthy();
    expect(screen.getByText("Suporte lateral", { selector: "dd" })).toBeTruthy();

    const rows = screen.getAllByRole("row").slice(1, 4);
    expect(rows.map((row) => within(row).getAllByRole("cell")[0].textContent)).toEqual(["10", "20", "G01Adicionada no Gestor"]);
    expect(screen.getByText("42,5 s")).toBeTruthy();
    expect(screen.getAllByText("n/a")).toHaveLength(2);
    expect(screen.getAllByText("n/a")[0].getAttribute("title")).toBe(NA_TEXT);
    expect(screen.getByText(NA_TEXT)).toBeTruthy();
    expect(screen.getByText("Adicionada no Gestor")).toBeTruthy();

    const history = screen.getByRole("heading", { name: "Histórico do roteiro" }).closest("section")!;
    expect(within(history).getByText("Maria PCP")).toBeTruthy();
    expect(within(history).getByText("Adicionou etapa")).toBeTruthy();
    expect(within(history).getByText("Peça saiu com rebarba")).toBeTruthy();
  });

  it("sem permissão do backend não há botão de adicionar nem de desativar", async () => {
    stubFetch(false);
    renderPage();
    await openOrder();
    expect(screen.queryByRole("button", { name: "Adicionar etapa" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Desativar etapa/ })).toBeNull();
  });

  it("adicionar etapa envia o POST com os dados do formulário", async () => {
    const mock = stubFetch(true, (path, init) => (path.endsWith("/order-consultation/OP-100/steps") && init?.method === "POST" ? json({ ok: true, item: { id: 4, numero_operacao: "G02" } }) : undefined));
    renderPage();
    await openOrder();

    fireEvent.click(screen.getByRole("button", { name: "Adicionar etapa" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Depois da operação"), { target: { value: "2" } });
    fireEvent.change(within(dialog).getByLabelText("Setor"), { target: { value: "Solda" } });
    fireEvent.change(within(dialog).getByLabelText("Recurso"), { target: { value: "SOLDA1" } });
    fireEvent.change(within(dialog).getByLabelText("Descrição da etapa"), { target: { value: "Soldar reforço" } });
    fireEvent.change(within(dialog).getByLabelText("Motivo"), { target: { value: "Cliente pediu reforço" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Adicionar etapa" }));

    await waitFor(() => expect(postCalls(mock)).toHaveLength(1));
    const [path, init] = postCalls(mock)[0];
    expect(String(path)).toBe("/api/v1/order-consultation/OP-100/steps");
    expect(JSON.parse(String((init as RequestInit).body))).toEqual({
      after_operation_id: 2, description: "Soldar reforço", resource_code: "SOLDA1", reason: "Cliente pediu reforço",
    });
    await screen.findByText(/Etapa adicionada ao roteiro/);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("desativar com apontamento mostra mensagem humana do 409, sem código técnico", async () => {
    const mock = stubFetch(true, (path, init) => (
      path.endsWith("/steps/3/deactivate") && init?.method === "POST"
        ? json({ code: "route_step_already_pointed", message: "mensagem crua do servidor" }, 409)
        : undefined
    ));
    renderPage();
    await openOrder();

    fireEvent.click(screen.getByRole("button", { name: /Desativar etapa G01/ }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Motivo"), { target: { value: "Não é mais necessária" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Desativar etapa" }));

    const alert = await screen.findByText("Esta etapa já tem apontamento e não pode ser desativada.");
    expect(alert).toBeTruthy();
    expect(screen.queryByText(/route_step_already_pointed/)).toBeNull();
    expect(JSON.parse(String((postCalls(mock)[0][1] as RequestInit).body))).toEqual({ reason: "Não é mais necessária" });
  });
});
