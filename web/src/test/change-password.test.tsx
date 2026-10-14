import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

const operador = {
  id: 7, name: "Terminal Dobra", role: "operador_dobra",
  management_access: false, andon_access: false, operator_access: true,
  password_change_required: false,
};
const gestorPendente = {
  id: 3, name: "Bruna", role: "gestor",
  management_access: true, andon_access: true, operator_access: false,
  password_change_required: true,
};

function renderAt(path: string, fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal("fetch", fetchMock);
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider><App /></AuthProvider>
    </MemoryRouter>,
  );
}

describe("troca obrigatória da senha padrão (SEC-05)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("gestão na senha padrão vê só a etapa de nova senha e é liberada depois de trocar", async () => {
    const chamadas: string[] = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      chamadas.push(path);
      if (path.includes("/auth/session")) return json(gestorPendente);
      if (path.includes("/auth/password")) {
        expect(JSON.parse(String(init?.body))).toEqual({ new_password: "senha-nova-forte" });
        return json({ ...gestorPendente, password_change_required: false });
      }
      return json({}, 200);
    });
    renderAt("/inicio/visao-geral", fetchMock);

    expect(await screen.findByRole("heading", { name: "Defina uma nova senha" })).toBeTruthy();
    // Nenhuma tela de gestão é carregada enquanto a senha não for trocada.
    expect(chamadas.every((path) => path.includes("/auth/"))).toBe(true);

    const [nova, repetida] = screen.getAllByLabelText(/nova senha/i);
    fireEvent.change(nova, { target: { value: "123456" } });
    fireEvent.change(repetida, { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar e entrar" }));
    expect((await screen.findByRole("alert")).textContent).toMatch(/pelo menos 8/);

    fireEvent.change(nova, { target: { value: "senha-nova-forte" } });
    fireEvent.change(repetida, { target: { value: "senha-nova-forte" } });
    fireEvent.click(screen.getByRole("button", { name: "Salvar e entrar" }));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Defina uma nova senha" })).toBeNull());
    expect(chamadas.some((path) => path.includes("/auth/password"))).toBe(true);
  });

  it("operador com a senha padrão não passa pela etapa", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes("/auth/session")) return json(operador);
      if (path.includes("/operator/context")) {
        return json({
          sector: "Dobra",
          route: "Dobra",
          resources: ["1303", "2204"],
          fixed_resource: false,
          station_profile_required: false,
          has_setup: true,
          automatic_queue: false,
          workflow: "workbench",
        });
      }
      return json({}, 200);
    });
    renderAt("/operador", fetchMock);
    expect(await screen.findByText("2204")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Defina uma nova senha" })).toBeNull();
  });
});
