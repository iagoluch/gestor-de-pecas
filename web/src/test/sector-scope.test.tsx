import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FilterBar } from "../components/FilterBar";
import { FilterProvider, useManagementFilters } from "../filters/FilterContext";

const scope = vi.hoisted(() => ({ value: null as string[] | null }));
vi.mock("../auth/AuthContext", () => ({ useSectorScope: () => scope.value }));

function Probe() {
  const { query } = useManagementFilters();
  return <output>{query}</output>;
}

function montar() {
  render(<FilterProvider><FilterBar /><Probe /></FilterProvider>);
}

/** Líder/supervisor veem só o próprio setor (27/10/2026). */
describe("filtro de setor com escopo da conta", () => {
  beforeEach(() => { scope.value = null; });

  it("conta de um setor só não tem seletor e já consulta o setor dela", () => {
    scope.value = ["Pintura"];
    montar();
    expect(screen.queryByLabelText("Setor")).not.toBeInTheDocument();
    expect(screen.getByText("Setor: Pintura")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("setor=Pintura");
  });

  it("supervisor de vários setores escolhe só entre os dele, sem Todos", () => {
    scope.value = ["Dobra", "Corte"];
    montar();
    const select = screen.getByLabelText("Setor") as HTMLSelectElement;
    expect([...select.options].map((option) => option.text)).toEqual(["Dobra", "Corte"]);
    expect(select.value).toBe("Dobra");
    expect(screen.getByRole("status")).toHaveTextContent("setor=Dobra");
  });

  it("quem vê a fábrica toda segue com Todos os setores", () => {
    montar();
    const select = screen.getByLabelText("Setor") as HTMLSelectElement;
    expect(select.options[0].text).toBe("Todos os setores");
    expect(select.options.length).toBeGreaterThan(10);
  });
});
