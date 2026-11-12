import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";

// Card "Pessoas no recurso" (12/11/2026): o crachá é pedido ao iniciar, o "+"
// põe mais uma pessoa e o "×" tira; a finalização usa quem está no card.

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

const gate = {
  aplicavel: false, liberado: true, status: "CONFORME", peca_produzida: false,
  setup_obrigatorio: false, setup_registrado: false, inspecao_concluida: false,
  bloqueio_ativo: false, gate_estruturado: false, code: "", message: "", pendencias: [],
};

function mockPosto({ team, production }: { team: { cracha: string; nome: string }[]; production: unknown[] }) {
  let actionCalls = 0;
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    if (path.includes("/auth/session")) return json({ id: 2, name: "Operador", role: "operador_dobra", management_access: false, operator_access: true, operator_sector: "Dobra", operator_resources: ["1303"] });
    if (path.includes("/operator/context")) return json({ sector: "Dobra", route: "Dobra", resources: ["1303"], fixed_resource: true, has_setup: false, automatic_queue: false, workflow: "workbench" });
    if (path.includes("/operator/stop-reasons")) return json({ items: [] });
    if (path.includes("/operator/operators")) return json({ items: [{ id: 1, cracha: "123", nome: "Ana", ativo: true }, { id: 2, cracha: "456", nome: "Bruno", ativo: true }] });
    if (path.includes("/operator/history")) return json({ items: [], has_more: false });
    if (path.includes("/operator/workbench")) return json({ sector: "Dobra", resource: "1303", queue: [], team, production });
    if (path.includes("/operator/drawings")) return json({ available: false, message: "Nenhum desenho disponível." });
    if (path.includes("/operator/operations/OP-NOVA")) return json({ items: [{ id: 10, numero_operacao: "10", descricao_operacao: "DOBRA", visual_status: "current", visual_current: true, actionable: true, selectable: true, requires_confirmation: false, quantidade_planejada: 5, pode_finalizar: false, exige_gate_primeira_peca: false, primeira_peca: gate }] });
    if (path.includes("/operator/team") && method === "POST") return json({ ok: true, message: "Equipe atualizada.", team });
    if (path.includes("/operator/actions") && method === "POST") {
      actionCalls += 1;
      const body = JSON.parse(String(init?.body));
      if (!body.badges?.length) return json({ code: "cracha_obrigatorio_inicio", message: "Informe o crachá de quem vai trabalhar neste início." }, 409);
      return json({ ok: true, message: "Iniciado." });
    }
    return json({ code: "not_found", message: "Não encontrado" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, actionCalls: () => actionCalls };
}

function posts(fetchMock: ReturnType<typeof vi.fn>, endpoint: string) {
  return fetchMock.mock.calls
    .filter(([path, init]) => String(path).includes(endpoint) && (init as RequestInit | undefined)?.method === "POST")
    .map(([, init]) => JSON.parse(String((init as RequestInit).body)));
}

function renderPosto() {
  render(<MemoryRouter initialEntries={["/operador"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
}

const emProcesso = { id: 10, op: "OP-NOVA", status: "Em processo", operation: "10 - DOBRA", numero_operacao: "10", product: "P1", qty: 5, good: 0, scrap: 0, attended: 0, balance: 5 };

describe("Card Pessoas no recurso", () => {
  it("mostra quem está no recurso, adiciona com + e remove com ×", async () => {
    const { fetchMock } = mockPosto({ team: [{ cracha: "123", nome: "Ana" }], production: [emProcesso] });
    renderPosto();
    const card = await screen.findByRole("region", { name: "Pessoas no recurso" });
    await within(card).findByText("Ana");

    fireEvent.change(within(card).getByLabelText("Adicionar crachá"), { target: { value: "456" } });
    fireEvent.click(within(card).getByRole("button", { name: "Adicionar pessoa" }));
    await waitFor(() => expect(posts(fetchMock, "/operator/team")).toHaveLength(1));
    expect(posts(fetchMock, "/operator/team")[0]).toEqual({ resource: "1303", badge: "456", action: "add" });

    fireEvent.click(within(card).getByRole("button", { name: "Remover Ana" }));
    await waitFor(() => expect(posts(fetchMock, "/operator/team")).toHaveLength(2));
    expect(posts(fetchMock, "/operator/team")[1]).toEqual({ resource: "1303", badge: "123", action: "remove" });
  });

  it("crachá não cadastrado não chega ao servidor", async () => {
    const { fetchMock } = mockPosto({ team: [{ cracha: "123", nome: "Ana" }], production: [emProcesso] });
    renderPosto();
    const card = await screen.findByRole("region", { name: "Pessoas no recurso" });
    await within(card).findByText("Ana");
    fireEvent.change(within(card).getByLabelText("Adicionar crachá"), { target: { value: "999" } });
    fireEvent.click(within(card).getByRole("button", { name: "Adicionar pessoa" }));
    expect(await within(card).findByText("Crachá não cadastrado ou inativo.")).toBeInTheDocument();
    expect(posts(fetchMock, "/operator/team")).toHaveLength(0);
  });

  it("sem ninguém no recurso, Iniciar pede o crachá e reenvia com ele", async () => {
    const { fetchMock } = mockPosto({ team: [], production: [] });
    renderPosto();
    const card = await screen.findByRole("region", { name: "Pessoas no recurso" });
    expect(within(card).getByText("O crachá é pedido ao iniciar.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Código da OP"), { target: { value: "OP-NOVA" } });
    fireEvent.click(screen.getByRole("button", { name: "Carregar roteiro" }));
    await screen.findByRole("button", { name: "10 - DOBRA — Atual" });
    const iniciar = await screen.findByRole("button", { name: "Iniciar" });
    await waitFor(() => expect(iniciar).toBeEnabled());
    fireEvent.click(iniciar);

    const dialog = await screen.findByRole("dialog", { name: /Quem vai trabalhar/ });
    const confirmar = within(dialog).getByRole("button", { name: "Confirmar" });
    expect(confirmar).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Crachá"), { target: { value: "123" } });
    fireEvent.keyDown(within(dialog).getByLabelText("Crachá"), { key: "Enter" });
    await within(dialog).findByText("Ana");
    await waitFor(() => expect(confirmar).toBeEnabled());
    fireEvent.click(confirmar);

    await waitFor(() => expect(posts(fetchMock, "/operator/actions")).toHaveLength(2));
    expect(posts(fetchMock, "/operator/actions")[1]).toMatchObject({ badges: ["123"] });
  });
});
