import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ManagementUsersPage } from "../pages/home/UsersPage";

vi.mock("../auth/AuthContext", () => {
  const auth = { user: { id: 1, name: "Admin", role: "admin" } };
  return { useAuth: () => auth, useOptionalAuth: () => auth };
});

const USUARIOS = [
  { id: 1, nome: "Admin", nivel: "admin", ativo: true },
  { id: 2, nome: "Bruno Lima", nivel: "gestor", ativo: true },
];

function stubFetch() {
  const mock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    const body = (init?.method ?? "GET") === "POST"
      ? { ok: true, item: USUARIOS[1] }
      : { items: USUARIOS, count: 2, active: 2, levels: ["admin", "gestor"] };
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

const posts = (mock: ReturnType<typeof stubFetch>) => mock.mock.calls.filter(([, init]) => init?.method === "POST");

afterEach(() => vi.restoreAllMocks());

describe("Cadastro de usuários — GE-01/GE-02", () => {
  it("não deixa o admin desativar a própria conta e explica o motivo", async () => {
    stubFetch();
    render(<MemoryRouter><ManagementUsersPage /></MemoryRouter>);
    const [propria, outra] = await screen.findAllByRole("button", { name: "Desativar" });
    expect(propria).toBeDisabled();
    expect(propria).toHaveAttribute("title", expect.stringContaining("Sua própria conta"));
    expect(outra).toBeEnabled();
  });

  it("pede confirmação antes de desativar outro usuário", async () => {
    const mock = stubFetch();
    render(<MemoryRouter><ManagementUsersPage /></MemoryRouter>);
    const outra = (await screen.findAllByRole("button", { name: "Desativar" }))[1];

    fireEvent.click(outra);
    fireEvent.click(await screen.findByRole("button", { name: "Cancelar" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(posts(mock)).toHaveLength(0);

    fireEvent.click(outra);
    fireEvent.click(await screen.findByRole("button", { name: "Desativar usuário" }));
    await waitFor(() => expect(posts(mock)).toHaveLength(1));
    expect(JSON.parse(String(posts(mock)[0][1]?.body))).toMatchObject({ id: 2, ativo: false });
  });

  it("só exclui outro usuário depois de confirmar, e nunca a própria conta", async () => {
    const mock = stubFetch();
    render(<MemoryRouter><ManagementUsersPage /></MemoryRouter>);
    const [propria, outra] = await screen.findAllByRole("button", { name: "Excluir" });
    expect(propria).toBeDisabled();

    fireEvent.click(outra);
    fireEvent.click(await screen.findByRole("button", { name: "Cancelar" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const deletes = () => mock.mock.calls.filter(([, init]) => init?.method === "DELETE");
    expect(deletes()).toHaveLength(0);

    fireEvent.click(outra);
    fireEvent.click(await screen.findByRole("button", { name: "Excluir usuário" }));
    await waitFor(() => expect(deletes()).toHaveLength(1));
    expect(String(deletes()[0][0])).toContain("/api/v1/management/users/2");
  });

  it("cria um nível copiando outro e só exclui o nível depois de confirmar", async () => {
    const nivel = { nome: "supervisor", rotulo: "Supervisor", nivel_base: "gestor" };
    const mock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = (init?.method ?? "GET") === "GET"
        ? { items: USUARIOS, count: 2, active: 2, levels: ["admin", "gestor", "supervisor"], custom_levels: [nivel] }
        : { ok: true, item: nivel };
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", mock);
    render(<MemoryRouter><ManagementUsersPage /></MemoryRouter>);

    fireEvent.click(await screen.findByRole("button", { name: "Novo nível" }));
    fireEvent.change(await screen.findByLabelText(/Nome do nível/), { target: { value: "Supervisor" } });
    fireEvent.click(screen.getByRole("button", { name: "Criar nível" }));
    await waitFor(() => expect(posts(mock)).toHaveLength(1));
    expect(String(posts(mock)[0][0])).toContain("/api/v1/management/levels");
    expect(JSON.parse(String(posts(mock)[0][1]?.body))).toMatchObject({ rotulo: "Supervisor", nivel_base: "gestor" });

    const linha = (await screen.findAllByText("Supervisor")).map((el) => el.closest("tr")).find(Boolean)!;
    fireEvent.click(linha.querySelector("button")!);
    fireEvent.click(await screen.findByRole("button", { name: "Excluir nível" }));
    const deletes = () => mock.mock.calls.filter(([, init]) => init?.method === "DELETE");
    await waitFor(() => expect(deletes()).toHaveLength(1));
    expect(String(deletes()[0][0])).toContain("/api/v1/management/levels/supervisor");
  });

  it("filtra por unidade e grava a unidade digitada no cadastro", async () => {
    const comUnidade = [USUARIOS[0], { ...USUARIOS[1], unidade: "4" }];
    const mock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      const body = (init?.method ?? "GET") === "GET"
        ? { items: comUnidade, count: 2, active: 2, levels: ["admin", "gestor"] }
        : { ok: true, item: comUnidade[1] };
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", mock);
    render(<MemoryRouter><ManagementUsersPage /></MemoryRouter>);

    fireEvent.change(await screen.findByLabelText("Unidade"), { target: { value: "4" } });
    await waitFor(() => expect(screen.queryByText("Admin")).toBeNull());
    expect(screen.getByText("Bruno Lima")).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: "Editar" })[0]);
    fireEvent.change(await screen.findByPlaceholderText("Ex.: 4"), { target: { value: " 5 " } });
    fireEvent.click(screen.getByRole("button", { name: /^Salvar/ }));
    await waitFor(() => expect(posts(mock)).toHaveLength(1));
    expect(JSON.parse(String(posts(mock)[0][1]?.body))).toMatchObject({ id: 2, unidade: "5" });
  });

  it("filtra por tela: gestão x apontamento", async () => {
    window.sessionStorage.clear(); // o teste de unidade deixa filtro salvo
    const lista = [
      { ...USUARIOS[0], tela: "gestao" },
      { id: 3, nome: "Carla Corte", nivel: "operador_corte", ativo: true, tela: "apontamento" },
    ];
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ items: lista, count: 2, active: 2, levels: ["admin", "operador_corte"] }),
      { status: 200, headers: { "content-type": "application/json" } },
    )));
    render(<MemoryRouter><ManagementUsersPage /></MemoryRouter>);

    fireEvent.change(await screen.findByLabelText("Tela"), { target: { value: "apontamento" } });
    await waitFor(() => expect(screen.queryByText("Admin")).toBeNull());
    expect(screen.getByText("Carla Corte")).toBeInTheDocument();
  });
});
