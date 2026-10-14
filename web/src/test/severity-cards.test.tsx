import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FilterProvider } from "../filters/FilterContext";
import { AuditIssuesPage } from "../pages/audit/AuditPages";
import { HomeAlertsPage } from "../pages/home/HomePages";
import { formatPieces } from "../utils/format";

afterEach(() => vi.unstubAllGlobals());

// O backend conta por IssueSeverity (mes/domain/industrial.py): chaves em português.
const BY_SEVERITY = { info: 1, aviso: 3, erro: 8, critico: 2 };

function stubFetch(byUrl: Record<string, unknown>) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const key = Object.keys(byUrl).find((prefix) => url.includes(prefix));
    return new Response(JSON.stringify(key ? byUrl[key] : {}), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }));
}

function cardValue(label: string) {
  return screen.getByText(label).closest(".metric-card")?.querySelector(".metric-card__value")?.textContent;
}

describe("cartões de severidade leem as chaves do backend", () => {
  it("Tela inicial — Alertas", async () => {
    stubFetch({
      "/api/v1/management/internal-alerts": { items: [], count: 0, pending: 0 },
      "/api/v1/management/alerts": { items: [], count: 14, by_severity: BY_SEVERITY },
    });
    render(<MemoryRouter><FilterProvider><HomeAlertsPage /></FilterProvider></MemoryRouter>);
    await screen.findByText("Críticos");
    expect(cardValue("Críticos")).toBe("2");
    expect(cardValue("Erros")).toBe("8");
    expect(cardValue("Atenções")).toBe("3");
  });

  it("Auditoria — Inconsistências", async () => {
    stubFetch({ "/api/v1/audit": { issues: [], count: 14, by_severity: BY_SEVERITY } });
    render(<MemoryRouter><FilterProvider><AuditIssuesPage /></FilterProvider></MemoryRouter>);
    await screen.findByText("Críticas");
    expect(cardValue("Críticas")).toBe("2");
    expect(cardValue("Erros")).toBe("8");
    expect(cardValue("Atenções")).toBe("3");
  });
});

describe("formatPieces", () => {
  it("sem valor não ganha o sufixo de peças", () => {
    expect(formatPieces(null)).toBe("Não disponível");
    expect(formatPieces(undefined)).toBe("Não disponível");
  });
  it("com valor mostra a quantidade em peças", () => {
    expect(formatPieces(0)).toBe("0 peça(s)");
    expect(formatPieces(1200)).toBe("1.200 peça(s)");
  });
});
