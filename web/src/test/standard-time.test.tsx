import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";
import { FilterProvider } from "../filters/FilterContext";
import { StandardTimePage, validFromLabel } from "../pages/production/StandardTimePage";
import { NO_PROTHEUS_STANDARD_TEXT } from "../types/standardTime";

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

/** A tela de tempo padrão não tem mais rota (04/11/2026): o teste a monta direto. */
function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/manufatura/tempo-padrao"]}>
      <AuthProvider><FilterProvider><StandardTimePage /></FilterProvider></AuthProvider>
    </MemoryRouter>,
  );
}

const listCalls = (mock: ReturnType<typeof vi.fn>) =>
  mock.mock.calls.map(([path]) => String(path)).filter((path) => path.includes("/management/standard-times?"));

beforeEach(() => {
  document.cookie = "gestor_csrf=csrf-teste; path=/";
});
afterEach(() => vi.restoreAllMocks());

describe("Manufatura — seção vazia (04/11/2026)", () => {
  it.each(["manufatura", "admin"])("a seção Manufatura aparece para %s, sem aba de tempo padrão", async (role) => {
    stubFetch(role);
    renderAt("/producao/ordens");
    const menu = await screen.findByRole("navigation", { name: "Navegação gerencial" });
    expect(within(menu).getByRole("link", { name: /Manufatura/ })).toHaveAttribute("href", "/manufatura");
  });

  it("a seção Manufatura NÃO aparece para o gestor comum", async () => {
    stubFetch("gestor");
    renderAt("/producao/ordens");
    const menu = await screen.findByRole("navigation", { name: "Navegação gerencial" });
    expect(within(menu).getByRole("link", { name: /Produção/ })).toBeInTheDocument();
    expect(within(menu).queryByRole("link", { name: /Manufatura/ })).not.toBeInTheDocument();
  });

  it("a engenharia abre Manufatura vazia, sem aba e sem consultar o tempo padrão", async () => {
    const mock = stubFetch("manufatura");
    renderAt("/manufatura");
    expect(await screen.findByText("Nenhuma tela por enquanto")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Tempo padrão" })).not.toBeInTheDocument();
    expect(listCalls(mock)).toHaveLength(0);
  });

  it("o gestor que abre a URL direta recebe o aviso e a API nem é consultada", async () => {
    const mock = stubFetch("gestor");
    renderAt("/manufatura");
    expect(await screen.findByText("Acesso restrito à engenharia de manufatura")).toBeInTheDocument();
    expect(listCalls(mock)).toHaveLength(0);
  });
});

describe("Tempo padrão — tela só leitura (04/11/2026)", () => {
  it("lista as operações com a fonte rotulada, n/a sem Protheus e o estimado sempre como estimado", async () => {
    stubFetch("manufatura");
    renderPage();
    await screen.findByText("PROD-1");
    const rows = document.querySelectorAll(".data-table tbody tr");
    expect(rows).toHaveLength(3);
    const semPadrao = rows[0] as HTMLElement;
    expect(within(semPadrao).getByText("n/a", { selector: ".status-badge" })).toBeInTheDocument();
    expect(within(semPadrao).getByText("n/a", { selector: "strong" })).toBeInTheDocument();
    expect(within(semPadrao).getByText(NO_PROTHEUS_STANDARD_TEXT)).toBeInTheDocument();
    expect(semPadrao.querySelector(".std-time__na")?.getAttribute("title")).toBe(NO_PROTHEUS_STANDARD_TEXT);
    const estimada = rows[1] as HTMLElement;
    expect(within(estimada).getByText("62,5 s")).toBeInTheDocument();
    expect(within(estimada).getByText("estimado · 7 amostras")).toBeInTheDocument();
    expect(within(estimada).getByText("Estimado")).toBeInTheDocument();
    // O estimado não substitui o Protheus: a coluna oficial continua n/a.
    expect(within(estimada).getByText(NO_PROTHEUS_STANDARD_TEXT)).toBeInTheDocument();
    expect(estimada.querySelector(".std-time__estimated[title^='Estimado']")?.getAttribute("title")).toContain("7 execuções reais");
    const protheus = rows[2] as HTMLElement;
    expect(within(protheus).getByText("Protheus", { selector: ".status-badge" })).toBeInTheDocument();
    expect(within(protheus).getByText("30 s")).toBeInTheDocument();
    expect(within(protheus).queryByText("n/a")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("Sem padrão");
  });

  it("não há formulário, botão de salvar/remover nem histórico do manual", async () => {
    const mock = stubFetch("manufatura");
    renderPage();
    await screen.findByText("PROD-1");
    expect(screen.getByRole("heading", { name: "Manufatura — Tempo padrão" })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /Tempo manual/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Salvar" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Remover manual|^Histórico:/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: /Manual/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Ações" })).not.toBeInTheDocument();
    expect(document.querySelector(".data-table form")).toBeNull();
    expect(mock.mock.calls.some(([path, init]) => String(path).includes("/standard-times/manual") || ["PUT", "DELETE"].includes(String(init?.method)))).toBe(false);
  });

  it("'somente sem tempo no Protheus' vem ligado e o filtro vira parâmetro da consulta", async () => {
    const mock = stubFetch("manufatura");
    renderPage();
    await screen.findByText("PROD-1");
    const toggle = screen.getByRole("checkbox", { name: "Somente sem tempo no Protheus" });
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
        return json({ status: "running", started_at: "2026-10-06T10:00:00" }, 202);
      }
      if (path.endsWith("/standard-times/estimates/recalculate/status")) {
        return json({
          status: "done",
          summary: {
            calculado_em: "2026-10-06T10:00:00",
            janela_inicio: "2026-09-01",
            janela_fim: "2026-10-05",
            execucoes_elegiveis: 1204,
            chaves_avaliadas: 340,
            chaves_estimadas: 12,
            amostra_minima: 3,
          },
        });
      }
      return undefined;
    });
    renderPage();
    await screen.findByText("PROD-1");
    fireEvent.click(screen.getByRole("button", { name: "Recalcular estimativas" }));
    const aviso = await screen.findByText(/Estimativas recalculadas: 12 de 340 operações avaliadas/);
    expect(aviso.textContent).toContain("1.204 execuções reais");
    expect(aviso.textContent).not.toContain("{");
  });
});

describe("Tempo padrão — chave mista e vigência", () => {
  const MISTA = {
    ...SEM_PADRAO,
    produto_codigo: "PROD-M",
    tempo_protheus_segundos: 30,
    estimado_vigente_desde: "2026-10-01",
    tempo_estimado_segundos: 50,
    linhas_com_protheus: 2,
    linhas_total: 5,
    fonte_efetiva: "protheus",
  };

  it("chave mista avisa em quantas OPs há Protheus (as demais ficam n/a) e mostra 'vale a partir de' do estimado", async () => {
    stubFetch("manufatura", (path) => {
      if (path.includes("/management/standard-times?")) return json(listResponse([MISTA, ESTIMADA]));
      return undefined;
    });
    renderPage();
    await screen.findByText("PROD-M");
    const rows = document.querySelectorAll(".data-table tbody tr");
    const mista = rows[0] as HTMLElement;
    expect(within(mista).getByText("Protheus em 2 de 5 OPs (as demais ficam n/a)")).toBeInTheDocument();
    const vale = within(mista).getAllByText(/^vale a partir de/);
    expect(vale).toHaveLength(1);
    expect(vale[0].textContent).toMatch(/^vale a partir de 01\/10\/2026$/);
    // Chave sem os campos novos (backend antigo) não mostra aviso nem vigência.
    const antiga = rows[1] as HTMLElement;
    expect(within(antiga).queryByText(/Protheus em/)).not.toBeInTheDocument();
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
    renderPage();
    await screen.findByText("PROD-3");
    expect(screen.queryByText(/Protheus em \d/)).not.toBeInTheDocument();
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
