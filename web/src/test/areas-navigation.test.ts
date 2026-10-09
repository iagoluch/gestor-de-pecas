import { describe, expect, it } from "vitest";
import { managementSections, sectionPathFor, sectionVisibleFor } from "../config/navigation";

const areaSections = managementSections.filter((section) => section.id.startsWith("area-"));
const visiveis = (role: string, ids: string[]) =>
  areaSections.filter((section) => sectionVisibleFor(section, role, ids)).map((section) => section.label);

describe("menu por área", () => {
  it("tem uma seção por área, com o nome do setor", () => {
    expect(areaSections.map((section) => section.label)).toEqual(
      ["Dobra e Corte", "Usinagem", "Serra", "Solda", "Pintura", "Protótipo"],
    );
  });

  it("líder da Serra enxerga só a seção Serra", () => {
    expect(visiveis("lider", ["serra"])).toEqual(["Serra"]);
  });

  it("supervisor enxerga as seções do seu setor", () => {
    expect(visiveis("supervisor", ["solda", "pintura"])).toEqual(["Solda", "Pintura"]);
  });

  it("admin com todas as áreas enxerga as seis", () => {
    expect(visiveis("admin", areaSections.map((section) => section.tabs[0].area!))).toHaveLength(6);
  });

  it("conta sem áreas não vê nenhuma", () => {
    expect(visiveis("gestor", [])).toEqual([]);
    expect(areaSections.some((section) => sectionVisibleFor(section, "gestor", undefined))).toBe(false);
  });

  it("seções comuns não dependem das áreas", () => {
    const operations = managementSections.find((section) => section.id === "operations")!;
    expect(sectionVisibleFor(operations, "gestor", [])).toBe(true);
    expect(sectionPathFor(operations, "gestor", [])).toBe(operations.defaultPath);
  });

  it("o clique abre a rota da própria área", () => {
    const serra = areaSections.find((section) => section.label === "Serra")!;
    expect(sectionPathFor(serra, "lider", ["serra"])).toBe("/areas/serra");
  });
});
