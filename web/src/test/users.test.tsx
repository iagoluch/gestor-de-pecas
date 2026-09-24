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
});
