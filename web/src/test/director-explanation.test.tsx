import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DirectorPage } from "../pages/director/DirectorPage";

const PAINEL = {
  periodo: { nome: "hoje", inicio: "2026-10-20T00:00:00", fim: "2026-10-20T23:59:59" },
  cards: { produzido: 1240, horas_paradas: 12.5, custo_parada: 2250, eficiencia_oee: { value: 71.4, unit: "%", availability: "disponivel" } },
  onde_perdemos: [
    { setor: "Corte", horas_paradas: 6, custo: 1500, motivo_principal: "Falta de material", custo_completo: true },
    { setor: null, horas_paradas: 2, custo: 100, motivo_principal: null, custo_completo: true },
  ],
  melhor_setor: { nome: "Pintura", oee: 82 },
  pior_setor: { nome: "Corte", oee: 55.5 },
  custo_completo: true,
  custos_faltando: 0,
  aviso: null,
};

const FICHA = {
  texto: "O Corte trabalhou 31 h de 40 h.",
  trabalhou_h: 31,
  disponivel_h: 40,
  produzido: 800,
  custo_trabalho: 9300,
  parado_h: 6,
  custo_parada: 1500,
  motivo_principal: "Falta de material",
  paradas_por_motivo: [{ motivo: "Falta de material", horas: 4 }],
  sem_demanda_h: 3,
  fora_turno_h: 5.5,
  pessoas: [],
  custo_parada_completo: true,
  custos_faltando_parada: 0,
  custo_trabalho_completo: true,
  custos_faltando_trabalho: 0,
  custo_completo: true,
  custos_faltando: 0,
};

const CUSTOS = {
  recursos: [
    { recurso: "LASER1", setor: "Corte", valor_hora: 120 },
    { recurso: "PINT1", setor: "Pintura", valor_hora: null },
  ],
  pessoas: [{ operador_id: 7, nome: "João Silva", cracha: "123", valor_hora: 30 }],
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function explanation(metric: string) {
  return {
    kind: "value",
    metric,
    label: `Explicação ${metric}`,
    unit: "brl",
    value: 120,
    reason: "Teste.",
    rule: "Regra de teste.",
    children: [],
    excluded: [],
    reconciliation: { ok: true, sum: 120, diff: 0 },
    calculated_at: "2026-10-20T14:00:00",
    truncated: false,
    notes: [],
  };
}

function stub(explainStatus = 200) {
  const mock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.includes("/diretoria/explicacao")) {
      if (explainStatus !== 200) return json({ code: "forbidden", message: "Sem acesso" }, explainStatus);
      return json(explanation(new URL(path, "http://x").searchParams.get("metric") ?? ""));
    }
    if (path.includes("/diretoria/painel")) return json(PAINEL);
    if (path.includes("/diretoria/ficha")) return json(FICHA);
    if (path.includes("/diretoria/custos")) return json(CUSTOS);
    return json({ code: "not_found", message: "Não encontrado" }, 404);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function explainUrls(mock: ReturnType<typeof stub>) {
  return mock.mock.calls.map((call) => String((call as unknown[])[0])).filter((url) => url.includes("/diretoria/explicacao"));
}

async function clickAndExpect(mock: ReturnType<typeof stub>, name: RegExp, expected: string[]) {
  fireEvent.click(await screen.findByRole("button", { name }));
  await screen.findByRole("dialog");
  await waitFor(() => expect(explainUrls(mock).some((url) => expected.every((part) => url.includes(part)))).toBe(true));
  fireEvent.click(screen.getByRole("button", { name: "Fechar explicação" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Diretoria: números clicáveis", () => {
  it("Painel: os 4 cartões abrem dir.* com o período da tela", async () => {
    const mock = stub();
    render(<DirectorPage />);
    await clickAndExpect(mock, /Ver de onde vem este número: Produzido/, ["metric=dir.produzido", "periodo=hoje"]);
    await clickAndExpect(mock, /Ver de onde vem este número: Horas paradas/, ["metric=dir.horas_paradas"]);
    await clickAndExpect(mock, /Ver de onde vem este número: Custo das paradas/, ["metric=dir.custo_parada"]);
    await clickAndExpect(mock, /Ver de onde vem este número: Eficiência/, ["metric=dir.eficiencia"]);
  });

  it("Painel: horas e custo de cada setor do ranking levam o setor", async () => {
    const mock = stub();
    render(<DirectorPage />);
    await screen.findByText("Onde mais perdemos");
    const buttons = screen.getAllByRole("button", { name: /Ver de onde vem este número:/ });
    const horasCorte = buttons.find((b) => b.textContent === "6 h");
    const custoCorte = buttons.find((b) => b.textContent === "R$ 1.500");
    expect(horasCorte).toBeDefined();
    expect(custoCorte).toBeDefined();
    fireEvent.click(horasCorte!);
    await screen.findByRole("dialog");
    await waitFor(() => expect(explainUrls(mock).some((u) => u.includes("metric=dir.horas_paradas") && u.includes("setor=Corte"))).toBe(true));
    fireEvent.click(screen.getByRole("button", { name: "Fechar explicação" }));
    fireEvent.click(custoCorte!);
    await screen.findByRole("dialog");
    await waitFor(() => expect(explainUrls(mock).some((u) => u.includes("metric=dir.custo_setor") && u.includes("setor=Corte"))).toBe(true));
  });

  it("Painel: linha sem setor não vira botão de explicação (custo_setor exige setor)", async () => {
    stub();
    render(<DirectorPage />);
    await screen.findByText("Onde mais perdemos");
    const lines = screen.getAllByRole("listitem").filter((li) => li.className.includes("director-loss-row"));
    const semSetor = lines.find((li) => li.textContent?.includes("Sem setor"));
    expect(semSetor).toBeDefined();
    expect(semSetor!.querySelectorAll("button.explainable-value")).toHaveLength(0);
  });

  it("Painel: eficiência sem valor fica como texto simples", async () => {
    const mock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes("/diretoria/painel")) return json({ ...PAINEL, cards: { ...PAINEL.cards, eficiencia_oee: { value: null, availability: "dados_insuficientes" } } });
      return json({ code: "not_found", message: "x" }, 404);
    });
    vi.stubGlobal("fetch", mock);
    render(<DirectorPage />);
    await screen.findByText("Onde mais perdemos");
    expect(screen.queryByRole("button", { name: /Ver de onde vem este número: Eficiência/ })).not.toBeInTheDocument();
  });

  it("Ficha: cinco cartões e a hora de cada motivo abrem dir.* com os filtros da ficha", async () => {
    const mock = stub();
    render(<DirectorPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Ficha" }));
    await screen.findByText(FICHA.texto);
    await clickAndExpect(mock, /Ver de onde vem este número: Trabalhou/, ["metric=dir.trabalhou"]);
    await clickAndExpect(mock, /Ver de onde vem este número: Custo do trabalho/, ["metric=dir.custo_trabalho"]);
    await clickAndExpect(mock, /Ver de onde vem este número: Parado por Falta de material/, ["metric=dir.parado_motivo", "motivo="]);
  });

  it("Custos: depois de salvar, o valor cadastrado mostrado é o novo", async () => {
    stub();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (init?.method === "PUT") return json({ ok: true });
      if (path.includes("/diretoria/custos")) return json(CUSTOS);
      return json(PAINEL);
    }));
    render(<DirectorPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Custos" }));
    const input = await screen.findByLabelText("Valor da hora de LASER1");
    fireEvent.change(input, { target: { value: "200" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar valor de LASER1" }));
    expect(await screen.findByRole("button", { name: /Valor cadastrado de LASER1/ })).toHaveTextContent("R$ 200,00/h");
  });

  it("Custos: valor cadastrado do recurso e da pessoa abre dir.valor_hora", async () => {
    const mock = stub();
    render(<DirectorPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Custos" }));
    await screen.findByLabelText("Valor da hora de LASER1");
    await clickAndExpect(mock, /Ver de onde vem este número: Valor cadastrado de LASER1/, ["metric=dir.valor_hora", "recurso=LASER1"]);
    await clickAndExpect(mock, /Ver de onde vem este número: Valor cadastrado de João Silva/, ["metric=dir.valor_hora", "pessoa=7"]);
  });

  it("recusa 403 mostra mensagem de acesso, sem expor erro técnico", async () => {
    stub(403);
    render(<DirectorPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Ver de onde vem este número: Produzido/ }));
    expect(await screen.findByText("Você não tem acesso a esta explicação.")).toBeInTheDocument();
  });
});
