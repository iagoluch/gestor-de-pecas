import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";
import { QUALITY_TEMPLATE_LEVELS } from "../config/navigation";
import { draftFromCota } from "../pages/production/QualityTemplatesPage";
import type { QualityDimension } from "../types/api";

function session(role: string) {
  return { id: 1, name: `Conta ${role}`, role, management_access: true, andon_access: true, operator_access: false };
}

function json(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: { "content-type": "application/json" } });
}

const PROD_1 = {
  produto_codigo: "PROD-1",
  produto_descricao: "Suporte lateral",
  revisao: 2,
  quantidade_cotas: 2,
  atualizado_por: "Sandro",
  atualizado_em: "2026-10-05T14:30:00",
  ativo: true,
};
const PROD_2 = { ...PROD_1, produto_codigo: "PROD-2", produto_descricao: null, revisao: 1, quantidade_cotas: 1, atualizado_por: null, atualizado_em: null };

const cota = (sequencia: number, padrao: string, descricao: string | null = null): QualityDimension => ({
  id: sequencia, sequencia, descricao, padrao, unidade: "mm",
  referencia: null, margem: null, limite_inferior: null, limite_superior: null, conformidade_automatica: true,
});

const TEMPLATE_PROD_1 = {
  id: 7, produto: "PROD-1", revisao: 2, atualizado_por: "Sandro", atualizado_em: "2026-10-05T14:30:00",
  cotas: [cota(1, "125,0 ± 0,5", "Largura"), cota(2, "40 +/- 0,2")],
};

function listResponse(items: unknown[], total = items.length, offset = 0) {
  return { items, total, limit: 100, offset };
}

type Handler = (path: string, init?: RequestInit) => Response | undefined;

function stubFetch(role: string, handler: Handler = () => undefined) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.includes("/auth/session")) return json(session(role));
    const custom = handler(path, init);
    if (custom) return custom;
    if (path.includes("/management/quality-templates?")) return json(listResponse([PROD_1, PROD_2]));
    if (path.endsWith("/api/v1/quality/templates/PROD-1")) return json({ produto: "PROD-1", template: TEMPLATE_PROD_1, can_edit: true });
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

const paths = (mock: ReturnType<typeof vi.fn>) => mock.mock.calls.map(([path]) => String(path));
const listCalls = (mock: ReturnType<typeof vi.fn>) => paths(mock).filter((path) => path.includes("/management/quality-templates?"));
const qualityCalls = (mock: ReturnType<typeof vi.fn>) => paths(mock).filter((path) => path.includes("quality-templates") || path.includes("/quality/templates"));
const postCall = (mock: ReturnType<typeof vi.fn>) => mock.mock.calls.find(([, init]) => init?.method === "POST")!;

beforeEach(() => {
  document.cookie = "gestor_csrf=csrf-teste; path=/";
});
afterEach(() => vi.restoreAllMocks());

describe("Qualidade (cotas padrão) — acesso por nível", () => {
  it("espelha os níveis do backend", () => {
    expect([...QUALITY_TEMPLATE_LEVELS]).toEqual(["admin", "qualidade"]);
  });

  it.each(["qualidade", "admin"])("a seção Qualidade aparece para %s, com a aba Cotas padrão", async (role) => {
    stubFetch(role);
    renderAt("/producao/ordens");
    const menu = await screen.findByRole("navigation", { name: "Navegação gerencial" });
    expect(within(menu).getByRole("link", { name: /Qualidade/ })).toHaveAttribute("href", "/qualidade/cotas");
    const nav = await screen.findByRole("navigation", { name: "Produção" });
    expect(within(nav).queryByRole("link", { name: "Qualidade" })).not.toBeInTheDocument();
  });

  it.each(["gestor", "manufatura", "supervisor"])("a seção Qualidade NÃO aparece para %s", async (role) => {
    stubFetch(role);
    renderAt("/producao/ordens");
    const menu = await screen.findByRole("navigation", { name: "Navegação gerencial" });
    expect(within(menu).getByRole("link", { name: /Produção/ })).toBeInTheDocument();
    expect(within(menu).queryByRole("link", { name: /Qualidade/ })).not.toBeInTheDocument();
  });

  it("a aba Cotas padrão fica dentro da seção Qualidade", async () => {
    stubFetch("qualidade");
    renderAt("/qualidade/cotas");
    const nav = await screen.findByRole("navigation", { name: "Qualidade" });
    expect(within(nav).getByRole("link", { name: "Cotas padrão" })).toHaveAttribute("href", "/qualidade/cotas");
  });

  it("o gestor que abre a URL direta recebe o aviso e nenhuma API de cotas é chamada", async () => {
    const mock = stubFetch("gestor");
    renderAt("/qualidade/cotas");
    expect(await screen.findByText("Acesso restrito à Qualidade")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cadastrar produto" })).not.toBeInTheDocument();
    expect(qualityCalls(mock)).toHaveLength(0);
  });
});

describe("Qualidade (cotas padrão) — lista", () => {
  it("mostra produto, descrição, revisão, nº de cotas e quem atualizou, com paginação de 100", async () => {
    const mock = stubFetch("qualidade");
    renderAt("/qualidade/cotas");
    await screen.findByText("PROD-1");
    const rows = document.querySelectorAll(".data-table tbody tr");
    expect(rows).toHaveLength(2);
    const primeira = rows[0] as HTMLElement;
    expect(within(primeira).getByText("Suporte lateral")).toBeInTheDocument();
    expect(within(primeira).getByText("Rev. 2")).toBeInTheDocument();
    expect(within(primeira).getByText("Sandro")).toBeInTheDocument();
    expect(within(primeira).getByText("2")).toBeInTheDocument();
    const segunda = rows[1] as HTMLElement;
    expect(within(segunda).getAllByText("—").length).toBeGreaterThanOrEqual(3);
    expect(listCalls(mock)[0]).toContain("limit=100");
    expect(listCalls(mock)[0]).toContain("offset=0");
  });

  it("a busca vira parâmetro `produto` e volta para a primeira página", async () => {
    const mock = stubFetch("qualidade");
    renderAt("/qualidade/cotas");
    await screen.findByText("PROD-1");
    fireEvent.change(screen.getByLabelText("Produto"), { target: { value: "PROD-9" } });
    await waitFor(() => expect(listCalls(mock).at(-1)).toContain("produto=PROD-9"));
    expect(listCalls(mock).at(-1)).toContain("offset=0");
  });

  it("pagina de 100 em 100", async () => {
    const mock = stubFetch("qualidade", (path) => {
      if (path.includes("/management/quality-templates?")) return json(listResponse([PROD_1, PROD_2], 150, path.includes("offset=100") ? 100 : 0));
      return undefined;
    });
    renderAt("/qualidade/cotas");
    await screen.findByText("Mostrando 1–2 de 150");
    fireEvent.click(screen.getByRole("button", { name: "Próxima" }));
    await waitFor(() => expect(listCalls(mock).at(-1)).toContain("offset=100"));
  });

  it("403 vira mensagem em português, sem o código técnico", async () => {
    stubFetch("qualidade", (path) => {
      if (path.includes("/management/quality-templates?")) return json({ code: "quality_templates_access_denied", message: "negado" }, 403);
      return undefined;
    });
    renderAt("/qualidade/cotas");
    expect(await screen.findByText(/Seu perfil não tem acesso às cotas padrão/)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("quality_templates_access_denied");
  });

  it("lista vazia explica o próximo passo", async () => {
    stubFetch("qualidade", (path) => (path.includes("/management/quality-templates?") ? json(listResponse([])) : undefined));
    renderAt("/qualidade/cotas");
    expect(await screen.findByText("Nenhum produto com cotas cadastradas")).toBeInTheDocument();
  });
});

describe("Qualidade (cotas padrão) — edição", () => {
  it("abre o editor pela linha com as cotas salvas, salva com CSRF e recarrega a lista", async () => {
    const mock = stubFetch("qualidade", (path, init) => {
      if (path.endsWith("/api/v1/quality/templates") && init?.method === "POST") return json({ ok: true, message: "Cotas padrão atualizadas.", code: null, data: {} });
      return undefined;
    });
    renderAt("/qualidade/cotas");
    await screen.findByText("PROD-1");
    const antes = listCalls(mock).length;

    fireEvent.click(screen.getByRole("button", { name: "Abrir cotas de PROD-1" }));
    const dialogo = await screen.findByRole("dialog", { name: "Cotas padrão — PROD-1" });
    expect(await within(dialogo).findByLabelText("Padrão nominal da cota 1")).toHaveValue("125,0");
    expect(within(dialogo).getByLabelText("Tolerância da cota 1")).toHaveValue("0,5");
    expect(within(dialogo).getByLabelText("Padrão nominal da cota 2")).toHaveValue("40");
    expect(within(dialogo).getByLabelText("Tolerância da cota 2")).toHaveValue("0,2");
    expect(within(dialogo).getByText(/Revisão atual: 2\. Ao salvar, é criada a revisão 3/)).toBeInTheDocument();

    fireEvent.change(within(dialogo).getByLabelText("Tolerância da cota 1"), { target: { value: "0,6" } });
    fireEvent.click(within(dialogo).getByRole("button", { name: "Salvar cotas do produto" }));

    await screen.findByText("Cotas padrão de PROD-1 atualizadas: revisão 3.");
    const post = postCall(mock);
    expect(String(post[0])).toBe("/api/v1/quality/templates");
    expect(JSON.parse(String(post[1]?.body))).toEqual({
      produto: "PROD-1",
      cotas: [
        { sequencia: 1, descricao: "Largura", padrao: "125,0 ± 0,6", unidade: "mm" },
        { sequencia: 2, descricao: null, padrao: "40 ± 0,2", unidade: "mm" },
      ],
    });
    expect(new Headers(post[1]?.headers).get("X-CSRF-Token")).toBe("csrf-teste");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(listCalls(mock).length).toBeGreaterThan(antes));
  });

  it("erro do servidor aparece em português dentro do editor, que continua aberto", async () => {
    stubFetch("qualidade", (path, init) => {
      if (path.endsWith("/api/v1/quality/templates") && init?.method === "POST") {
        return json({ code: "qualidade_template_protegido", message: "msg do servidor", request_id: "r1" }, 409);
      }
      return undefined;
    });
    renderAt("/qualidade/cotas");
    await screen.findByText("PROD-1");
    fireEvent.click(screen.getByRole("button", { name: "Editar cotas de PROD-1" }));
    const dialogo = await screen.findByRole("dialog");
    await within(dialogo).findByLabelText("Padrão nominal da cota 1");
    fireEvent.click(within(dialogo).getByRole("button", { name: "Salvar cotas do produto" }));

    expect(await within(dialogo).findByText(/só podem ser alteradas pela Qualidade ou pela administração/)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("qualidade_template_protegido");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("cadastrar produto novo: pede o código, abre o editor vazio e grava a primeira revisão", async () => {
    const mock = stubFetch("qualidade", (path, init) => {
      if (path.endsWith("/api/v1/quality/templates/NOVO-1")) return json({ produto: "NOVO-1", template: null, can_edit: true });
      if (path.endsWith("/api/v1/quality/templates") && init?.method === "POST") return json({ ok: true, message: "Cotas padrão salvas para o produto.", code: null, data: {} });
      return undefined;
    });
    renderAt("/qualidade/cotas");
    await screen.findByText("PROD-1");

    fireEvent.click(screen.getByRole("button", { name: "Cadastrar produto" }));
    const dialogo = await screen.findByRole("dialog", { name: "Cadastrar produto" });
    const continuar = within(dialogo).getByRole("button", { name: "Continuar" });
    expect(continuar).toBeDisabled();
    fireEvent.change(within(dialogo).getByLabelText("Código do produto"), { target: { value: " NOVO-1 " } });
    fireEvent.click(continuar);

    const editor = await screen.findByRole("dialog", { name: "Cotas padrão — NOVO-1" });
    fireEvent.change(await within(editor).findByLabelText("Padrão nominal da cota 1"), { target: { value: "10,0" } });
    fireEvent.change(within(editor).getByLabelText("Tolerância da cota 1"), { target: { value: "0,1" } });
    fireEvent.click(within(editor).getByRole("button", { name: "Salvar cotas do produto" }));

    await screen.findByText("Cotas padrão de NOVO-1 cadastradas.");
    expect(JSON.parse(String(postCall(mock)[1]?.body))).toEqual({
      produto: "NOVO-1",
      cotas: [{ sequencia: 1, descricao: null, padrao: "10,0 ± 0,1", unidade: "mm" }],
    });
  });

  it("cadastrar um código que já tem cotas abre a edição, com aviso, em vez de sobrescrever", async () => {
    stubFetch("qualidade");
    renderAt("/qualidade/cotas");
    await screen.findByText("PROD-1");
    fireEvent.click(screen.getByRole("button", { name: "Cadastrar produto" }));
    const dialogo = await screen.findByRole("dialog");
    fireEvent.change(within(dialogo).getByLabelText("Código do produto"), { target: { value: "PROD-1" } });
    fireEvent.click(within(dialogo).getByRole("button", { name: "Continuar" }));

    expect(await screen.findByText(/O produto PROD-1 já tinha cotas cadastradas; você está editando\./)).toBeInTheDocument();
    expect(await screen.findByLabelText("Padrão nominal da cota 1")).toHaveValue("125,0");
  });
});

describe("draftFromCota", () => {
  it.each([
    ["125,0 ± 0,5", "125,0", "0,5"],
    ["40 +/- 0,2", "40", "0,2"],
    ["12.0 +- 0.2", "12.0", "0.2"],
    ["453", "453", "0"],
    ["Furo livre", "Furo livre", ""],
  ])("converte %j em padrão e tolerância", (padrao, nominal, tolerancia) => {
    expect(draftFromCota(cota(3, padrao, "x"), 2)).toEqual({ sequencia: 3, descricao: "x", nominal, tolerancia });
  });
});
