import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ExplainableValue } from "../components/ExplainableValue";
import { MetricExplanationPanel } from "../components/MetricExplanationPanel";
import { LocalExplanationPanel } from "../components/ValueExplanationPanel";
import { defaultFilters, FilterProvider } from "../filters/FilterContext";
import { ProductionOrdersPage, ProductionPlanActualPage } from "../pages/production/ProductionPages";
import {
  buildAttendanceExplanation,
  buildSumExplanation,
  sumQuantities,
  type QuantityRow,
} from "../pages/production/productionExplanations";
import { isValueExplanation, type ValueExplanation } from "../types/valueExplanation";

afterEach(() => vi.restoreAllMocks());

const FILTERS = { ...defaultFilters(new Date(2026, 9, 19, 10, 0)) };

function respond(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function serverValue(overrides: Partial<ValueExplanation> = {}): ValueExplanation {
  return {
    kind: "value",
    metric: "qtd.refugo",
    label: "Refugo",
    unit: "pcs",
    value: 12,
    reason: "Peças apontadas como refugo no período.",
    rule: "Refugo = soma dos eventos de refugo do período.",
    children: [
      {
        kind: "sector", label: "Corte", value: 9, truncated: false, detail: null,
        children: [{
          kind: "resource", label: "LASER1", value: 9, truncated: false, detail: null,
          children: [{
            kind: "event", label: "07:30 · OP 123", value: 9, truncated: false, children: [],
            detail: { id: "evt:77", op: "123", motivo: "Rebarba", operador: null },
          }],
        }],
      },
      { kind: "sector", label: "Solda", value: 3, truncated: false, detail: null, children: [] },
    ],
    excluded: [{ label: "Retrabalho", value: 4, reason: "Não conta como refugo." }],
    reconciliation: { ok: true, sum: 12, diff: 0 },
    calculated_at: "2026-10-19T14:02:11",
    truncated: false,
    notes: ["A taxa de refugo ignora retrabalho; o FTT inclui."],
    ...overrides,
  };
}

const ROWS: QuantityRow[] = [
  { op: "OP1", operacao: 10, produto: "P-1", recurso_real: "LASER1", quantidade_planejada: 100, quantidade_boa: 60, refugo: 5, retrabalho: 3 },
  { op: "OP2", operacao: 20, quantidade_planejada: 50, quantidade_boa: 50, refugo: 2, retrabalho: 0 },
  { op: "OP3", operacao: 10, quantidade_planejada: 10, quantidade_boa: 1, refugo: 0, retrabalho: 1, saldo_quantidade: 9 },
];

describe("ValueExplanationPanel (painel local)", () => {
  it("mostra valor, motivo, regra, árvore expansível, o que ficou de fora e a conferência", () => {
    render(<LocalExplanationPanel explanation={serverValue()} onClose={vi.fn()} />);
    const dialog = screen.getByRole("dialog", { name: "Refugo" });

    expect(within(dialog).getByTestId("explanation-total")).toHaveTextContent("12");
    expect(dialog).toHaveTextContent("Peças apontadas como refugo no período.");
    expect(dialog).toHaveTextContent("Refugo = soma dos eventos de refugo do período.");
    expect(dialog).toHaveTextContent("(Retrabalho 4: Não conta como refugo.)");
    expect(dialog).toHaveTextContent("A taxa de refugo ignora retrabalho; o FTT inclui.");
    expect(dialog).toHaveTextContent("os itens somam 12, igual ao número clicado");
    expect(dialog).toHaveTextContent("calculado às 14:02");
    expect(within(dialog).queryByRole("alert")).not.toBeInTheDocument();
    // Não é painel de servidor: sem chat de IA.
    expect(within(dialog).queryByTestId("explanation-chat-slot")).not.toBeInTheDocument();

    expect(within(dialog).queryByRole("button", { name: /LASER1/ })).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: /Corte/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: /LASER1/ }));
    expect(dialog).not.toHaveTextContent("evt:77");
    fireEvent.click(within(dialog).getByRole("button", { name: /07:30 · OP 123/ }));
    expect(dialog).toHaveTextContent("evt:77");
    expect(dialog).toHaveTextContent("Rebarba");
    // Campo nulo não é inventado.
    expect(dialog).not.toHaveTextContent("Operador");
  });

  it("avisa em vermelho quando a conta não fecha e quando a lista foi cortada", () => {
    render(<LocalExplanationPanel
      explanation={serverValue({ truncated: true, reconciliation: { ok: false, sum: 10, diff: 2 } })}
      onClose={vi.fn()}
    />);
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("alert")).toHaveTextContent("os itens somam 10, mas o número clicado é 12 (diferença de 2)");
    expect(dialog).toHaveTextContent("A lista foi cortada por tamanho");
  });

  it("formata taxas (entradas em peças) e dinheiro sem NaN", () => {
    const rate = serverValue({
      metric: "qtd.taxa_refugo", label: "Taxa de refugo", unit: "pct", value: 4.8,
      children: [
        { kind: "input", label: "Refugo", value: 12, children: [], detail: null, truncated: false },
        { kind: "input", label: "Boa + refugo", value: 250, children: [], detail: null, truncated: false },
      ],
      excluded: [], reconciliation: { ok: true, sum: 4.8, diff: 0 },
    });
    const { unmount } = render(<LocalExplanationPanel explanation={rate} onClose={vi.fn()} />);
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByTestId("explanation-total")).toHaveTextContent("4,8%");
    expect(dialog).toHaveTextContent("12");
    expect(dialog).toHaveTextContent("250");
    expect(dialog).toHaveTextContent("refazendo a conta com as entradas dá 4,8%");
    unmount();

    // O que ficou de fora de uma taxa é quantidade de peças, nunca percentual.
    const withExcluded = serverValue({
      ...rate,
      excluded: [{ label: "Retrabalho", value: 4, reason: "Não conta como refugo." }],
    });
    render(<LocalExplanationPanel explanation={withExcluded} onClose={vi.fn()} />);
    expect(screen.getByRole("dialog")).toHaveTextContent("(Retrabalho 4: Não conta como refugo.)");
    expect(screen.getByRole("dialog")).not.toHaveTextContent("4%");
    cleanup();

    render(<LocalExplanationPanel explanation={serverValue({ unit: "brl", value: 1234.5, children: [], excluded: [], notes: [] })} onClose={vi.fn()} />);
    expect(screen.getByTestId("explanation-total").textContent).toMatch(/R\$\s?1\.234,50/);
    expect(document.body).not.toHaveTextContent("NaN");
  });
});

describe("MetricExplanationPanel com resposta kind:value", () => {
  it("renderiza o corpo de valor e mantém o chat", async () => {
    const fetchMock = vi.fn(async () => respond(serverValue()));
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter><MetricExplanationPanel metric="qtd.refugo" filters={FILTERS} onClose={vi.fn()} /></MemoryRouter>);
    const dialog = await screen.findByRole("dialog", { name: "Refugo" });
    expect(await within(dialog).findByTestId("explanation-total")).toHaveTextContent("12");
    expect(dialog).toHaveTextContent("os itens somam 12");
    expect(within(dialog).getByTestId("explanation-chat-slot")).toBeInTheDocument();
    expect(String((fetchMock.mock.calls[0] as unknown[])[0])).toContain("/api/v1/management/explicacao?metric=qtd.refugo");
    expect(isValueExplanation(serverValue())).toBe(true);
  });
});

describe("productionExplanations (soma no navegador)", () => {
  it("a soma das linhas é o número do cartão, para cada métrica", () => {
    const totals = sumQuantities(ROWS);
    expect(totals).toMatchObject({ planned: 160, good: 111, scrap: 7, rework: 4, attended: 118 });
    // Saldo: OP1 = 35, OP2 = max(0, 50−50−2) = 0, OP3 = 9 (vem do backend).
    expect(totals.balance).toBe(44);

    const expectations = { planned: 160, good: 111, scrap: 7, rework: 4, attended: 118, balance: 44, losses: 11 } as const;
    for (const [metric, expected] of Object.entries(expectations)) {
      const built = buildSumExplanation(metric as keyof typeof expectations, { rows: ROWS, filterTotal: 3 });
      expect(built.value).toBe(expected);
      expect(built.children).toHaveLength(3);
      expect(built.children.reduce((acc, node) => acc + Number(node.value), 0)).toBe(expected);
      expect(built.reconciliation).toEqual({ ok: true, sum: expected, diff: 0 });
      expect(built.notes.join(" ")).not.toContain("linhas carregadas");
    }
  });

  it("uma linha por OP com valor da coluna e só o que existe no detail", () => {
    const built = buildSumExplanation("good", { rows: ROWS, filterTotal: 3, now: new Date(2026, 9, 19, 9, 5, 7) });
    expect(built.children.map((node) => [node.label, node.value])).toEqual([["OP OP1 · op. 10", 60], ["OP OP2 · op. 20", 50], ["OP OP3 · op. 10", 1]]);
    expect(built.children[0].detail).toEqual({ produto: "P-1", recurso: "LASER1" });
    expect(built.children[1].detail).toBeNull();
    expect(built.calculated_at).toBe("2026-10-19T09:05:07");
  });

  it("sempre avisa 'Soma das N linhas carregadas; o filtro tem M no total' quando N < M", () => {
    const built = buildSumExplanation("planned", { rows: ROWS, filterTotal: 350 });
    expect(built.notes).toContain("Soma das 3 linhas carregadas; o filtro tem 350 no total.");
    const attendance = buildAttendanceExplanation({ rows: ROWS, filterTotal: 350 });
    expect(attendance.notes).toContain("Soma das 3 linhas carregadas; o filtro tem 350 no total.");
  });

  it("% atendida = atendida ÷ planejada, com as duas somas como entradas", () => {
    const built = buildAttendanceExplanation({ rows: ROWS, filterTotal: 3 });
    expect(built.unit).toBe("pct");
    expect(built.value).toBeCloseTo((118 / 160) * 100, 6);
    expect(built.children.map((node) => [node.kind, node.value])).toEqual([["input", 118], ["input", 160]]);
    expect(built.reconciliation.ok).toBe(true);
  });
});

describe("ExplainableValue", () => {
  it("é um botão acessível que abre o painel local ao clicar", () => {
    render(<ExplainableValue local={serverValue()} context="Refugo 12">12</ExplainableValue>);
    const button = screen.getByRole("button", { name: "Ver de onde vem este número: Refugo 12" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(button);
    expect(screen.getByRole("dialog", { name: "Refugo" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Fechar explicação" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("sem contexto usa o texto padrão e, com metric+filters, busca no servidor", async () => {
    const fetchMock = vi.fn(async () => respond(serverValue()));
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter><ExplainableValue metric="qtd.refugo" filters={FILTERS}>12</ExplainableValue></MemoryRouter>);
    fireEvent.click(screen.getByRole("button", { name: "Ver de onde vem este número" }));
    const dialog = await screen.findByRole("dialog", { name: "Refugo" });
    await within(dialog).findByTestId("explanation-total");
    expect(String((fetchMock.mock.calls[0] as unknown[])[0])).toContain("metric=qtd.refugo");
  });
});

describe("Produção: cartões somados no navegador", () => {
  const items = ROWS.map((row, index) => ({ apontamento_id: index + 1, status: "Em andamento", ...row }));

  function renderPage(page: "orders" | "plan", total: number) {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes("/api/v1/orders?") || path.includes("/planned-vs-actual")) {
        return respond({ periodo: {}, availability: "disponivel", items, page: { page: 1, page_size: 200, total } });
      }
      return respond({});
    });
    vi.stubGlobal("fetch", fetchMock);
    render(
      <MemoryRouter>
        <FilterProvider>{page === "orders" ? <ProductionOrdersPage /> : <ProductionPlanActualPage />}</FilterProvider>
      </MemoryRouter>,
    );
    return fetchMock;
  }

  it("clicar na quantidade planejada abre a soma por OP com a nota de truncamento", async () => {
    renderPage("orders", 350);
    const button = await screen.findByRole("button", { name: "Ver de onde vem este número: Quantidade planejada 160" });
    expect(button).toHaveTextContent("160");
    fireEvent.click(button);

    const dialog = await screen.findByRole("dialog", { name: "Quantidade planejada" });
    expect(within(dialog).getByTestId("explanation-total")).toHaveTextContent("160");
    expect(dialog).toHaveTextContent("Soma das 3 linhas carregadas; o filtro tem 350 no total.");
    expect(dialog).toHaveTextContent("os itens somam 160, igual ao número clicado");
    expect(dialog).toHaveTextContent("OP OP1 · op. 10");
  });

  it("saldo a produzir e peças boas usam as mesmas linhas do cartão", async () => {
    renderPage("orders", 3);
    const balance = await screen.findByRole("button", { name: /Saldo a produzir 44/ });
    expect(balance).toHaveTextContent("44");
    fireEvent.click(balance);
    const dialog = await screen.findByRole("dialog", { name: "Saldo a produzir" });
    expect(dialog).toHaveTextContent("os itens somam 44, igual ao número clicado");
    expect(dialog).not.toHaveTextContent("linhas carregadas");
    fireEvent.click(within(dialog).getByRole("button", { name: "Fechar explicação" }));

    expect(screen.getByRole("button", { name: /Peças boas 111/ })).toHaveTextContent("111");
  });

  it("Planejado × Realizado: atendimento mostra as entradas e perdas soma refugo + retrabalho", async () => {
    renderPage("plan", 3);
    const attendance = await screen.findByRole("button", { name: /Atendimento 73,8%/ });
    fireEvent.click(attendance);
    const dialog = await screen.findByRole("dialog", { name: "Atendimento" });
    expect(within(dialog).getByTestId("explanation-total")).toHaveTextContent("73,8%");
    expect(dialog).toHaveTextContent("Atendida (boas + refugo)");
    expect(dialog).toHaveTextContent("118");
    expect(dialog).toHaveTextContent("160");
    fireEvent.click(within(dialog).getByRole("button", { name: "Fechar explicação" }));

    fireEvent.click(screen.getByRole("button", { name: /Perdas no período 11/ }));
    await waitFor(() => expect(screen.getByRole("dialog", { name: "Perdas no período" })).toHaveTextContent("os itens somam 11"));
  });
});
