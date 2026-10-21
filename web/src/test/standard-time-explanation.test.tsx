import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";

const BASE = {
  produto_codigo: "PROD-1",
  numero_operacao: "10",
  codigo_recurso: "DOBRA01",
  tipo_setor: "Dobra",
  produto_descricao: "Suporte lateral",
  descricao_operacao: "Dobrar aba",
  tempo_protheus_segundos: null,
  tempo_manual_segundos: null,
  tempo_estimado_segundos: null,
  fonte_efetiva: null,
};
const PROTHEUS = { ...BASE, produto_codigo: "PROD-3", tempo_protheus_segundos: 30, fonte_efetiva: "protheus" };
const ESTIMADA = { ...BASE, produto_codigo: "PROD-2", tempo_estimado_segundos: 62.5, estimado_amostras: 7, fonte_efetiva: "estimado" };
const MANUAL = {
  ...BASE,
  produto_codigo: "PROD-4",
  tempo_manual_segundos: 45,
  manual_alterado_por: "Ana",
  manual_alterado_em: "2026-10-01T08:00:00",
  manual_vigente_desde: "2026-10-02T00:00:00",
  fonte_efetiva: "manual",
};

function json(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: { "content-type": "application/json" } });
}

function explanation(metric: string) {
  return {
    kind: "value", metric, label: `Explicação ${metric}`, unit: "seconds", value: 30, reason: "Teste.", rule: "Regra de teste.",
    children: [], excluded: [], reconciliation: { ok: true, sum: 30, diff: 0 },
    calculated_at: "2026-10-20T14:00:00", truncated: false, notes: [],
  };
}

function stub(explainStatus = 200, rows: Record<string, unknown>[] = [PROTHEUS, ESTIMADA, MANUAL]) {
  const mock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.includes("/auth/session")) {
      return json({ id: 1, name: "Conta manufatura", role: "manufatura", management_access: true, andon_access: true, operator_access: false });
    }
    if (path.includes("/management/explicacao")) {
      if (explainStatus !== 200) return json({ code: explainStatus === 403 ? "standard_time_access_denied" : "internal_error", message: "Falha" }, explainStatus);
      return json(explanation(new URL(path, "http://x").searchParams.get("metric") ?? ""));
    }
    if (path.includes("/management/standard-times?")) {
      const items = rows;
      return json({ items, total: items.length, sem_produto: 0, limit: 100, offset: 0, somente_sem_padrao: false });
    }
    return json({ code: "not_found", message: "Não encontrado" }, 404);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/manufatura/tempo-padrao"]}>
      <AuthProvider><App /></AuthProvider>
    </MemoryRouter>,
  );
}

const explainUrls = (mock: ReturnType<typeof stub>) =>
  mock.mock.calls.map((call) => String((call as unknown[])[0])).filter((url) => url.includes("/management/explicacao"));

async function clickAndExpect(mock: ReturnType<typeof stub>, name: RegExp, expected: string[]) {
  fireEvent.click(await screen.findByRole("button", { name }));
  await screen.findByRole("dialog");
  await waitFor(() => expect(explainUrls(mock).some((url) => expected.every((part) => url.includes(part)))).toBe(true));
  fireEvent.click(screen.getByRole("button", { name: "Fechar explicação" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
}

beforeEach(() => {
  document.cookie = "gestor_csrf=csrf-teste; path=/";
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Tempo padrão: números clicáveis", () => {
  it("Protheus, estimado, manual e fonte abrem std.* com a chave da linha", async () => {
    const mock = stub();
    renderPage();
    const key = ["produto=PROD-3", "operacao=10", "recurso=DOBRA01"];
    await clickAndExpect(mock, /Ver de onde vem este número: Tempo Protheus 30 s/, ["metric=std.protheus", ...key]);
    await clickAndExpect(mock, /Ver de onde vem este número: Tempo estimado 62,5 s/, ["metric=std.estimado", "produto=PROD-2"]);
    await clickAndExpect(mock, /Ver de onde vem este número: Tempo manual 45 s/, ["metric=std.manual", "produto=PROD-4"]);
    await clickAndExpect(mock, /Ver de onde vem este número: Fonte em uso: PROD-3, operação 10, recurso DOBRA01/, ["metric=std.fonte", ...key]);
  });

  it("o último recálculo abre std.recalculo sem chave de linha", async () => {
    const mock = stub();
    renderPage();
    await clickAndExpect(mock, /Ver de onde vem este número: último recálculo/, ["metric=std.recalculo"]);
    expect(explainUrls(mock).every((url) => !url.includes("produto="))).toBe(true);
  });

  it("linha sem tempo cadastrado não vira botão de Protheus nem de estimado", async () => {
    stub();
    renderPage();
    await screen.findByRole("button", { name: /Tempo Protheus 30 s/ });
    expect(screen.getAllByRole("button", { name: /Tempo Protheus/ })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: /Tempo estimado/ })).toHaveLength(1);
  });

  it("recusa 403 mostra mensagem de acesso, sem expor erro técnico", async () => {
    stub(403);
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /Tempo Protheus 30 s/ }));
    expect(await screen.findByText("Você não tem acesso a esta explicação.")).toBeInTheDocument();
  });

  it("falha 500 oferece tentar de novo e refaz a chamada", async () => {
    const mock = stub(500);
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /Tempo Protheus 30 s/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Tentar novamente" }));
    await waitFor(() => expect(explainUrls(mock).length).toBeGreaterThanOrEqual(2));
  });

  it("código de produto com & / % e espaço vai codificado na URL, sem quebrar a chave", async () => {
    const mock = stub(200, [{ ...PROTHEUS, produto_codigo: "A&B/1 %x" }]);
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /Tempo Protheus 30 s/ }));
    await screen.findByRole("dialog");
    await waitFor(() => expect(explainUrls(mock).length).toBeGreaterThan(0));
    const url = new URL(explainUrls(mock)[0], "http://x");
    expect(url.searchParams.get("produto")).toBe("A&B/1 %x");
    expect(url.searchParams.get("metric")).toBe("std.protheus");
    expect(url.searchParams.get("recurso")).toBe("DOBRA01");
  });
});
