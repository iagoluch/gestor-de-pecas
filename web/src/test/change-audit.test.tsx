import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";
import { changeLines, fieldValue } from "../pages/home/ChangeAuditPage";
import type { ChangeAuditEntry } from "../types/changeAudit";

function json(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: { "content-type": "application/json" } });
}

const session = (role: string) => ({
  id: 1, name: `Conta ${role}`, role, assigned_level: role, management_access: true, andon_access: true, operator_access: false,
});

const entry = (id: number, extra: Partial<ChangeAuditEntry> = {}): ChangeAuditEntry => ({
  id, quando: "2026-10-27T09:30:00", usuario_id: 1, usuario_nome: "Admin Teste", entidade: "usuario", chave: "7",
  acao: "alterar", antes: { nome: "Ana", ativo: true }, depois: { nome: "Ana", ativo: false }, ...extra,
});

function stub(user: ReturnType<typeof session>, items: ChangeAuditEntry[]) {
  const mock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.includes("/auth/session")) return json(user);
    if (path.includes("/management/audit")) return json({ items, count: items.length });
    return json({ code: "not_found", message: "Não encontrado" }, 404);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

const renderAt = (route: string) =>
  render(<MemoryRouter initialEntries={[route]}><AuthProvider><App /></AuthProvider></MemoryRouter>);

const auditCalls = (mock: ReturnType<typeof stub>) =>
  mock.mock.calls.filter(([path]) => String(path).includes("/management/audit"));

afterEach(() => vi.restoreAllMocks());

describe("Alterações — quem mudou o quê", () => {
  it("mostra só os campos que mudaram, em português", () => {
    expect(changeLines(entry(1))).toEqual(["Ativo: Sim → Não"]);
    expect(changeLines(entry(2, { acao: "criar", antes: null, depois: { nome: "Turno A", ativo: true } }))).toEqual(["Nome: Turno A", "Ativo: Sim"]);
    expect(changeLines(entry(3, { acao: "excluir", depois: null, antes: { nome: "Pausa 1" } }))).toEqual(["Nome: Pausa 1"]);
    expect(fieldValue(null)).toBe("vazio");
  });

  it("admin vê a lista; filtrar manda os parâmetros e nunca pede R$", async () => {
    const mock = stub(session("admin"), [entry(1), entry(2, { entidade: "rnc_decisao", chave: "RNC-9", acao: "criar", antes: null, depois: { decisao: "retrabalhar", justificativa: "Furo fora de medida" } })]);
    renderAt("/inicio/alteracoes");
    expect(await screen.findByText("Usuário · 7")).toBeTruthy();
    expect(screen.getByText("Decisão de RNC · RNC-9")).toBeTruthy();
    expect(screen.getByText("Ativo: Sim → Não")).toBeTruthy();
    expect(screen.getByText("Justificativa: Furo fora de medida")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("O quê"), { target: { value: "turno" } });
    fireEvent.change(screen.getByLabelText("Quem"), { target: { value: "Ana" } });
    fireEvent.click(screen.getByRole("button", { name: "Filtrar" }));
    await waitFor(() => expect(auditCalls(mock).some(([path]) => String(path).includes("entidade=turno") && String(path).includes("usuario=Ana"))).toBe(true));
    expect(auditCalls(mock).every(([path]) => !String(path).includes("custo"))).toBe(true);
  });

  it("gestão comum não monta a tela nem chama a API", async () => {
    const mock = stub(session("gestor"), [entry(1)]);
    renderAt("/inicio/alteracoes");
    expect(await screen.findByText("Acesso restrito ao administrador")).toBeTruthy();
    expect(auditCalls(mock)).toHaveLength(0);
  });
});
