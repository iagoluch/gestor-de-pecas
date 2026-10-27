import { describe, expect, it } from "vitest";
import { managementSections, sectionVisibleFor } from "../config/navigation";

describe("Melhoria Contínua é exclusiva do setor", () => {
  const section = managementSections.find((item) => item.id === "melhoria")!;

  it("aparece para o nível atribuído melhoria_continua e para o admin", () => {
    expect(sectionVisibleFor(section, "lider", [], "melhoria_continua")).toBe(true);
    expect(sectionVisibleFor(section, "admin", [], "admin")).toBe(true);
  });

  it("some para líderes, gestor e gerente industrial", () => {
    for (const assigned of ["lider", "lider_pintura", "gestor", "gerente_industrial", "manutencao"]) {
      expect(sectionVisibleFor(section, "lider", [], assigned)).toBe(false);
    }
    expect(sectionVisibleFor(section, "gestor", [], "gestor")).toBe(false);
  });
});
