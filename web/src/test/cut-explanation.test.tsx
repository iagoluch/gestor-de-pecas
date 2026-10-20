import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FilterProvider } from "../filters/FilterContext";
import { TraceabilityNestingPage } from "../pages/traceability/TraceabilityPages";

const NESTINGS = {
  items: [{ apontamento_id: 1, tarefa: "T1", programa: "P1", nesting: 1, maquina: "LASER1", previsto_segundos: 3600, real_segundos: 4200, real_periodo_segundos: 4200 }],
  count: 1,
  page: 1,
  // totais do filtro inteiro (maiores que a página): os cartões têm de usar estes
  totals: { previsto_segundos: 7200, real_segundos: 9000, real_periodo_segundos: 9000 },
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function explanation(metric: string) {
  return {
    kind: "value", metric, label: `Explicação ${metric}`, unit: "hours", value: 2,
    reason: "Teste.", rule: "Regra.", children: [], excluded: [],
    reconciliation: { ok: true, sum: 2, diff: 0 }, calculated_at: "2026-10-20T14:00:00", truncated: false, notes: [],
  };
}

function stub(explainStatus = 200) {
  const mock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.includes("/management/explicacao")) {
      if (explainStatus !== 200) return json({ code: "forbidden", message: "Sem acesso" }, explainStatus);
      return json(explanation(new URL(path, "http://x").searchParams.get("metric") ?? ""));
    }
    if (path.includes("/traceability/nestings")) return json(NESTINGS);
    return json({ code: "not_found", message: "Não encontrado" }, 404);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function explainUrls(mock: ReturnType<typeof stub>) {
  return mock.mock.calls.map((call) => String((call as unknown[])[0])).filter((url) => url.includes("/management/explicacao"));
}

function mount() {
  render(<MemoryRouter><FilterProvider><TraceabilityNestingPage /></FilterProvider></MemoryRouter>);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Corte: cartões de nesting clicáveis", () => {
  it("os quatro cartões abrem cut.* e a tela usa os totais do servidor", async () => {
    const mock = stub();
    mount();
    for (const [name, metric] of [
      [/Ver de onde vem este número: Nestings no filtro/, "cut.nestings"],
      [/Ver de onde vem este número: Tempo previsto/, "cut.previsto"],
      [/Ver de onde vem este número: Tempo realizado/, "cut.realizado"],
      [/Ver de onde vem este número: Desvio do previsto/, "cut.desvio"],
    ] as const) {
      fireEvent.click(await screen.findByRole("button", { name }));
      await screen.findByRole("dialog");
      await waitFor(() => expect(explainUrls(mock).some((url) => url.includes(`metric=${metric}`))).toBe(true));
      fireEvent.click(screen.getByRole("button", { name: "Fechar explicação" }));
      await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    }
    // 7200 s previstos = 02:00:00 (total do servidor), não 01:00:00 (só a página)
    expect(screen.getByRole("button", { name: /Tempo previsto/ })).toHaveTextContent("02:00:00");
  });

  it("a explicação não leva setor, OP, operação, produto nem operador", async () => {
    const mock = stub();
    mount();
    fireEvent.click(await screen.findByRole("button", { name: /Ver de onde vem este número: Nestings no filtro/ }));
    await waitFor(() => expect(explainUrls(mock).length).toBeGreaterThan(0));
    const url = new URL(explainUrls(mock)[0], "http://x");
    for (const key of ["setor", "op", "operacao", "produto", "operador"]) expect(url.searchParams.get(key) ?? "").toBe("");
  });

  it("enquanto a busca tem texto, os cartões viram texto simples", async () => {
    stub();
    mount();
    await screen.findByRole("button", { name: /Ver de onde vem este número: Nestings no filtro/ });
    fireEvent.change(screen.getByPlaceholderText("Buscar tarefa, material ou nesting"), { target: { value: "T1" } });
    await waitFor(() => expect(screen.queryByRole("button", { name: /Ver de onde vem este número: Nestings no filtro/ })).not.toBeInTheDocument());
  });

  it("recusa 403 mostra mensagem de acesso", async () => {
    stub(403);
    mount();
    fireEvent.click(await screen.findByRole("button", { name: /Ver de onde vem este número: Nestings no filtro/ }));
    expect(await screen.findByText("Você não tem acesso a esta explicação.")).toBeInTheDocument();
  });
});
