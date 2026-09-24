import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ManagementBadgesPage } from "../pages/home/BadgesPage";

const CRACHAS = [
  { id: 1, cracha: "1001", nome: "Ana Souza", ativo: true, fonte: "cadastro", autorizador_retrabalho: true },
  { id: 2, cracha: "1002", nome: "Bruno Lima", ativo: true, fonte: "cadastro", autorizador_retrabalho: false },
  { id: 3, cracha: "1003", nome: "Carla Dias", ativo: false, fonte: "gestao", autorizador_retrabalho: false },
];

function payload(items = CRACHAS) {
  const autorizados = items.filter((item) => item.autorizador_retrabalho && item.ativo);
  return {
    items,
    count: items.length,
    active: items.filter((item) => item.ativo).length,
    authorizers: autorizados,
    authorizer_count: autorizados.length,
  };
}

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function stubFetch(items = CRACHAS) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    if (path.includes("/management/badges") && method === "GET") return json(payload(items));
    if (path.includes("/management/badges") && method === "POST") return json({ ok: true, item: items[0] });
    return json({ code: "not_found", message: "Não encontrado" }, 404);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function renderBadges() {
  return render(<MemoryRouter><ManagementBadgesPage /></MemoryRouter>);
}

function corpoDaTabela() {
  return document.querySelector(".data-table tbody")?.textContent ?? "";
}

function linhas() {
  return document.querySelectorAll(".data-table tbody tr").length;
}

beforeEach(() => window.sessionStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("Crachás — organização e filtros", () => {
  it("lista os crachás com situação, perfil e origem legíveis", async () => {
    stubFetch();
    renderBadges();

    await waitFor(() => expect(linhas()).toBe(3));
    expect(screen.getByText("3 crachás cadastrados")).toBeInTheDocument();
    expect(corpoDaTabela()).toContain("Responsável por retrabalho");
    expect(screen.getAllByText("Ativo").length).toBeGreaterThan(0);
    expect(screen.getByText("Inativo")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/autorizador_retrabalho|tipo_setor/);
  });

  it("filtra por situação", async () => {
    stubFetch();
    renderBadges();
    await waitFor(() => expect(linhas()).toBe(3));

    fireEvent.change(screen.getByLabelText("Situação"), { target: { value: "inativo" } });

    await waitFor(() => expect(linhas()).toBe(1));
    expect(corpoDaTabela()).toContain("Carla Dias");
  });

  it("filtra por perfil", async () => {
    stubFetch();
    renderBadges();
    await waitFor(() => expect(linhas()).toBe(3));

    fireEvent.change(screen.getByLabelText("Perfil"), { target: { value: "responsavel" } });

    await waitFor(() => expect(linhas()).toBe(1));
    expect(corpoDaTabela()).toContain("Ana Souza");
  });

  it("filtra por origem do cadastro", async () => {
    stubFetch();
    renderBadges();
    await waitFor(() => expect(linhas()).toBe(3));

    fireEvent.change(screen.getByLabelText("Origem do cadastro"), { target: { value: "gestao" } });

    await waitFor(() => expect(linhas()).toBe(1));
    expect(corpoDaTabela()).toContain("Carla Dias");
  });

  it("busca por crachá e por nome", async () => {
    stubFetch();
    renderBadges();
    await waitFor(() => expect(linhas()).toBe(3));

    const busca = screen.getByLabelText("Buscar por crachá ou nome");
    fireEvent.change(busca, { target: { value: "1002" } });
    await waitFor(() => expect(linhas()).toBe(1));
    expect(corpoDaTabela()).toContain("Bruno Lima");

    fireEvent.change(busca, { target: { value: "carla" } });
    await waitFor(() => expect(corpoDaTabela()).toContain("Carla Dias"));
    expect(linhas()).toBe(1);
  });

  it("combina filtros, mostra estado vazio humano e limpa a seleção", async () => {
    stubFetch();
    renderBadges();
    await waitFor(() => expect(linhas()).toBe(3));

    fireEvent.change(screen.getByLabelText("Situação"), { target: { value: "ativo" } });
    fireEvent.change(screen.getByLabelText("Perfil"), { target: { value: "responsavel" } });
    await waitFor(() => expect(linhas()).toBe(1));

    fireEvent.change(screen.getByLabelText("Origem do cadastro"), { target: { value: "gestao" } });
    await waitFor(() => expect(screen.getByText("Nenhum crachá no filtro atual")).toBeInTheDocument());
    expect(document.body.textContent).not.toMatch(/sem_registros|no_records|\[\]/);

    fireEvent.click(screen.getByRole("button", { name: "Limpar filtros" }));
    await waitFor(() => expect(linhas()).toBe(3));
    expect((screen.getByLabelText("Situação") as HTMLSelectElement).value).toBe("");
  });

  it("mostra estado vazio humano quando não há crachá cadastrado", async () => {
    stubFetch([]);
    renderBadges();

    expect(await screen.findByText("Nenhum crachá cadastrado")).toBeInTheDocument();
    expect(screen.getByText(/nenhuma exceção operacional pode ser autorizada/)).toBeInTheDocument();
  });

  it("edita o crachá no diálogo preservando o contrato de cadastro", async () => {
    const mock = stubFetch();
    renderBadges();
    await waitFor(() => expect(linhas()).toBe(3));

    fireEvent.click(screen.getAllByRole("button", { name: "Editar" })[0]);
    expect(await screen.findByRole("dialog", { name: "Editar crachá" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Nome"), { target: { value: "Ana Souza Silva" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar" }));

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Crachá salvo"));
    const post = mock.mock.calls.find(([, init]) => (init as RequestInit)?.method === "POST");
    expect(JSON.parse(String((post?.[1] as RequestInit).body))).toEqual({
      cracha: "1001",
      nome: "Ana Souza Silva",
      ativo: true,
      autorizador_retrabalho: true,
    });
  });

  it("ativa e desativa pela ação da linha", async () => {
    const mock = stubFetch();
    renderBadges();
    await waitFor(() => expect(linhas()).toBe(3));

    fireEvent.click(screen.getAllByRole("button", { name: "Desativar" })[0]);
    fireEvent.click(await screen.findByRole("button", { name: "Desativar crachá" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Crachá salvo"));
    let corpo = JSON.parse(String((mock.mock.calls.filter(([, init]) => (init as RequestInit)?.method === "POST").at(-1)?.[1] as RequestInit).body));
    expect(corpo.ativo).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Ativar" }));
    await waitFor(() => {
      corpo = JSON.parse(String((mock.mock.calls.filter(([, init]) => (init as RequestInit)?.method === "POST").at(-1)?.[1] as RequestInit).body));
      expect(corpo.ativo).toBe(true);
    });
  });

  it("mantém a designação de responsável por crachá, sem autenticação nova", async () => {
    const mock = stubFetch();
    renderBadges();
    await waitFor(() => expect(linhas()).toBe(3));

    fireEvent.click(screen.getAllByRole("button", { name: "Tornar responsável" })[0]);

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Crachá salvo"));
    const corpo = JSON.parse(String((mock.mock.calls.filter(([, init]) => (init as RequestInit)?.method === "POST").at(-1)?.[1] as RequestInit).body));
    expect(corpo).toMatchObject({ autorizador_retrabalho: true });
    expect(Object.keys(corpo)).toEqual(["cracha", "nome", "ativo", "autorizador_retrabalho"]);
  });
});
