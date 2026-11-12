import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";

// "Finalizar Ret." (20/10/2026): no estado Retrabalho o botao "Retrabalho" vira
// "Finalizar Ret." e pergunta boas e refugo (campo vazio vale 0). Encerra o
// retrabalho e a OP volta a Em processo; o botao "Finalizar" nao muda.

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

const gateNaoAplicavel = {
  aplicavel: false, liberado: true, status: "CONFORME", peca_produzida: false,
  setup_obrigatorio: false, setup_registrado: false, inspecao_concluida: false,
  bloqueio_ativo: false, gate_estruturado: false, code: "", message: "", pendencias: [],
};

function mockWorkbench(status: string) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    if (path.includes("/auth/session")) return json({ id: 2, name: "Operador", role: "operador_dobra", management_access: false, operator_access: true, operator_sector: "Dobra", operator_resources: ["1303"] });
    if (path.includes("/operator/context")) return json({ sector: "Dobra", route: "Dobra", resources: ["1303"], fixed_resource: true, has_setup: false, automatic_queue: false, workflow: "workbench" });
    if (path.includes("/operator/stop-reasons")) return json({ items: [] });
    if (path.includes("/operator/operators")) return json({ items: [{ id: 1, cracha: "123", nome: "Ana", ativo: true }] });
    if (path.includes("/operator/history")) return json({ items: [], has_more: false });
    if (path.includes("/operator/workbench")) return json({ sector: "Dobra", resource: "1303", queue: [], team: [{ cracha: "123", nome: "Ana" }], production: [{ id: 10, op: "OP-RET", status, operation: "10 - DOBRA", numero_operacao: "10", product: "P1", qty: 5, good: 0, scrap: 0, attended: 0, balance: 5 }] });
    if (path.includes("/operator/drawings")) return json({ available: false, message: "Nenhum desenho disponível." });
    if (path.includes("/operator/operations/OP-RET")) return json({ items: [{ id: 10, numero_operacao: "10", descricao_operacao: "DOBRA", visual_status: "current", visual_current: true, actionable: true, selectable: true, requires_confirmation: false, quantidade_planejada: 5, pode_finalizar: true, exige_gate_primeira_peca: false, primeira_peca: gateNaoAplicavel }] });
    if (path.includes("/operator/actions") && method === "POST") return json({ ok: true, message: "Retrabalho finalizado. Produção retomada.", data: { status: "Em processo" } });
    return json({ code: "not_found", message: "Não encontrado" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

async function abrirOp() {
  render(<MemoryRouter initialEntries={["/operador"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
  await screen.findByText("1303");
  fireEvent.change(screen.getByLabelText("Código da OP"), { target: { value: "OP-RET" } });
  fireEvent.click(screen.getByRole("button", { name: "Carregar roteiro" }));
  await screen.findByRole("button", { name: "10 - DOBRA — Atual" });
}

function postedAction(fetchMock: ReturnType<typeof mockWorkbench>) {
  const call = fetchMock.mock.calls.find(([path, init]) => String(path).includes("/operator/actions") && init?.method === "POST");
  return call ? JSON.parse(String(call[1]?.body)) : undefined;
}

async function abrirPopup(fetchMock: ReturnType<typeof mockWorkbench>) {
  void fetchMock;
  await abrirOp();
  const botao = await screen.findByRole("button", { name: "Finalizar Ret." });
  await waitFor(() => expect(botao).toBeEnabled());
  fireEvent.click(botao);
  await screen.findByRole("heading", { name: "Finalizar retrabalho" });
}

describe("Finalizar Ret. no posto do operador", () => {
  it("fora do Retrabalho o botão segue Retrabalho e o Finalizar não muda", async () => {
    mockWorkbench("Em processo");
    await abrirOp();
    expect(await screen.findByRole("button", { name: "Finalizar" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Retrabalho" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Finalizar Ret." })).not.toBeInTheDocument();
  });

  it("em Retrabalho o botão Retrabalho vira Finalizar Ret. e o Finalizar continua igual", async () => {
    mockWorkbench("Retrabalho");
    await abrirOp();
    expect(await screen.findByRole("button", { name: "Finalizar Ret." })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Finalizar" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retrabalho" })).not.toBeInTheDocument();
  });

  it("não pede peças (12/11/2026): só encerra o retrabalho, com quem está no card", async () => {
    const fetchMock = mockWorkbench("Retrabalho");
    await abrirPopup(fetchMock);
    expect(screen.queryByLabelText("Peças boas (recuperadas)")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Peças para refugo")).not.toBeInTheDocument();
    expect(screen.getByText("Quem trabalhou: Ana (123).")).toBeInTheDocument();
    expect(screen.queryByLabelText("Crachá do operador")).not.toBeInTheDocument();
  });

  it("confirmar envia 0/0 e só encerra o retrabalho", async () => {
    const fetchMock = mockWorkbench("Retrabalho");
    await abrirPopup(fetchMock);
    const confirmar = screen.getByRole("button", { name: "Confirmar" });
    await waitFor(() => expect(confirmar).toBeEnabled());
    fireEvent.click(confirmar);

    await waitFor(() => expect(postedAction(fetchMock)).toBeDefined());
    expect(postedAction(fetchMock)).toMatchObject({ action: "Finalizar Retrabalho", good: 0, scrap: 0 });
    expect(postedAction(fetchMock).badges).toBeUndefined();
  });
});
