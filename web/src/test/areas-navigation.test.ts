import { describe, expect, it } from "vitest";
import { managementSections, sectionPathFor, sectionVisibleFor, tabVisibleFor } from "../config/navigation";

const areaSections = managementSections.filter((section) => section.id.startsWith("area-"));
const visiveis = (role: string, ids: string[]) =>
  areaSections.filter((section) => sectionVisibleFor(section, role, ids)).map((section) => section.label);

describe("menu por área", () => {
  it("tem uma seção por área, com o nome do setor", () => {
    expect(areaSections.map((section) => section.label)).toEqual(
      ["Dobra e Corte", "Usinagem", "Serra", "Solda", "Pintura", "Protótipo", "Projetos/Ferramentaria"],
    );
  });

  it("líder da Serra enxerga só a seção Serra", () => {
    expect(visiveis("lider", ["serra"])).toEqual(["Serra"]);
  });

  it("supervisor enxerga as seções do seu setor", () => {
    expect(visiveis("supervisor", ["solda", "pintura"])).toEqual(["Solda", "Pintura"]);
  });

  it("quem tem todas as áreas (admin, gerente) não ganha 7 seções: o setor vira filtro em Recursos", () => {
    const todas = areaSections.map((section) => section.tabs[0].area!);
    expect(visiveis("admin", todas)).toEqual([]);
    expect(visiveis("gerente_industrial", todas)).toEqual([]);
    // O guarda de rota e a busca (Ctrl+K) seguem liberando /areas/<setor>.
    expect(areaSections.every((section) => tabVisibleFor(section.tabs[0], "admin", todas))).toBe(true);
  });

  it("quem tem só algumas áreas mantém as seções delas", () => {
    expect(visiveis("supervisor", ["solda", "pintura", "serra", "usinagem", "prototipo", "dobra-corte"])).toHaveLength(6);
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
