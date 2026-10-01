import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BarList } from "../components/BarList";
import { StatusBadge } from "../components/StatusBadge";
import { displayName, displayText, humanize } from "../utils/format";

describe("nomes técnicos nunca aparecem crus", () => {
  it("traduz níveis de acesso, inclusive os de Solda por estação", () => {
    expect(humanize("admin")).toBe("Administrador");
    expect(humanize("operador_destaque")).toBe("Operador de Destaque");
    expect(humanize("operador_solda_estacao_3")).toBe("Operador Solda — Estação 3");
    expect(humanize("estacao2aco")).toBe("Operador Solda Aço — Estação 2");
    expect(humanize("estacao1alu")).toBe("Operador Solda Alumínio 1");
    expect(humanize("robo1")).toBe("Operador Solda Robô 1");
  });

  it("converte snake_case, caixa alta e enums em inglês", () => {
    expect(humanize("em_andamento")).toBe("Em Andamento");
    expect(humanize("CORTE_LASER")).toBe("Corte Laser");
    expect(humanize("manutencao_preventiva")).toBe("Manutenção Preventiva");
    expect(humanize("CONFORME")).toBe("Conforme");
    expect(humanize("critical")).toBe("Crítico");
    expect(humanize("warning")).toBe("Atenção");
    expect(humanize("OEE")).toBe("OEE");
  });

  it("displayName preserva nome cadastrado e trata só o identificador técnico", () => {
    expect(displayName("Solda Aço")).toBe("Solda Aço");
    expect(displayName("Plasma TerraBlade 4")).toBe("Plasma TerraBlade 4");
    expect(displayName("PCMIXQ01001")).toBe("PCMIXQ01001");
    expect(displayName("falta_de_material")).toBe("Falta De Material");
    expect(displayName(null)).toBe("Não disponível");
    expect(displayName("", "—")).toBe("—");
  });

  it("displayText troca identificadores embutidos em texto livre", () => {
    expect(displayText("Origem: eventos_estado_recurso")).toBe("Origem: Estado físico do recurso");
    expect(displayText(null, "—")).toBe("—");
  });

  it("StatusBadge e BarList exibem texto tratado", () => {
    const { container } = render(<><StatusBadge value="critical" /><BarList data={[{ label: "parada_por_falta_de_material", value: 2 }]} /></>);
    expect(screen.getByText("Crítico")).toBeInTheDocument();
    expect(screen.getByText("Parada Por Falta De Material")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/_|critical/);
  });
});
