import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";
import { parseSeconds, validFromLabel } from "../pages/production/StandardTimePage";

function session(role: string) {
  return { id: 1, name: `Conta ${role}`, role, management_access: true, andon_access: true, operator_access: false };
}

function json(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: { "content-type": "application/json" } });
}

const SEM_PADRAO = {
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

const ESTIMADA = {
  ...SEM_PADRAO,
  produto_codigo: "PROD-2",
  tempo_estimado_segundos: 62.5,
  estimado_amostras: 7,
  estimado_janela_inicio: "2026-09-01",
  estimado_janela_fim: "2026-10-05",
  fonte_efetiva: "estimado",
};

const DO_PROTHEUS = {
  ...SEM_PADRAO,
  produto_codigo: "PROD-3",
  tempo_protheus_segundos: 30,
  fonte_efetiva: "protheus",
};

function listResponse(items: unknown[], somente = true) {
  return { items, total: items.length, sem_produto: 0, limit: 100, offset: 0, somente_sem_padrao: somente };
}

type Handler = (path: string, init?: RequestInit) => Response | undefined;

function stubFetch(role: string, handler: Handler = () => undefined) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.includes("/auth/session")) return json(session(role));
    const custom = handler(path, init);
    if (custom) return custom;
    if (path.includes("/management/standard-times?")) return json(listResponse([SEM_PADRAO, ESTIMADA, DO_PROTHEUS]));
    return json({ code: "not_found", message: "Não encontrado" }, 404);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function renderAt(route: string) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <AuthProvider><App /></AuthProvider>
    </MemoryRouter>,
  );
}

const listCalls = (mock: ReturnType<typeof vi.fn>) =>
  mock.mock.calls.map(([path]) => String(path)).filter((path) => path.includes("/management/standard-times?"));

beforeEach(() => {
  document.cookie = "gestor_csrf=csrf-teste; path=/";
});
afterEach(() => vi.restoreAllMocks());

describe("Tempo padrão — acesso por nível", () => {
  it.each(["manufatura", "admin"])("a seção Manufatura aparece para %s, com a aba Tempo padrão", async (role) => {
    stubFetch(role);
    renderAt("/producao/ordens");
    const menu = await screen.findByRole("navigation", { name: "Navegação gerencial" });
    expect(within(menu).getByRole("link", { name: /Manufatura/ })).toHaveAttribute("href", "/manufatura/tempo-padrao");
    const nav = await screen.findByRole("navigation", { name: "Produção" });
    expect(within(nav).queryByRole("link", { name: "Tempo padrão" })).not.toBeInTheDocument();
  });

  it("a seção Manufatura NÃO aparece para o gestor comum", async () => {
    stubFetch("gestor");
    renderAt("/producao/ordens");
    const menu = await screen.findByRole("navigation", { name: "Navegação gerencial" });
    expect(within(menu).getByRole("link", { name: /Produção/ })).toBeInTheDocument();
    expect(within(menu).queryByRole("link", { name: /Manufatura/ })).not.toBeInTheDocument();
  });

  it("a aba Tempo padrão fica dentro da seção Manufatura", async () => {
    stubFetch("manufatura");
    renderAt("/manufatura/tempo-padrao");
    const nav = await screen.findByRole("navigation", { name: "Manufatura" });
    expect(within(nav).getByRole("link", { name: "Tempo padrão" })).toHaveAttribute("href", "/manufatura/tempo-padrao");
  });

  it("o gestor que abre a URL direta recebe o aviso e a API nem é consultada", async () => {
    const mock = stubFetch("gestor");
    renderAt("/manufatura/tempo-padrao");
    expect(await screen.findByText("Acesso restrito à engenharia de manufatura")).toBeInTheDocument();
    expect(listCalls(mock)).toHaveLength(0);
  });
});

describe("Tempo padrão — tela", () => {
  it("lista as operações com a fonte rotulada e o estimado sempre como estimado", async () => {
    stubFetch("manufatura");
    renderAt("/manufatura/tempo-padrao");
    await screen.findByText("PROD-1");
    const rows = document.querySelectorAll(".data-table tbody tr");
    expect(rows).toHaveLength(3);
    expect(within(rows[0] as HTMLElement).getByText("Sem padrão")).toBeInTheDocument();
    const estimada = rows[1] as HTMLElement;
    expect(within(estimada).getByText("62,5 s")).toBeInTheDocument();
    expect(within(estimada).getByText("estimado · 7 amostras")).toBeInTheDocument();
    expect(within(estimada).getByText("Estimado")).toBeInTheDocument();
    expect(estimada.querySelector(".std-time__estimated")?.getAttribute("title")).toContain("7 execuções reais");
    expect(within(rows[2] as HTMLElement).getByText("Protheus", { selector: ".status-badge" })).toBeInTheDocument();
  });

  it("campo manual fica desabilitado quando o Protheus já define o tempo", async () => {
    stubFetch("manufatura");
    renderAt("/manufatura/tempo-padrao");
    await screen.findByText("PROD-3");
    const campo = screen.getByLabelText(/Tempo manual em segundos por peça: PROD-3/);
    expect(campo).toBeDisabled();
    expect(screen.getByText("Definido no Protheus")).toBeInTheDocument();
  });

  it("salva o valor com vírgula decimal pt-BR como número, com CSRF e observação", async () => {
    const mock = stubFetch("manufatura", (path, init) => {
      if (path.endsWith("/management/standard-times/manual") && init?.method === "PUT") {
        return json({ ok: true, item: { ...SEM_PADRAO, tempo_manual_segundos: 45.5, fonte_efetiva: "manual" } });
      }
      return undefined;
    });
    renderAt("/manufatura/tempo-padrao");
    await screen.findByText("PROD-1");

    const campo = screen.getByLabelText(/Tempo manual em segundos por peça: PROD-1/);
    fireEvent.change(campo, { target: { value: "45,5" } });
    fireEvent.change(screen.getByLabelText(/Observação do tempo manual: PROD-1/), { target: { value: "medido na bancada" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Salvar" })[0]);

    await screen.findByText(/Tempo manual salvo: PROD-1, operação 10, 45,5 s por peça/);
    const put = mock.mock.calls.find(([, init]) => init?.method === "PUT")!;
    expect(JSON.parse(String(put[1]?.body))).toEqual({
      produto_codigo: "PROD-1",
      numero_operacao: "10",
      codigo_recurso: "DOBRA01",
      segundos_por_peca: 45.5,
      observacao: "medido na bancada",
    });
    expect(new Headers(put[1]?.headers).get("X-CSRF-Token")).toBe("csrf-teste");
  });

  it("409 de Protheus mostra mensagem humana, sem código técnico, e recarrega a lista", async () => {
    const mock = stubFetch("manufatura", (path, init) => {
      if (path.endsWith("/management/standard-times/manual") && init?.method === "PUT") {
        return json({ code: "standard_time_defined_by_protheus", message: "msg do servidor", request_id: "r1" }, 409);
      }
      return undefined;
    });
    renderAt("/manufatura/tempo-padrao");
    await screen.findByText("PROD-1");
    const antes = listCalls(mock).length;

    fireEvent.change(screen.getByLabelText(/Tempo manual em segundos por peça: PROD-1/), { target: { value: "20" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Salvar" })[0]);

    const alerta = await screen.findByText(/O Protheus já define o tempo padrão desta operação/);
    expect(alerta).toHaveAttribute("role", "alert");
    expect(document.body.textContent).not.toContain("standard_time_defined_by_protheus");
    await waitFor(() => expect(listCalls(mock).length).toBeGreaterThan(antes));
  });

  it("valida no cliente: zero, acima de 86400 e texto, sem chamar a API", async () => {
    const mock = stubFetch("manufatura");
    renderAt("/manufatura/tempo-padrao");
    await screen.findByText("PROD-1");
    const campo = screen.getByLabelText(/Tempo manual em segundos por peça: PROD-1/);

    for (const [valor, mensagem] of [
      ["0", "O tempo precisa ser maior que zero."],
      ["86400,5", "O tempo máximo é 86.400 segundos por peça (24 horas)."],
      ["abc", "Use só números, por exemplo 45 ou 45,5."],
    ] as const) {
      fireEvent.change(campo, { target: { value: valor } });
      fireEvent.click(screen.getAllByRole("button", { name: "Salvar" })[0]);
      expect(await screen.findByText(mensagem)).toBeInTheDocument();
    }
    expect(mock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(false);
  });

  it("'somente sem padrão' vem ligado e o filtro vira parâmetro da consulta", async () => {
    const mock = stubFetch("manufatura");
    renderAt("/manufatura/tempo-padrao");
    await screen.findByText("PROD-1");
    const toggle = screen.getByRole("checkbox", { name: "Somente sem padrão" });
    expect(toggle).toBeChecked();
    expect(listCalls(mock)[0]).toContain("somente_sem_padrao=true");
    expect(listCalls(mock)[0]).toContain("limit=100");

    fireEvent.click(toggle);
    await waitFor(() => expect(listCalls(mock).some((path) => path.includes("somente_sem_padrao=false"))).toBe(true));

    fireEvent.change(screen.getByLabelText("Produto"), { target: { value: "PROD-9" } });
    fireEvent.change(screen.getByLabelText("Setor"), { target: { value: "Dobra" } });
    await waitFor(() => {
      const ultima = listCalls(mock).at(-1)!;
      expect(ultima).toContain("produto=PROD-9");
      expect(ultima).toContain("setor=Dobra");
      expect(ultima).toContain("somente_sem_padrao=false");
    });
  });

  it("recalcular estimativas mostra o resumo humanizado, sem JSON cru", async () => {
    stubFetch("manufatura", (path, init) => {
      if (path.endsWith("/standard-times/estimates/recalculate") && init?.method === "POST") {
        return json({
          ok: true,
          calculado_em: "2026-10-06T10:00:00",
          janela_inicio: "2026-09-01",
          janela_fim: "2026-10-05",
          execucoes_elegiveis: 1204,
          chaves_avaliadas: 340,
          chaves_estimadas: 12,
          amostra_minima: 3,
        });
      }
      return undefined;
    });
    renderAt("/manufatura/tempo-padrao");
    await screen.findByText("PROD-1");
    fireEvent.click(screen.getByRole("button", { name: "Recalcular estimativas" }));
    const aviso = await screen.findByText(/Estimativas recalculadas: 12 de 340 operações avaliadas/);
    expect(aviso.textContent).toContain("1.204 execuções reais");
    expect(aviso.textContent).not.toContain("{");
  });

  it("abre o histórico do tempo manual da operação", async () => {
    const comManual = { ...SEM_PADRAO, tempo_manual_segundos: 45.5, manual_alterado_em: "2026-10-06T09:00:00", fonte_efetiva: "manual" };
    const mock = stubFetch("manufatura", (path) => {
      if (path.includes("/standard-times/manual/history?")) {
        return json({ items: [{ acao: "alterado", segundos_anterior: 40, segundos_novo: 45.5, observacao: "revisado", usuario_nome: "Gabriel Fogaça", registrado_em: "2026-10-06T09:00:00" }] });
      }
      if (path.includes("/management/standard-times?")) return json(listResponse([comManual]));
      return undefined;
    });
    renderAt("/manufatura/tempo-padrao");
    await screen.findByText("PROD-1");

    fireEvent.click(screen.getByRole("button", { name: /^Histórico:/ }));
    const dialogo = await screen.findByRole("dialog", { name: "Histórico do tempo manual" });
    await within(dialogo).findByText("Alterado");
    expect(within(dialogo).getByText("40 s")).toBeInTheDocument();
    expect(within(dialogo).getByText("Gabriel Fogaça")).toBeInTheDocument();
    const historyCall = mock.mock.calls.map(([path]) => String(path)).find((path) => path.includes("/manual/history?"))!;
    expect(historyCall).toContain("produto_codigo=PROD-1");
    expect(historyCall).toContain("numero_operacao=10");
    expect(historyCall).toContain("codigo_recurso=DOBRA01");
  });
});

describe("Tempo padrão — chave mista e vigência", () => {
  const MISTA = {
    ...SEM_PADRAO,
    produto_codigo: "PROD-M",
    tempo_manual_segundos: 45.5,
    manual_alterado_por: "Gabriel Fogaça",
    manual_alterado_em: "2026-10-06T09:00:00",
    manual_vigente_desde: "2026-10-06T09:00:00",
    estimado_vigente_desde: "2026-10-01",
    tempo_estimado_segundos: 50,
    linhas_com_protheus: 2,
    linhas_total: 5,
    fonte_efetiva: "manual",
  };

  it("chave mista avisa quantas OPs o manual cobre e mostra 'vale a partir de' do manual e do estimado", async () => {
    stubFetch("manufatura", (path) => {
      if (path.includes("/management/standard-times?")) return json(listResponse([MISTA, ESTIMADA]));
      return undefined;
    });
    renderAt("/manufatura/tempo-padrao");
    await screen.findByText("PROD-M");
    const rows = document.querySelectorAll(".data-table tbody tr");
    const mista = rows[0] as HTMLElement;
    expect(within(mista).getByText("Manual cobre 3 de 5 OPs (as demais usam Protheus)")).toBeInTheDocument();
    const vale = within(mista).getAllByText(/^vale a partir de/);
    expect(vale).toHaveLength(2);
    // Ordem das colunas: manual (instante ISO, com hora) e depois estimado (data pura).
    expect(vale[0].textContent).toMatch(/^vale a partir de 06\/10\/2026.*09:00/);
    expect(vale[1].textContent).toMatch(/^vale a partir de 01\/10\/2026$/);
    // Chave sem os campos novos (backend antigo) não mostra aviso nem vigência.
    const antiga = rows[1] as HTMLElement;
    expect(within(antiga).queryByText(/Manual cobre/)).not.toBeInTheDocument();
    expect(within(antiga).queryByText(/vale a partir de/)).not.toBeInTheDocument();
  });

  it("sem aviso quando todas as linhas têm Protheus ou nenhuma tem", async () => {
    stubFetch("manufatura", (path) => {
      if (path.includes("/management/standard-times?")) {
        return json(listResponse([
          { ...DO_PROTHEUS, linhas_com_protheus: 3, linhas_total: 3 },
          { ...SEM_PADRAO, produto_codigo: "PROD-Z", linhas_com_protheus: 0, linhas_total: 3 },
        ]));
      }
      return undefined;
    });
    renderAt("/manufatura/tempo-padrao");
    await screen.findByText("PROD-3");
    expect(screen.queryByText(/Manual cobre/)).not.toBeInTheDocument();
  });

  it("lembra que o valor manual não altera períodos já passados ao editar", async () => {
    stubFetch("manufatura");
    renderAt("/manufatura/tempo-padrao");
    await screen.findByText("PROD-1");
    expect(screen.queryByText(/não altera períodos já passados\./, { selector: "small" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/Tempo manual em segundos por peça: PROD-1/), { target: { value: "30" } });
    expect(screen.getByText("Vale a partir do momento em que você salvar; não altera períodos já passados.")).toBeInTheDocument();
  });

  it("histórico mostra 'Vale a partir de' por entrada, com data ou data e hora", async () => {
    const comManual = { ...SEM_PADRAO, tempo_manual_segundos: 45.5, manual_alterado_em: "2026-10-06T09:00:00", fonte_efetiva: "manual" };
    stubFetch("manufatura", (path) => {
      if (path.includes("/standard-times/manual/history?")) {
        return json({ items: [
          { acao: "alterado", segundos_anterior: 40, segundos_novo: 45.5, registrado_em: "2026-10-06T09:00:00", vigente_desde: "2026-10-06T09:00:00" },
          { acao: "definido", segundos_anterior: null, segundos_novo: 40, registrado_em: "2026-10-01T08:00:00", vigente_desde: "2026-10-01" },
        ] });
      }
      if (path.includes("/management/standard-times?")) return json(listResponse([comManual]));
      return undefined;
    });
    renderAt("/manufatura/tempo-padrao");
    await screen.findByText("PROD-1");
    fireEvent.click(screen.getByRole("button", { name: /^Histórico:/ }));
    const dialogo = await screen.findByRole("dialog", { name: "Histórico do tempo manual" });
    await within(dialogo).findByText("Alterado");
    expect(within(dialogo).getByRole("columnheader", { name: "Vale a partir de" })).toBeInTheDocument();
    expect(within(dialogo).getByText("01/10/2026")).toBeInTheDocument();
    // "Quando" e "Vale a partir de" da entrada de 06/10 mostram o mesmo instante.
    expect(within(dialogo).getAllByText(/^06\/10\/2026.*09:00/, { selector: "td" })).toHaveLength(2);
  });
});

describe("validFromLabel", () => {
  it("data pura não escorrega de dia por fuso; instante ISO traz hora; vazio e lixo são tolerados", () => {
    expect(validFromLabel("2026-10-06")).toBe("06/10/2026");
    expect(validFromLabel("2026-10-06T14:30:00")).toMatch(/^06\/10\/2026.*14:30/);
    expect(validFromLabel(null)).toBe("");
    expect(validFromLabel("ontem")).toBe("ontem");
  });
});

describe("parseSeconds", () => {
  it.each([
    ["45", 45],
    ["45,5", 45.5],
    ["45.5", 45.5],
    ["1.234,5", 1234.5],
    [" 0,25 ", 0.25],
    ["86400", 86400],
  ])("aceita %s", (texto, esperado) => {
    expect(parseSeconds(texto)).toEqual({ value: esperado });
  });

  it.each(["", "0", "-3", "1,2,3", "12abc", "86400,01", "1.2.3"])("recusa %j", (texto) => {
    expect(parseSeconds(texto)).toHaveProperty("error");
  });
});
