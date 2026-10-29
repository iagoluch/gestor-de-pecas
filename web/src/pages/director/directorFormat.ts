import { formatNumber } from "../../utils/format";
import { humanizeSystemState } from "../../utils/systemState";
import type { DirectorCards } from "../../types/director";

/** Texto para custo zerado que só é zero porque falta valor da hora cadastrado. */
export const NO_COST = "Sem custo cadastrado";

/** Horas já vêm em horas da API: "3 h", "12,5 h". */
export function formatHoursValue(hours: number) {
  return `${formatNumber(hours, 1)} h`;
}

/** "R$ 2.250"; centavos só abaixo de mil e quando existem ("R$ 12,50"). */
export function formatMoney(value: number) {
  const cents = value < 1000 && !Number.isInteger(value) ? 2 : 0;
  return `R$ ${value.toLocaleString("pt-BR", { minimumFractionDigits: cents, maximumFractionDigits: cents })}`;
}

/**
 * Valor em R$ honesto: sem nenhum custo cadastrado, zero não é "R$ 0" (a
 * conta não foi feita). Valor parcial é marcado por quem mostra (detalhe ou aviso).
 */
export function costText(value: number, complete: boolean) {
  return !complete && value <= 0 ? NO_COST : formatMoney(value);
}

/** Mesmo que `costText`, com a marca "(parcial)" para uso em linha. */
export function costLine(value: number, complete: boolean) {
  const text = costText(value, complete);
  return !complete && value > 0 ? `${text} (parcial)` : text;
}

export function efficiencyText(metric: DirectorCards["eficiencia_oee"]) {
  if (typeof metric === "number") return `${formatNumber(metric, 1)}%`;
  if (metric && metric.value !== null && metric.value !== undefined) return `${formatNumber(metric.value, 1)}${metric.unit ?? "%"}`;
  return humanizeSystemState(metric?.availability ?? "dados_insuficientes", { fallback: "Sem dados no período" });
}

/** Percentual da eficiência quando existe; `null` em "dados insuficientes". */
export function efficiencyValue(metric: DirectorCards["eficiencia_oee"]) {
  if (typeof metric === "number") return metric;
  return metric?.value ?? null;
}

/** O ritmo real pode passar do padrão cadastrado: o número não é cortado em 100%, mas avisamos. */
export const EFFICIENCY_ABOVE_100_NOTICE =
  "Eficiência acima de 100%: as peças saíram mais rápido que o tempo padrão cadastrado. O número é real (não foi limitado); vale revisar o tempo padrão do produto.";

/** Valor da hora no campo: 80 -> "80,00". */
export function formatRate(value: number | null) {
  return value === null ? "" : value.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// pt-BR com milhar ("1.250,50") ou número simples com vírgula/ponto decimal ("12,5", "12.50").
const RATE_WITH_THOUSANDS = /^\d{1,3}(\.\d{3})*(,\d{1,2})?$/;
const RATE_PLAIN = /^\d+([.,]\d{1,2})?$/;

/**
 * Lê o que a pessoa digitou ("12,50", "1.250,75", "12.5") como número.
 * Qualquer outro formato ("12 50", "1.2.5,00", "-5") é inválido: nada de
 * adivinhar o que a pessoa quis dizer com um valor em R$.
 */
export function parseRate(text: string): number | null {
  const value = text.trim();
  if (RATE_WITH_THOUSANDS.test(value)) return Number(value.replace(/\./g, "").replace(",", "."));
  if (RATE_PLAIN.test(value)) return Number(value.replace(",", "."));
  return null;
}
