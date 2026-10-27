import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";
import { decisionLabel, rncErrorMessage } from "../pages/production/QualityRncDecisionPage";
import { ApiError } from "../api/client";
import type { RncListItem } from "../types/qualityRnc";

function json(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: { "content-type": "application/json" } });
}

const session = (role: string) => ({
  id: 1, name: `Conta ${role}`, role, assigned_level: role, management_access: true, andon_access: true, operator_access: false,
});

const rnc = (id: number, extra: Partial<RncListItem> = {}): RncListItem => ({
  id, codigo: `RNC-12-000${id}`, motivo: "cota fora", resultado_peca: "REFUGO", numero_peca: 1, op: "OP-1", produto: "PRD_X",
  recurso: "DOBRA1", criada_em: "2026-10-26T09:00:00", decisao_vigente: null, aviso: null, ...extra,
});

const AVISO = "A peça foi registrada como REFUGO na inspeção, mas a decisão é usar como está. A decisão foi gravada; confirme se é isso mesmo.";

function stub(user: ReturnType<typeof session>, items: RncListItem[]) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.includes("/auth/session")) return json(user);
    if (path.includes("/decisions") && init?.method === "POST") {
      return json({ ok: true, decisao: { id: 9, rnc_id: 1, decisao: "usar_como_esta", justificativa: "cliente aceitou", decidido_por_id: 1, decidido_por_nome: "Sandro", quando: "2026-10-27T10:00:00", vigente: true, aviso: AVISO }, resultado_peca: "REFUGO", aviso: AVISO });
    }
    if (path.includes("/decisions")) {
      return json({ rnc: { id: 1, codigo: "RNC-12-0001", resultado_peca: "REFUGO" }, vigente: null, items: [{ id: 5, rnc_id: 1, decisao: "retrabalhar", justificativa: "furo refeito", decidido_por_id: 1, decidido_por_nome: "Sandro", quando: "2026-10-26T15:00:00", vigente: true, aviso: null }] });
    }
    if (path.includes("/quality/rnc")) return json({ items, count: items.length });
    return json({ code: "not_found", message: "Não encontrado" }, 404);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

const renderAt = (route: string) =>
  render(<MemoryRouter initialEntries={[route]}><AuthProvider><App /></AuthProvider></MemoryRouter>);

const rncCalls = (mock: ReturnType<typeof stub>) => mock.mock.calls.filter(([path]) => String(path).includes("/quality/rnc"));

afterEach(() => vi.restoreAllMocks());

describe("Qualidade — decisão de RNC", () => {
  it("rótulos e mensagens de erro em português", () => {
    expect(decisionLabel("usar_como_esta")).toBe("Usar como está");
    expect(rncErrorMessage(new ApiError(403, { code: "quality_templates_access_denied", message: "x" }))).toContain("Só a Qualidade e a administração");
    expect(rncErrorMessage(new ApiError(404, { code: "quality_rnc_not_found", message: "x" }))).toContain("não existe mais");
    expect(rncErrorMessage(new ApiError(422, { code: "validation_error", message: "x" }))).toContain("justificativa");
  });

  it("Qualidade vê as RNCs sem decisão, registra e vê o aviso de contradição", async () => {
    const mock = stub(session("qualidade"), [rnc(1)]);
    renderAt("/qualidade/rnc");
    expect(await screen.findByText("RNC-12-0001")).toBeTruthy();
    expect(rncCalls(mock).some(([path]) => String(path).includes("somente_sem_decisao=true"))).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Decidir RNC-12-0001" }));
    const submit = await screen.findByRole("button", { name: "Registrar decisão" });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    expect(await screen.findByText(/furo refeito/)).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Decisão"), { target: { value: "usar_como_esta" } });
    fireEvent.change(screen.getByLabelText("Justificativa"), { target: { value: "cliente aceitou" } });
    expect((submit as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(submit);

    expect(await screen.findByText(/Decisão registrada\. Atenção:/)).toBeTruthy();
    const post = mock.mock.calls.find(([, init]) => init?.method === "POST")!;
    expect(String(post[0])).toContain("/quality/rnc/1/decisions");
    expect(JSON.parse(String(post[1]?.body))).toEqual({ decisao: "usar_como_esta", justificativa: "cliente aceitou" });
  });

  it("aba Todas pede a lista completa", async () => {
    const mock = stub(session("admin"), [rnc(1)]);
    renderAt("/qualidade/rnc");
    await screen.findByText("RNC-12-0001");
    fireEvent.click(screen.getByRole("tab", { name: "Todas" }));
    await waitFor(() => expect(rncCalls(mock).some(([path]) => String(path).includes("somente_sem_decisao=false"))).toBe(true));
  });

  it("gestão comum não monta a tela nem chama a API de RNC", async () => {
    const mock = stub(session("gestor"), [rnc(1)]);
    renderAt("/qualidade/rnc");
    expect(await screen.findByText(/exclusiva da Qualidade e da administração/)).toBeTruthy();
    expect(rncCalls(mock)).toHaveLength(0);
  });
});
