import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { AuthProvider } from "../auth/AuthContext";
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

afterEach(() => vi.restoreAllMocks());

describe("Manutenção — utilitários", () => {
  it("duração humana", () => {
    expect(formatStopDuration(45)).toBe("45 s");
    expect(formatStopDuration(1500)).toBe("25 min");
    expect(formatStopDuration(7200)).toBe("2 h");
    expect(formatStopDuration(null)).toBe("Não disponível");
  });
});

describe("Manutenção — tela do perfil de Manutenção (visual de terminal)", () => {
  const mantenedor = { ...session("lider", "manutencao"), management_access: false, andon_access: false, maintenance_access: true };

  it("abre em /manutencao no visual do terminal, sem apontamento nem botão de chamada", async () => {
    stub(mantenedor, () => json(lista([item(3)])));
    renderAt("/manutencao");
    expect(await screen.findByText("Recurso 3")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Manutenção · Sugestões" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Aceitar" })).toBeInTheDocument();
    expect(screen.queryByText(/Posto do operador/)).not.toBeInTheDocument();
  });

  it("URL de gestão volta para a tela de manutenção", async () => {
    stub(mantenedor, () => json(lista([item(4)])));
    renderAt("/inicio/visao-geral");
    expect(await screen.findByText("Recurso 4")).toBeInTheDocument();
  });
});
