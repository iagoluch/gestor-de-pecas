import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";
import { managementSections, sectionVisibleFor, tabVisibleFor } from "../config/navigation";
import { formatStopDuration } from "../pages/maintenance/MaintenanceSuggestionsPage";
import type { MaintenanceSuggestion } from "../types/maintenance";

function json(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), { status, headers: { "content-type": "application/json" } });
}

const session = (role: string, assigned_level: string | null = role) => ({
  id: 1, name: `Conta ${role}`, role, assigned_level, management_access: true, andon_access: true, operator_access: false,
});

const item = (id: number, extra: Partial<MaintenanceSuggestion> = {}): MaintenanceSuggestion => ({
  id, recurso: `Recurso ${id}`, setor: "Usinagem", parada_inicio: "2026-10-26T08:00:00", parada_fim: "2026-10-26T08:25:00",
  parada_segundos: 1500, motivo: "Quebra de ferramenta", op: `OP${id}`, status: "sugerida", criada_em: "2026-10-26T08:30:00",
  decidido_por_id: null, decidido_por_nome: null, decidido_em: null, nota: null, ...extra,
});

const lista = (items: MaintenanceSuggestion[], status = "sugerida") => ({ status, limit: 200, count: items.length, items });

type Handler = (path: string, init?: RequestInit) => Response;

function stub(user: ReturnType<typeof session>, handler: Handler) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.includes("/auth/session")) return json(user);
    if (path.includes("/maintenance/")) return handler(path, init);
    return json({ code: "not_found", message: "Não encontrado" }, 404);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

function renderAt(route: string) {
  return render(<MemoryRouter initialEntries={[route]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
}

const calls = (mock: ReturnType<typeof stub>, fragment: string) =>
  mock.mock.calls.filter(([path]) => String(path).includes(fragment));

afterEach(() => vi.restoreAllMocks());

describe("Manutenção — sugestões de paradas", () => {
  it("lista as sugestões com duração humana e o texto de apoio; mantenedor tem nível efetivo lider", async () => {
    const mock = stub(session("lider", "manutencao"), () => json(lista([item(1), item(2, { motivo: null, op: null, parada_segundos: 3900 })])));
    renderAt("/manutencao/sugestoes");
    expect(await screen.findByText("Recurso 1")).toBeInTheDocument();
    expect(screen.getByText("25 min")).toBeInTheDocument();
    expect(screen.getByText("1 h 05 min")).toBeInTheDocument();
    expect(screen.getByText("Quebra de ferramenta")).toBeInTheDocument();
    expect(screen.getByText(/nada é enviado ao TOTVS/)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Aceitar" })).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: "Descartar" })).toHaveLength(2);
    expect(String(calls(mock, "/maintenance/")[0][0])).toContain("/api/v1/maintenance/suggestions?status=sugerida");
  });

  it("Aceitar chama POST /accept com a nota e recarrega a lista", async () => {
    let aceita = false;
    const mock = stub(session("lider", "manutencao"), (path, init) => {
      if (path.endsWith("/accept")) {
        aceita = true;
        return json({ ok: true, item: item(7, { status: "aceita" }) });
      }
      expect(init?.method ?? "GET").toBe("GET");
      return json(lista(aceita ? [] : [item(7)]));
    });
    renderAt("/manutencao/sugestoes");
    await screen.findByText("Recurso 7");
    fireEvent.change(screen.getByLabelText("Nota opcional para Recurso 7"), { target: { value: " troca de fresa " } });
    fireEvent.click(screen.getByRole("button", { name: "Aceitar" }));
    expect(await screen.findByText("Sugestão de Recurso 7 aceita.")).toBeInTheDocument();
    const [post] = calls(mock, "/suggestions/7/accept");
    expect(post[1]?.method).toBe("POST");
    expect(JSON.parse(String(post[1]?.body))).toEqual({ nota: "troca de fresa" });
    await waitFor(() => expect(screen.queryByText("Recurso 7")).not.toBeInTheDocument());
  });

  it("Descartar sem nota chama POST /discard sem corpo", async () => {
    const mock = stub(session("admin"), (path) => path.endsWith("/discard")
      ? json({ ok: true, item: item(3, { status: "descartada" }) })
      : json(lista([item(3)])));
    renderAt("/manutencao/sugestoes");
    await screen.findByText("Recurso 3");
    fireEvent.click(screen.getByRole("button", { name: "Descartar" }));
    expect(await screen.findByText("Sugestão de Recurso 3 descartada.")).toBeInTheDocument();
    expect(calls(mock, "/suggestions/3/discard")[0][1]?.body).toBeUndefined();
  });

  it("409 mostra 'Já decidida por X' e recarrega a lista", async () => {
    let gets = 0;
    const mock = stub(session("lider", "manutencao"), (path) => {
      if (path.endsWith("/accept")) {
        return json({
          code: "maintenance_suggestion_already_decided", message: "x",
          details: { status: "aceita", decidido_por_nome: "Carlos Mantenedor", decidido_em: "2026-10-26T09:00:00" },
        }, 409);
      }
      gets += 1;
      return json(lista(gets === 1 ? [item(5)] : []));
    });
    renderAt("/manutencao/sugestoes");
    await screen.findByText("Recurso 5");
    fireEvent.click(screen.getByRole("button", { name: "Aceitar" }));
    expect(await screen.findByText(/Já decidida por Carlos Mantenedor/)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("Recurso 5")).not.toBeInTheDocument());
    expect(calls(mock, "/maintenance/suggestions?status=sugerida").length).toBeGreaterThanOrEqual(2);
  });

  it("aba Aceitas mostra quem decidiu, quando e a nota, sem botões de decisão", async () => {
    stub(session("admin"), (path) => path.includes("status=aceita")
      ? json(lista([item(9, { status: "aceita", decidido_por_nome: "Carlos Mantenedor", decidido_em: "2026-10-26T09:00:00", nota: "peça trocada" })], "aceita"))
      : json(lista([])));
    renderAt("/manutencao/sugestoes");
    await screen.findByText("Nenhuma sugestão pendente.");
    fireEvent.click(screen.getByRole("tab", { name: "Aceitas" }));
    expect(await screen.findByText("Carlos Mantenedor")).toBeInTheDocument();
    expect(screen.getByText("peça trocada")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Aceitar" })).not.toBeInTheDocument();
  });

  it("líder comum e gestor não veem o menu e, pela URL direta, a API nem é chamada", async () => {
    for (const user of [session("lider", "lider"), session("gestor", "gestor"), session("lider", null)]) {
      const mock = stub(user, () => json(lista([])));
      const { unmount } = renderAt("/manutencao/sugestoes");
      expect(await screen.findByText("Acesso restrito à Manutenção")).toBeInTheDocument();
      expect(calls(mock, "/maintenance/")).toHaveLength(0);
      expect(screen.queryByRole("link", { name: /Manutenção/ })).not.toBeInTheDocument();
      unmount();
      vi.restoreAllMocks();
    }
  });

  it("o item de menu Manutenção aparece para o mantenedor (nível atribuído) e para o admin", async () => {
    stub(session("lider", "manutencao"), () => json(lista([])));
    renderAt("/inicio/visao-geral");
    const menu = await screen.findByRole("link", { name: /Manutenção/ });
    expect(menu).toHaveAttribute("href", "/manutencao/sugestoes");
  });

  it("regra de visibilidade: nível atribuído manutencao ou admin; mais ninguém", () => {
    const section = managementSections.find((candidate) => candidate.id === "maintenance")!;
    const tab = section.tabs[0];
    expect(sectionVisibleFor(section, "lider", [], "manutencao")).toBe(true);
    expect(tabVisibleFor(tab, "lider", [], "manutencao")).toBe(true);
    expect(sectionVisibleFor(section, "admin", [], "admin")).toBe(true);
    expect(sectionVisibleFor(section, "lider", [], "lider")).toBe(false);
    expect(sectionVisibleFor(section, "gestor", [], null)).toBe(false);
    expect(sectionVisibleFor(section, "qualidade", [], "qualidade")).toBe(false);
    // Seções com `levels` sem `assignedLevels` não ganham acesso pelo nível atribuído.
    const quality = managementSections.find((candidate) => candidate.id === "quality")!;
    expect(sectionVisibleFor(quality, "lider", [], "manutencao")).toBe(false);
  });

  it("duração humana", () => {
    expect(formatStopDuration(45)).toBe("45 s");
    expect(formatStopDuration(1500)).toBe("25 min");
    expect(formatStopDuration(7200)).toBe("2 h");
    expect(formatStopDuration(null)).toBe("Não disponível");
  });

  it("403 da API vira mensagem clara e sem botão de tentar de novo", async () => {
    stub(session("admin"), () => json({ code: "maintenance_access_denied", message: "x" }, 403));
    renderAt("/manutencao/sugestoes");
    expect(await screen.findByText(/Só a Manutenção e a administração usam esta tela/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Tentar novamente" })).not.toBeInTheDocument();
  });
});
