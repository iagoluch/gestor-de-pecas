import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";

describe("tela de login", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("começa no Usuário e o Enter ali leva à Senha sem tentar entrar", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/auth/session")) {
        return new Response(JSON.stringify({ code: "not_authenticated", message: "Sessão ausente" }), { status: 401, headers: { "content-type": "application/json" } });
      }
      return new Response(JSON.stringify({ code: "not_found", message: "Não encontrado" }), { status: 404, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter initialEntries={["/login"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    await screen.findByRole("heading", { name: "Entrar no Gestor" });

    const usuario = screen.getByLabelText("Usuário");
    expect(usuario).toHaveFocus();
    fireEvent.change(usuario, { target: { value: "operador" } });
    fireEvent.keyDown(usuario, { key: "Enter" });

    expect(screen.getByLabelText("Senha")).toHaveFocus();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/auth/login"))).toBe(false);
  });
});
