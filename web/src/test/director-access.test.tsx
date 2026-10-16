import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";
import { DIRECTOR_LEVELS } from "../config/navigation";

function session(role: string) {
  return { id: 1, name: `Conta ${role}`, role, management_access: true, andon_access: true, operator_access: false };
}

function json(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: { "content-type": "application/json" } });
}

function stubFetch(role: string) {
  const mock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.includes("/auth/session")) return json(session(role));
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

beforeEach(() => {
  document.cookie = "gestor_csrf=csrf-teste; path=/";
});
afterEach(() => vi.restoreAllMocks());

describe("Diretoria — acesso por nível", () => {
  it("espelha os níveis do backend", () => {
    expect([...DIRECTOR_LEVELS]).toEqual(["admin", "diretoria"]);
  });

  it.each(["diretoria", "admin"])("o item Diretoria aparece no menu para %s", async (role) => {
    stubFetch(role);
    renderAt("/producao/ordens");
    const menu = await screen.findByRole("navigation", { name: "Navegação gerencial" });
    expect(within(menu).getByRole("link", { name: /Diretoria/ })).toHaveAttribute("href", "/diretoria");
  });

  it("o item Diretoria NÃO aparece para o gestor", async () => {
    stubFetch("gestor");
    renderAt("/producao/ordens");
    const menu = await screen.findByRole("navigation", { name: "Navegação gerencial" });
    expect(within(menu).getByRole("link", { name: /Produção/ })).toBeInTheDocument();
    expect(within(menu).queryByRole("link", { name: /Diretoria/ })).not.toBeInTheDocument();
  });

  it.each(["diretoria", "admin"])("a rota /diretoria mostra a página para %s", async (role) => {
    stubFetch(role);
    renderAt("/diretoria");
    expect(await screen.findByRole("heading", { name: "Diretoria" })).toBeInTheDocument();
  });

  it("o gestor que abre /diretoria é redirecionado e não vê a página", async () => {
    stubFetch("gestor");
    renderAt("/diretoria");
    // Redireciona para a tela inicial da gestão; o menu aparece sem Diretoria.
    const menu = await screen.findByRole("navigation", { name: "Navegação gerencial" });
    expect(within(menu).queryByRole("link", { name: /Diretoria/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Diretoria" })).not.toBeInTheDocument();
  });
});
