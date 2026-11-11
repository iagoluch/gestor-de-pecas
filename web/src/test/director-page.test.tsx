import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, putOperatorRate, putResourceRate } from "../api/client";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { FilterProvider, useManagementFilters } from "../filters/FilterContext";
import { DirectorPage } from "../pages/director/DirectorPage";

// Leituras passam pelo fetch falso; as gravações são espiadas na própria função do client.
vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  putResourceRate: vi.fn(),
  putOperatorRate: vi.fn(),
}));

const PAINEL = {
  periodo: { nome: "hoje", inicio: "2026-10-16T00:00:00", fim: "2026-10-16T23:59:59" },
  cards: { produzido: 1240, horas_paradas: 12.5, custo_parada: 2250, eficiencia_oee: { value: 71.4, unit: "%", availability: "disponivel" } },
  onde_perdemos: [
    { setor: "Corte", horas_paradas: 6, custo: 1500, motivo_principal: "Falta de material", custo_completo: true },
    { setor: "Solda Aço", horas_paradas: 4, custo: 0, motivo_principal: "Manutenção", custo_completo: false },
    { setor: "Pintura", horas_paradas: 2.5, custo: 750, motivo_principal: null, custo_completo: true },
  ],
  melhor_setor: { nome: "Pintura", oee: 82 },
  pior_setor: { nome: "Corte", oee: 55.5 },
  custo_completo: false,
  custos_faltando: 3,
  aviso: "faltam custos de 3 recursos/pessoas — o valor real é maior",
};

const FICHA = {
  texto: "O Corte trabalhou 31 h de 40 h e ficou parado 6 h, principalmente por falta de material.",
  trabalhou_h: 31,
  disponivel_h: 40,
  produzido: 800,
  custo_trabalho: 9300,
  parado_h: 6,
  custo_parada: 1500,
  motivo_principal: "Falta de material",
  paradas_por_motivo: [{ motivo: "Falta de material", horas: 4 }, { motivo: "Ajuste", horas: 2 }],
  sem_demanda_h: 3,
  fora_turno_h: 5.5,
  pessoas: [{ nome: "João Silva", horas: 20, custo: 600, custo_completo: true }, { nome: "Maria", horas: 11, custo: 0, custo_completo: false }],
  custo_parada_completo: true,
  custos_faltando_parada: 0,
  custo_trabalho_completo: true,
  custos_faltando_trabalho: 0,
  custo_completo: true,
  custos_faltando: 0,
};

const FICHA_VAZIA = {
  ...FICHA,
  texto: "Sem paradas no período.",
  trabalhou_h: 0,
  parado_h: 0,
  custo_parada: 0,
  custo_trabalho: 0,
  motivo_principal: null,
  paradas_por_motivo: [],
  pessoas: [],
};

const CUSTOS = {
  recursos: [
    { recurso: "LASER1", setor: "Corte", valor_hora: null },
    { recurso: "PINT1", setor: "Pintura", valor_hora: 80 },
  ],
  pessoas: [{ operador_id: 7, nome: "João Silva", cracha: "123", valor_hora: 30 }],
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

const INDICADORES = {
  periodo: { nome: "semana", inicio: "2026-11-09T00:00:00", fim: "2026-11-11T23:59:59" },
  as_of: "2026-11-11T10:00:00",
  itens: [
    { chave: "pecas_boas", rotulo: "Peças boas", tipo: "02", campo: "quantidade_boa", unidade: "pecas", valor: 40, estado: "com_dados" },
    { chave: "refugo", rotulo: "Refugo", tipo: "02", campo: "quantidade_refugo", unidade: "pecas", valor: null, estado: "sem_registros" },
    { chave: "horas_paradas", rotulo: "Horas paradas não planejadas", tipo: "04", campo: "unplanned_downtime_seconds", unidade: "segundos", valor: 5400, estado: "com_dados" },
    { chave: "oee", rotulo: "OEE", tipo: "11", campo: "oee", unidade: "percentual", valor: 61.5, estado: "com_dados" },
  ],
};

function AuditoriaAberta() {
  const { filters } = useManagementFilters();
  const location = useLocation();
  return <p>Auditoria {location.search} de {filters.startDate} até {filters.endDate}</p>;
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/diretoria"]}>
      <FilterProvider>
        <Routes>
          <Route path="/diretoria" element={<DirectorPage />} />
          <Route path="/auditoria/analitica" element={<AuditoriaAberta />} />
        </Routes>
      </FilterProvider>
    </MemoryRouter>,
  );
}

function stub(overrides: { painel?: unknown; ficha?: unknown } = {}) {
  const mock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.includes("/diretoria/indicadores")) return json(INDICADORES);
    if (path.includes("/diretoria/painel")) return json(overrides.painel ?? PAINEL);
    if (path.includes("/diretoria/ficha")) return json(overrides.ficha ?? FICHA);
    if (path.includes("/diretoria/custos")) return json(CUSTOS);
    return json({ code: "not_found", message: "Não encontrado" }, 404);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

const fichaCalls = (mock: ReturnType<typeof stub>) => mock.mock.calls.map(([path]) => String(path)).filter((path) => path.includes("/diretoria/ficha"));

beforeEach(() => {
  vi.mocked(putResourceRate).mockReset();
  vi.mocked(putOperatorRate).mockReset();
});
afterEach(() => vi.unstubAllGlobals());

describe("Aba Diretoria — Painel", () => {
  it("mostra só o custo das paradas em R$ (sem repetir os indicadores) e o aviso de custos faltando", async () => {
    stub();
    renderPage();
    expect(await screen.findByText("faltam custos de 3 recursos/pessoas — o valor real é maior")).toBeInTheDocument();
    expect(screen.getByText("Custo das paradas")).toBeInTheDocument();
    expect(screen.getByText("R$ 2.250")).toBeInTheDocument();
    // Produzido, Horas paradas e Eficiência repetiam Peças boas, Horas paradas não planejadas e OEE.
    expect(screen.queryByText("Produzido")).not.toBeInTheDocument();
    expect(screen.queryByText("Eficiência")).not.toBeInTheDocument();
    expect(screen.queryByText("Horas paradas")).not.toBeInTheDocument();
    expect(screen.getByText(/Pintura/, { selector: ".director-highlight strong" })).toBeInTheDocument();
  });

  it("eficiência acima de 100% avisa; abaixo disso não avisa", async () => {
    stub({ painel: { ...PAINEL, cards: { ...PAINEL.cards, eficiencia_oee: { value: 112.3, unit: "%", availability: "disponivel" } } } });
    const { unmount } = renderPage();
    expect(await screen.findByText(/Eficiência acima de 100%/)).toBeInTheDocument();
    unmount();
    stub();
    renderPage();
    await screen.findByText("Custo das paradas");
    expect(screen.queryByText(/Eficiência acima de 100%/)).not.toBeInTheDocument();
  });

  it("melhor setor com 0% não vira destaque: mostra sem dados nos dois cartões", async () => {
    stub({ painel: { ...PAINEL, melhor_setor: { nome: "Corte", oee: 0 }, pior_setor: { nome: "Solda", oee: 0 } } });
    renderPage();
    expect(await screen.findAllByText("Sem dados de eficiência por setor no período.")).toHaveLength(2);
    expect(screen.queryByText(/Corte/, { selector: ".director-highlight strong" })).not.toBeInTheDocument();
  });

  it("setor com eficiência acima de 100% mostra o valor real e um aviso no cartão; abaixo disso não avisa", async () => {
    stub({ painel: { ...PAINEL, melhor_setor: { nome: "Pintura", oee: 1087.7 } } });
    const { unmount } = renderPage();
    expect(await screen.findByText(/confira o tempo padrão deste setor/)).toBeInTheDocument();
    expect(screen.getByText("1.087,7%")).toBeInTheDocument();
    unmount();
    stub();
    renderPage();
    await screen.findByText(/Pintura/, { selector: ".director-highlight strong" });
    expect(screen.queryByText(/confira o tempo padrão deste setor/)).not.toBeInTheDocument();
  });

  it("custo incompleto e zerado não vira um R$ 0 mentiroso", async () => {
    stub({ painel: { ...PAINEL, cards: { ...PAINEL.cards, custo_parada: 0 } } });
    renderPage();
    await screen.findByText("Onde mais perdemos");
    expect(screen.queryByText(/R\$ 0\b/)).not.toBeInTheDocument();
    expect(screen.getAllByText("Sem custo cadastrado").length).toBeGreaterThanOrEqual(2);
  });

  it("trocar o período pede o painel do novo período", async () => {
    const mock = stub();
    renderPage();
    await screen.findByText("Onde mais perdemos");
    fireEvent.click(screen.getByRole("button", { name: "Semana" }));
    await waitFor(() => expect(mock.mock.calls.some(([path]) => String(path).endsWith("/diretoria/painel?periodo=semana"))).toBe(true));
    expect(screen.getByRole("button", { name: "Semana" })).toHaveAttribute("aria-pressed", "true");
  });

  it("período sem paradas mostra 'sem paradas no período'", async () => {
    stub({ painel: { ...PAINEL, onde_perdemos: [], aviso: null, custo_completo: true, custos_faltando: 0 } });
    renderPage();
    expect(await screen.findByText(/sem paradas no período/i)).toBeInTheDocument();
  });

  it("clicar no setor do ranking abre a Ficha já filtrada no setor", async () => {
    const mock = stub();
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: /Ver a ficha do setor Corte/ }));
    expect(await screen.findByText(FICHA.texto)).toBeInTheDocument();
    expect(screen.getByLabelText("Setor")).toHaveValue("Corte");
    expect(fichaCalls(mock).some((path) => path.includes("setor=Corte") && path.includes("periodo=hoje"))).toBe(true);
  });
});

describe("Aba Diretoria — Indicadores da Auditoria", () => {
  it("mostra os números da Auditoria, 'sem registros' sem dado, e o clique abre a Auditoria no período", async () => {
    stub();
    renderPage();
    expect(await screen.findByText("Peças boas")).toBeInTheDocument();
    expect(screen.getByText("40 peças")).toBeInTheDocument();
    expect(screen.getByText("sem registros")).toBeInTheDocument();
    expect(screen.getByText("1,5 h")).toBeInTheDocument();
    expect(screen.getByText("61,5%")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Horas paradas não planejadas/ }));
    expect(await screen.findByText("Auditoria ?tipo=04 de 2026-11-09 até 2026-11-11")).toBeInTheDocument();
  });
});

describe("Aba Diretoria — Ficha", () => {
  it("mostra o texto pronto antes da lista de motivos, quem operou e as horas sem R$", async () => {
    stub();
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Ficha" }));
    const texto = await screen.findByText(FICHA.texto);
    const motivos = screen.getByRole("heading", { name: "Paradas por motivo" });
    expect(texto.compareDocumentPosition(motivos) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText("João Silva")).toBeInTheDocument();
    const semDemanda = screen.getByText(/Sem demanda/).closest("li")!;
    const foraTurno = screen.getByText(/Fora do turno/).closest("li")!;
    expect(semDemanda).toHaveTextContent("3 h");
    expect(foraTurno).toHaveTextContent("5,5 h");
    expect(semDemanda).not.toHaveTextContent("R$");
    expect(foraTurno).not.toHaveTextContent("R$");
    // Pessoa sem custo cadastrado não aparece como R$ 0.
    expect(within(screen.getByText("Maria").closest("li")!).getByText("Sem custo cadastrado")).toBeInTheDocument();
  });

  it("período vazio mostra o texto do servidor", async () => {
    stub({ ficha: FICHA_VAZIA });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Ficha" }));
    expect(await screen.findByText("Sem paradas no período.")).toBeInTheDocument();
  });

  it("escolher um recurso pede a ficha do recurso", async () => {
    const mock = stub();
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Ficha" }));
    await screen.findByText(FICHA.texto);
    const recurso = screen.getByLabelText("Recurso");
    await waitFor(() => expect(within(recurso).getAllByRole("option").length).toBeGreaterThan(1));
    fireEvent.change(recurso, { target: { value: "LASER1" } });
    await waitFor(() => expect(fichaCalls(mock).some((path) => path.includes("recurso=LASER1"))).toBe(true));
  });
});

describe("Aba Diretoria — Custos", () => {
  async function openCosts() {
    stub();
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Custos" }));
    return screen.findByLabelText("Valor da hora de LASER1");
  }

  it("aceita '12,50' e envia 12.5 para o recurso", async () => {
    vi.mocked(putResourceRate).mockResolvedValue({ ok: true });
    const field = await openCosts();
    fireEvent.change(field, { target: { value: "12,50" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar valor de LASER1" }));
    await waitFor(() => expect(putResourceRate).toHaveBeenCalledWith("LASER1", 12.5));
    expect(await screen.findByText("Salvo.")).toBeInTheDocument();
    expect(screen.getByLabelText("Valor da hora de PINT1")).toHaveValue("80,00");
  });

  it("salva o valor da pessoa pelo id do operador", async () => {
    vi.mocked(putOperatorRate).mockResolvedValue({ ok: true });
    await openCosts();
    const field = screen.getByLabelText("Valor da hora de João Silva");
    fireEvent.change(field, { target: { value: "1.250,75" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar valor de João Silva" }));
    await waitFor(() => expect(putOperatorRate).toHaveBeenCalledWith(7, 1250.75));
  });

  it("erro 422 do servidor aparece como mensagem legível na linha", async () => {
    vi.mocked(putResourceRate).mockRejectedValue(new ApiError(422, { code: "valor_invalido", message: "O valor da hora precisa ser maior que zero." }));
    const field = await openCosts();
    fireEvent.change(field, { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar valor de LASER1" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("O valor da hora precisa ser maior que zero.");
  });

  it.each(["12 50", "1.2.5,00", "0", "-5", "R$ 12,50"])("'%s' mostra o erro legível e não chama o servidor", async (typed) => {
    const field = await openCosts();
    fireEvent.change(field, { target: { value: typed } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar valor de LASER1" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("por exemplo 12,50");
    expect(putResourceRate).not.toHaveBeenCalled();
  });

  it.each([["1.250,50", 1250.5], ["12.5", 12.5], [" 7,25 ", 7.25], ["1.250", 1250]])("'%s' é enviado como %s", async (typed, expected) => {
    vi.mocked(putResourceRate).mockResolvedValue({ ok: true });
    const field = await openCosts();
    fireEvent.change(field, { target: { value: typed } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar valor de LASER1" }));
    await waitFor(() => expect(putResourceRate).toHaveBeenCalledWith("LASER1", expected));
  });

  it("422 genérico de validação vira orientação em português", async () => {
    vi.mocked(putResourceRate).mockRejectedValue(new ApiError(422, { code: "validation_error", message: "Os dados enviados são inválidos." }));
    const field = await openCosts();
    fireEvent.change(field, { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar valor de LASER1" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("por exemplo 12,50");
  });

  it("texto que não é valor nem chega ao servidor", async () => {
    const field = await openCosts();
    fireEvent.change(field, { target: { value: "doze" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar valor de LASER1" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("por exemplo 12,50");
    expect(putResourceRate).not.toHaveBeenCalled();
  });
});
