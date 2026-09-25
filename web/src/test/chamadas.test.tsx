import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ManagementChamadasPage } from "../pages/home/ChamadasPage";

vi.mock("../auth/AuthContext", () => {
  const auth = { user: { id: 1, name: "Admin", role: "admin" } };
  return { useAuth: () => auth, useOptionalAuth: () => auth };
});

const CONTATOS = [{ id: 7, nome: "Carla Souza", funcao: "Manutenção", ativo: true, padrao_gestao: false, setores: [] }];

function stubFetch() {
  const mock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    const body = url.includes("/contatos") ? { items: CONTATOS } : { items: [] };
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

const deletes = (mock: ReturnType<typeof stubFetch>) => mock.mock.calls.filter(([, init]) => init?.method === "DELETE");

afterEach(() => vi.restoreAllMocks());

// O menu "⋯" usa popover nativo; o jsdom o esconde mas não implementa showPopover, daí `hidden: true` nos itens.
describe("Contatos de chamada — GE-01", () => {
  it("só remove o contato depois da confirmação", async () => {
    const mock = stubFetch();
    render(<MemoryRouter><ManagementChamadasPage /></MemoryRouter>);
    const remover = await screen.findByRole("menuitem", { name: "Remover", hidden: true });

    fireEvent.click(remover);
    fireEvent.click(await screen.findByRole("button", { name: "Cancelar" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(deletes(mock)).toHaveLength(0);

    fireEvent.click(remover);
    fireEvent.click(await screen.findByRole("button", { name: "Remover contato" }));
    await waitFor(() => expect(deletes(mock)).toHaveLength(1));
    expect(String(deletes(mock)[0][0])).toContain("/api/v1/chamadas/admin/contatos/7");
  });
});
