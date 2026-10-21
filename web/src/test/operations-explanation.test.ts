import { describe, expect, it } from "vitest";
import {
  buildOccurrencesExplanation,
  buildResourceCountExplanation,
  buildRowSumExplanation,
  buildStoppedOrdersExplanation,
} from "../pages/operations/operationsExplanations";
import type { OrderRow, ResourceRow, SegmentRow } from "../types/management";

const res = (recurso: string, categoria: string, ops = 0): ResourceRow =>
  ({ recurso, recurso_nome: recurso, setor: "serra", categoria, quantidade_ops_ativas: ops, ops_ativas: ops ? [{ op: "OP1" }] : [] }) as unknown as ResourceRow;

describe("explicações locais de Operações/Áreas/Análises", () => {
  const rows = [res("A", "Produção", 2), res("B", "Parada"), res("C", "Parada"), res("D", "Setup")];

  it("conta recursos em produção e fecha com o cartão", () => {
    const e = buildResourceCountExplanation("producing", rows, 1);
    expect(e.children).toHaveLength(1);
    expect(e.reconciliation.ok).toBe(true);
  });

  it("recursos parados: 2 filhos, soma 2", () => {
    const e = buildResourceCountExplanation("stopped", rows, 2);
    expect(e.reconciliation).toMatchObject({ ok: true, sum: 2, diff: 0 });
  });

  it("OPs em execução soma o peso de cada recurso e mostra divergência", () => {
    const e = buildResourceCountExplanation("activeOps", rows, 5);
    expect(e.reconciliation.sum).toBe(2);
    expect(e.reconciliation.ok).toBe(false);
    expect(e.notes.join(" ")).toContain("O cartão mostra 5");
  });

  it("OPs paradas conta só status Parada e avisa quando a lista é parcial", () => {
    const orders = [{ op: "1", status: "Parada" }, { op: "2", status: "Em execução" }] as unknown as OrderRow[];
    const e = buildStoppedOrdersExplanation(orders, 10);
    expect(e.value).toBe(1);
    expect(e.notes.join(" ")).toContain("10 no total");
  });

  it("ocorrências: uma por linha e avisa quando faltam linhas", () => {
    const items = [{ recurso: "A", segundos: 60 }, { recurso: "B", segundos: 30 }] as SegmentRow[];
    expect(buildOccurrencesExplanation("Ocorrências", items, 2).reconciliation.ok).toBe(true);
    const partial = buildOccurrencesExplanation("Ocorrências", items, 5);
    expect(partial.reconciliation).toMatchObject({ ok: false, diff: 3 });
  });

  it("soma por linha: ignora linhas vazias e confere com o cartão", () => {
    const e = buildRowSumExplanation({
      metric: "t", label: "T", unit: "seconds", reason: "r", rule: "r",
      rows: [{ label: "A", value: 3600 }, { label: "B", value: null }, { label: "C", value: 1800 }],
      cardValue: 5400,
    });
    expect(e.children).toHaveLength(2);
    expect(e.reconciliation.ok).toBe(true);
    expect(buildRowSumExplanation({ metric: "t", label: "T", unit: "count", reason: "r", rule: "r", rows: [{ label: "A", value: 1 }], cardValue: 4 }).reconciliation.ok).toBe(false);
  });
});
