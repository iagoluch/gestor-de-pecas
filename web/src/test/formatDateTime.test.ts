import { describe, expect, it } from "vitest";
import { formatDateTime } from "../utils/format";

describe("formatDateTime", () => {
  it("data pura (coluna DATE) mostra o próprio dia, sem voltar um dia pelo fuso", () => {
    expect(formatDateTime("2026-11-05")).toBe("05/11/2026");
    expect(formatDateTime("2026-01-01")).toBe("01/01/2026");
  });

  it("data com hora continua com dia e hora", () => {
    expect(formatDateTime("2026-11-05T14:30:00")).toMatch(/^05\/11\/2026.*14:30$/);
  });

  it("vazio e texto inválido", () => {
    expect(formatDateTime(null)).toBe("—");
    expect(formatDateTime("sem data")).toBe("sem data");
  });
});
