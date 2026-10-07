import { describe, expect, it } from "vitest";
import type { AndonResource, AndonSnapshot } from "../types/andon";
import { ALUMINIUM_SMALL_BLOCK, MAP_AREAS, buildFactoryMap, mapState, tileLayout } from "./factoryMap";

function resource(sector: string, group: string, code: string, name = code, category: AndonResource["state"]["category"] = "producao", stop?: "planejada" | "nao_planejada"): AndonResource {
  return {
    code, name, sector, group, active_operations: 0,
    state: { category, label: category, stop_classification: stop ?? null },
    metrics: {} as AndonResource["metrics"],
  };
}
const sector = (name: string, resources: AndonResource[]): AndonSnapshot["sectors"][number] => ({ name, resources });

describe("buildFactoryMap", () => {
  it("coloca cada recurso na sua área e separa jato e secagem da pintura", () => {
    const model = buildFactoryMap([
      sector("Corte", [resource("Corte", "Laser", "LASER1"), resource("Corte", "Plasma", "PLASMA")]),
      sector("Caldeiraria", [resource("Caldeiraria", "Dobra", "DOBRA1"), resource("Caldeiraria", "Serra", "SERRA1")]),
      sector("Pintura", [
        resource("Pintura", "Pintura", "JATO", "JATEAMENTO"),
        resource("Pintura", "Pintura", "ESTUFA", "SECAGEM PINTURA"),
        resource("Pintura", "Pintura", "PINT.L", "PINTURA F IV"),
      ]),
    ]);
    expect(model.tiles.laser.map((t) => t.label)).toEqual(["LASER1"]);
    expect(model.tiles.dobra).toHaveLength(1);
    expect(model.tiles.serras).toHaveLength(1);
    expect(model.tiles.jateamento).toHaveLength(1);
    expect(model.tiles["cab-secagem"].map((t) => t.label)).toEqual(["ESTUFA"]);
    expect(model.tiles.pintura.map((t) => t.label)).toEqual(["PINT.L"]);
    expect(model.unplaced).toBe(0);
  });

  it("Solda de Alumínio: 1 estação no bloco menor e as demais no grande", () => {
    const stations = Array.from({ length: ALUMINIUM_SMALL_BLOCK + 5 }, (_, i) => resource("Solda", "Alumínio", `AL${i + 1}`, `Alumínio ${i + 1}`));
    const model = buildFactoryMap([sector("Solda", stations)]);
    expect(model.tiles["solda-aluminio-a"].map((t) => t.label)).toEqual(["1"]);
    expect(model.tiles["solda-aluminio-b"].map((t) => t.label)).toEqual(["2", "3", "4", "5", "6"]);
  });

  it("Solda de Aço: estações em ordem numérica, 10 depois de 2", () => {
    const names = ["Estação 10", "Estação 2", "Estação 1", "Estação 3"];
    const model = buildFactoryMap([sector("Solda", names.map((n) => resource("Solda", "Aço", n, n)))]);
    expect(model.tiles["solda-aco"].map((t) => t.label)).toEqual(["1", "2", "3", "10"]);
  });

  it("Robô da Solda vai para o bloco ROBÔ", () => {
    const model = buildFactoryMap([sector("Solda", [resource("Solda", "Robô", "ROBO1", "Robô 1")])]);
    expect(model.tiles.robo).toHaveLength(1);
    expect(model.tiles["robo-solda"]).toBeUndefined();
  });

  it("conta recurso sem área em vez de sumir com ele", () => {
    const model = buildFactoryMap([sector("Corte", [resource("Corte", "Novo", "X1")])]);
    expect(model.unplaced).toBe(1);
    expect(model.total).toBe(1);
  });

  it("toda área usada pelo mapeamento existe na planta", () => {
    const ids = new Set(MAP_AREAS.map((area) => area.id));
    const model = buildFactoryMap([
      sector("Solda", [resource("Solda", "Aço", "E1", "Estação 1"), resource("Solda", "Robô", "R1"), resource("Solda", "Ferramentaria", "F1"), resource("Solda", "Protótipo", "P1")]),
    ]);
    Object.keys(model.tiles).forEach((id) => expect(ids.has(id)).toBe(true));
    expect(model.unplaced).toBe(0);
  });
});

describe("mapState / tileLayout", () => {
  it("parada planejada tem estado próprio", () => {
    expect(mapState(resource("Corte", "Laser", "L", "L", "parada", "planejada"))).toBe("parada_planejada");
    expect(mapState(resource("Corte", "Laser", "L", "L", "parada", "nao_planejada"))).toBe("parada");
  });
  it("recurso ocioso (fila, fora de turno, sem estado) usa a cor de sem demanda", () => {
    (["fila", "fora_turno", "desconhecido", "sem_demanda"] as const).forEach((category) => {
      expect(mapState(resource("Corte", "Laser", "L", "L", category))).toBe("sem_demanda");
    });
  });
  it("pastilhas: uma linha quando cabem, duas quando ficariam estreitas, nunca fora da área", () => {
    const solda = MAP_AREAS.find((a) => a.id === "solda-aco")!;
    const usinagem = MAP_AREAS.find((a) => a.id === "usinagem")!;
    expect(tileLayout(solda, ["1"])[0].width).toBe(78);
    const two = tileLayout(usinagem, ["CNC-01", "CNC-02", "CNC-03", "CNC-04", "CNC-05"]);
    expect(new Set(two.map((box) => box.y)).size).toBe(2);
    two.forEach((box) => {
      expect(box.x + box.width).toBeLessThanOrEqual(usinagem.x + usinagem.w);
      expect(box.y + box.height).toBeLessThanOrEqual(usinagem.y + usinagem.h);
    });
    expect(tileLayout(solda, ["DESTAQUE"])[0].textLength).toBeDefined();
  });
});
