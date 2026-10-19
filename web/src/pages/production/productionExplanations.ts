import type { ValueDetail, ValueExplanation, ValueNode, ValueUnit } from "../../types/valueExplanation";

/**
 * Explicações dos totais que a tela soma no navegador (Produção > OPs e
 * Planejado × Realizado). São funções puras: usam as MESMAS linhas e a MESMA
 * conta (`rowQuantities`/`sumQuantities`) que geram o número do cartão, então
 * a explicação nunca é um segundo cálculo. Fórmulas como estão hoje; nada é
 * corrigido aqui, só explicado.
 */

export interface QuantityRow {
  apontamento_id?: number | null;
  op?: string | null;
  produto?: string | null;
  operacao?: string | number | null;
  operacao_atual?: string | number | null;
  recurso_planejado?: string | null;
  recurso_real?: string | null;
  quantidade_planejada?: number | null;
  quantidade_boa?: number | null;
  refugo?: number | null;
  retrabalho?: number | null;
  quantidade_atendida?: number | null;
  saldo_quantidade?: number | null;
}

export interface Quantities {
  planned: number;
  good: number;
  scrap: number;
  rework: number;
  attended: number;
  balance: number;
}

/** Limite de linhas que as duas telas pedem ao backend (`page_size=200`). */
export const ROW_LIMIT = 200;

/** Valores de uma linha: atendida = boa + refugo; saldo = max(0, planejada − boa − refugo) quando o backend não manda. */
export function rowQuantities(row: QuantityRow): Quantities {
  const planned = Number(row.quantidade_planejada ?? 0);
  const good = Number(row.quantidade_boa ?? 0);
  const scrap = Number(row.refugo ?? 0);
  const rework = Number(row.retrabalho ?? 0);
  return {
    planned,
    good,
    scrap,
    rework,
    attended: Number(row.quantidade_atendida ?? good + scrap),
    balance: Number(row.saldo_quantidade ?? Math.max(0, planned - good - scrap)),
  };
}

/** Soma das linhas: é o número dos cartões. */
export function sumQuantities(rows: QuantityRow[]): Quantities {
  return rows.reduce<Quantities>((acc, row) => {
    const values = rowQuantities(row);
    return {
      planned: acc.planned + values.planned,
      good: acc.good + values.good,
      scrap: acc.scrap + values.scrap,
      rework: acc.rework + values.rework,
      attended: acc.attended + values.attended,
      balance: acc.balance + values.balance,
    };
  }, { planned: 0, good: 0, scrap: 0, rework: 0, attended: 0, balance: 0 });
}

export type SumMetric = "planned" | "good" | "scrap" | "rework" | "attended" | "balance" | "losses";

interface MetricSpec {
  label: string;
  reason: string;
  rule: string;
  pick: (values: Quantities) => number;
}

const SUM_METRICS: Record<SumMetric, MetricSpec> = {
  planned: {
    label: "Quantidade planejada",
    reason: "É a soma da quantidade planejada de cada OP carregada na tela.",
    rule: "Planejada = soma do campo planejado de cada linha.",
    pick: (values) => values.planned,
  },
  good: {
    label: "Peças boas",
    reason: "É a soma das peças boas apontadas em cada OP carregada na tela.",
    rule: "Boas = soma das peças boas de cada linha. O percentual \"do planejado\" mostrado junto usa só as boas: boas ÷ planejada.",
    pick: (values) => values.good,
  },
  scrap: {
    label: "Refugo",
    reason: "É a soma do refugo apontado em cada OP carregada na tela.",
    rule: "Refugo = soma do refugo de cada linha.",
    pick: (values) => values.scrap,
  },
  rework: {
    label: "Retrabalho",
    reason: "É a soma do retrabalho apontado em cada OP carregada na tela.",
    rule: "Retrabalho = soma do retrabalho de cada linha.",
    pick: (values) => values.rework,
  },
  attended: {
    label: "Atendida",
    reason: "É quanto do plano já foi atendido, somando as OPs carregadas na tela.",
    rule: "Atendida = boas + refugo em cada linha, depois somadas. Retrabalho não conta como atendido.",
    pick: (values) => values.attended,
  },
  balance: {
    label: "Saldo a produzir",
    reason: "É o que ainda falta produzir, somando o saldo de cada OP carregada na tela.",
    rule: "Saldo de cada linha = planejada − boas − refugo, nunca abaixo de zero (retrabalho não reduz o saldo). O cartão soma os saldos das linhas.",
    pick: (values) => values.balance,
  },
  losses: {
    label: "Perdas no período",
    reason: "É o refugo mais o retrabalho de cada OP carregada na tela.",
    rule: "Perdas = refugo + retrabalho em cada linha, depois somadas.",
    pick: (values) => values.scrap + values.rework,
  },
};

export interface ExplanationScope {
  /** Linhas carregadas na tela (as mesmas do cartão). */
  rows: QuantityRow[];
  /** Total de linhas que o filtro tem no servidor (`page.total`). */
  filterTotal: number | null | undefined;
  /** Relógio injetável para teste. */
  now?: Date;
}

function localIso(date: Date) {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function rowLabel(row: QuantityRow) {
  const operation = row.operacao ?? row.operacao_atual;
  const op = row.op ? `OP ${row.op}` : "Sem OP";
  return operation !== null && operation !== undefined && operation !== "" ? `${op} · op. ${operation}` : op;
}

function rowDetail(row: QuantityRow): ValueDetail | null {
  const detail: ValueDetail = {};
  if (row.apontamento_id !== null && row.apontamento_id !== undefined) detail.registro = row.apontamento_id;
  if (row.produto) detail.produto = row.produto;
  const resource = row.recurso_real ?? row.recurso_planejado;
  if (resource) detail.recurso = resource;
  return Object.keys(detail).length ? detail : null;
}

/** Aviso de que a soma cobre só as linhas carregadas (N < M). */
function truncationNotes(loaded: number, filterTotal: number | null | undefined) {
  if (filterTotal === null || filterTotal === undefined || !Number.isFinite(filterTotal) || loaded >= filterTotal) return [];
  return [`Soma das ${loaded} linhas carregadas; o filtro tem ${filterTotal} no total.`];
}

function explanation(args: {
  metric: string;
  label: string;
  unit: ValueUnit;
  value: number;
  reason: string;
  rule: string;
  children: ValueNode[];
  sum: number;
  scope: ExplanationScope;
  notes?: string[];
}): ValueExplanation {
  const diff = args.value - args.sum;
  return {
    kind: "value",
    metric: args.metric,
    label: args.label,
    unit: args.unit,
    value: args.value,
    reason: args.reason,
    rule: args.rule,
    children: args.children,
    excluded: [],
    reconciliation: { ok: Math.abs(diff) < 1e-9, sum: args.sum, diff },
    calculated_at: localIso(args.scope.now ?? new Date()),
    truncated: false,
    notes: [...truncationNotes(args.scope.rows.length, args.scope.filterTotal), ...(args.notes ?? [])],
  };
}

/** Uma linha por OP com o valor da coluna; a soma das linhas é o número do cartão. */
export function buildSumExplanation(metric: SumMetric, scope: ExplanationScope): ValueExplanation {
  const spec = SUM_METRICS[metric];
  const total = spec.pick(sumQuantities(scope.rows));
  const children: ValueNode[] = scope.rows.map((row) => ({
    kind: "op",
    label: rowLabel(row),
    value: spec.pick(rowQuantities(row)),
    children: [],
    detail: rowDetail(row),
    truncated: false,
  }));
  const sum = children.reduce((acc, node) => acc + Number(node.value), 0);
  return explanation({
    metric: `local.${metric}`,
    label: spec.label,
    unit: "pcs",
    value: total,
    reason: spec.reason,
    rule: spec.rule,
    children,
    sum,
    scope,
  });
}

/** % atendida = atendida ÷ planejada, com as duas somas como entradas da fórmula. */
export function buildAttendanceExplanation(scope: ExplanationScope): ValueExplanation {
  const totals = sumQuantities(scope.rows);
  const input = (label: string, value: number): ValueNode => ({ kind: "input", label, value, children: [], detail: null, truncated: false });
  const value = totals.planned ? (totals.attended / totals.planned) * 100 : 0;
  return explanation({
    metric: "local.attendance",
    label: "Atendimento",
    unit: "pct",
    value,
    reason: "É quanto do plano foi atendido: peças atendidas divididas pela quantidade planejada, nas OPs carregadas na tela.",
    rule: "% atendida = atendida ÷ planejada, onde atendida = boas + refugo. Retrabalho não entra.",
    children: [input("Atendida (boas + refugo)", totals.attended), input("Planejada", totals.planned)],
    sum: totals.planned ? (totals.attended / totals.planned) * 100 : 0,
    scope,
  });
}
