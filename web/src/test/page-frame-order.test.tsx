import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { PageFrame } from "../components/PageFrame";
import { FilterProvider } from "../filters/FilterContext";

afterEach(cleanup);

function frame(children: React.ReactNode, filters = true) {
  return render(
    <MemoryRouter initialEntries={["/producao/realizada"]}>
      <FilterProvider>
        <PageFrame sectionId="production" title="T" subtitle="S" filters={filters}>{children}</PageFrame>
      </FilterProvider>
    </MemoryRouter>,
  );
}

const follows = (a: Element, b: Element) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

describe("PageFrame: cards em cima, filtros embaixo", () => {
  it("a grade de cards que abre o conteúdo sobe para cima da barra de filtros", () => {
    frame([<div key="c" className="metric-grid" data-testid="cards" />, <table key="t" data-testid="tabela" />]);
    const cards = screen.getByTestId("cards");
    const filtros = screen.getByRole("button", { name: "Aplicar" });
    expect(follows(cards, filtros)).toBe(true);
    expect(follows(filtros, screen.getByTestId("tabela"))).toBe(true);
  });

  it("conteúdo que não começa por cards fica abaixo dos filtros", () => {
    frame(<table data-testid="tabela" />);
    expect(follows(screen.getByRole("button", { name: "Aplicar" }), screen.getByTestId("tabela"))).toBe(true);
  });
});
