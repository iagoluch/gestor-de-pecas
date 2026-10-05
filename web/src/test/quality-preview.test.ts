// @vitest-environment node
import { describe, expect, it } from "vitest";
import { previewStatus, isInvalidMeasure, rangeLabel } from "../pages/operator/QualityInspectionPage";
import type { QualityDimension } from "../types/api";

function makeCota(overrides: Partial<QualityDimension> = {}): QualityDimension {
  return {
    id: 1,
    sequencia: 1,
    descricao: "Comprimento",
    padrao: "12,0 ± 0,2",
    unidade: "mm",
    referencia: 12,
    margem: 0.2,
    limite_inferior: 11.8,
    limite_superior: 12.2,
    conformidade_automatica: true,
    ...overrides,
  } as QualityDimension;
}

describe("previewStatus", () => {
  it("retorna CONFORME quando a medida está dentro da faixa", () => {
    const cota = makeCota();
    expect(previewStatus(cota, "12,0")).toBe("CONFORME");
    expect(previewStatus(cota, "12.0")).toBe("CONFORME");
  });

  it("retorna CONFORME exatamente nos limites inferior e superior", () => {
    const cota = makeCota();
    expect(previewStatus(cota, "11,8")).toBe("CONFORME");
    expect(previewStatus(cota, "11.8")).toBe("CONFORME");
    expect(previewStatus(cota, "12,2")).toBe("CONFORME");
    expect(previewStatus(cota, "12.2")).toBe("CONFORME");
  });

  it("retorna NAO_CONFORME quando a medida está fora da faixa", () => {
    const cota = makeCota();
    expect(previewStatus(cota, "11,79")).toBe("NAO_CONFORME");
    expect(previewStatus(cota, "11.79")).toBe("NAO_CONFORME");
    expect(previewStatus(cota, "12,21")).toBe("NAO_CONFORME");
    expect(previewStatus(cota, "12.21")).toBe("NAO_CONFORME");
  });

  it("retorna string vazia para texto vazio", () => {
    const cota = makeCota();
    expect(previewStatus(cota, "")).toBe("");
    expect(previewStatus(cota, "   ")).toBe("");
  });

  it("retorna string vazia para texto não numérico", () => {
    const cota = makeCota();
    expect(previewStatus(cota, "abc")).toBe("");
  });

  it("retorna string vazia quando conformidade_automatica é false", () => {
    const cota = makeCota({ conformidade_automatica: false });
    expect(previewStatus(cota, "12,0")).toBe("");
  });

  it("retorna string vazia quando limites são null", () => {
    const cota = makeCota({ limite_inferior: null, limite_superior: null });
    expect(previewStatus(cota, "12,0")).toBe("");
  });
});

describe("isInvalidMeasure", () => {
  it("retorna false para string vazia", () => {
    expect(isInvalidMeasure("")).toBe(false);
  });

  it("retorna false para string com apenas espaços", () => {
    expect(isInvalidMeasure("  ")).toBe(false);
  });

  it("retorna false para número válido com vírgula", () => {
    expect(isInvalidMeasure("12,5")).toBe(false);
  });

  it("retorna false para número válido com ponto", () => {
    expect(isInvalidMeasure("12.5")).toBe(false);
  });

  it("retorna true para texto não numérico", () => {
    expect(isInvalidMeasure("abc")).toBe(true);
  });

  it("retorna true para número com sufixo não numérico", () => {
    expect(isInvalidMeasure("12,5x")).toBe(true);
  });
});

describe("rangeLabel", () => {
  it("retorna string com 'a' e 'mm' quando limites existem", () => {
    const cota = makeCota({ limite_inferior: 11.8, limite_superior: 12.2 });
    const result = rangeLabel(cota);
    expect(result).toContain("a");
    expect(result).toContain("mm");
    // Valor real observado: "11.8 a 12.2 mm" (formatMeasurement usa ponto para número)
    expect(result).toBe("11.8 a 12.2 mm");
  });

  it("retorna string vazia quando limite_inferior é null", () => {
    const cota = makeCota({ limite_inferior: null });
    expect(rangeLabel(cota)).toBe("");
  });

  it("retorna string vazia quando limite_superior é null", () => {
    const cota = makeCota({ limite_superior: null });
    expect(rangeLabel(cota)).toBe("");
  });
});