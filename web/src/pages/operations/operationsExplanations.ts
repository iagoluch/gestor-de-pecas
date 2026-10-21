import type { OrderRow, ResourceRow, SegmentRow } from "../../types/management";
import type { ValueDetail, ValueExplanation, ValueNode } from "../../types/valueExplanation";
import { displayName, formatDuration, formatResourceName } from "../../utils/format";

/**
 * Explicações dos cartões de contagem de Operações e das Áreas ("Em produção
 * agora", "Parados", "OPs em execução", "OPs paradas"). Funções puras sobre as
 * MESMAS linhas que a tela já carregou: cada recurso/OP contado vira um filho, e
 * a reconciliação compara a soma dos filhos com o número do cartão. Quando o
 * cartão vem de um resumo do servidor e as linhas divergem, a diferença aparece
 * na reconciliação em vez de ser escondida.
 */

export type ResourceCountMetric = "producing" | "stopped" | "activeOps";

const norm = (value?: string | null) => String(value ?? "").trim().toLocaleLowerCase("pt-BR");

export const isProducing = (row: ResourceRow) => ["producao", "produção"].includes(norm(row.categoria));
export const isStopped = (row: ResourceRow) => norm(row.categoria) === "parada";

function localIso(date: Date) {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function resourceDetail(row: ResourceRow): ValueDetail | null {
  const detail: ValueDetail = {};
  if (row.setor) detail.setor = row.setor;
  if (row.motivo) detail.motivo = displayName(row.motivo);
  if (row.duracao_segundos !== null && row.duracao_segundos !== undefined) detail.duracao = formatDuration(row.duracao_segundos);
  const first = row.ops_ativas[0];
  if (first?.op) detail.op = first.op;
  if (first?.operador_inicio) detail.operador = first.operador_inicio;
  return Object.keys(detail).length ? detail : null;
}

const resourceNode = (row: ResourceRow, value: number): ValueNode => ({
  kind: "resource",
  label: formatResourceName(row.recurso_nome ?? row.recurso),
  value,
  children: [],
  detail: resourceDetail(row),
  truncated: false,
});

interface Spec {
  label: string;
  reason: string;
  rule: string;
  pick: (rows: ResourceRow[]) => ResourceRow[];
  weight: (row: ResourceRow) => number;
}

const SPECS: Record<ResourceCountMetric, Spec> = {
  producing: {
    label: "Em produção agora",
    reason: "É quantos recursos estão em estado produtivo neste momento.",
    rule: "Conta cada recurso cujo estado atual é produção. Cada recurso vale 1.",
    pick: (rows) => rows.filter(isProducing),
    weight: () => 1,
  },
  stopped: {
    label: "Recursos parados",
    reason: "É quantos recursos estão parados neste momento. O motivo de cada parada aparece em cada linha.",
    rule: "Conta cada recurso cujo estado atual é parada (planejada ou não). Cada recurso vale 1.",
    pick: (rows) => rows.filter(isStopped),
    weight: () => 1,
  },
  activeOps: {
    label: "OPs em execução",
    reason: "É quantas OPs estão abertas nos recursos agora, somando as OPs ativas de cada recurso.",
    rule: "Soma, por recurso, a quantidade de OPs ativas. Um recurso pode ter mais de uma.",
    pick: (rows) => rows.filter((row) => row.quantidade_ops_ativas > 0),
    weight: (row) => row.quantidade_ops_ativas,
  },
};

/**
 * `cardValue` é o número que o cartão mostra (do resumo do servidor ou da
 * contagem local). `scopeNote` descreve o recorte (ex.: "da área Solda").
 */
export function buildResourceCountExplanation(
  metric: ResourceCountMetric,
  rows: ResourceRow[],
  cardValue: number,
  options: { scopeNote?: string; now?: Date } = {},
): ValueExplanation {
  const spec = SPECS[metric];
  const children = spec.pick(rows).map((row) => resourceNode(row, spec.weight(row)));
  const sum = children.reduce((acc, node) => acc + Number(node.value), 0);
  const diff = cardValue - sum;
  const notes: string[] = [];
  if (options.scopeNote) notes.push(options.scopeNote);
  if (Math.abs(diff) >= 1e-9) notes.push(`O cartão mostra ${cardValue}, mas as linhas carregadas somam ${sum}: o resumo do servidor e a lista foram lidos em momentos diferentes.`);
  return {
    kind: "value",
    metric: `local.recursos.${metric}`,
    label: spec.label,
    unit: "count",
    value: cardValue,
    reason: spec.reason,
    rule: spec.rule,
    children,
    excluded: [],
    reconciliation: { ok: Math.abs(diff) < 1e-9, sum, diff },
    calculated_at: localIso(options.now ?? new Date()),
    truncated: false,
    notes,
  };
}

export const isStoppedOrder = (row: OrderRow) => String(row.status ?? "") === "Parada";

/** "OPs paradas": uma linha por OP com status Parada entre as carregadas. */
export function buildStoppedOrdersExplanation(
  rows: OrderRow[],
  filterTotal: number | null | undefined,
  now: Date = new Date(),
): ValueExplanation {
  const stopped = rows.filter(isStoppedOrder);
  const children: ValueNode[] = stopped.map((row) => {
    const detail: ValueDetail = {};
    if (row.produto) detail.produto = row.produto;
    if (row.recurso_real) detail.recurso = displayName(row.recurso_real);
    if (row.apontamento_id !== null && row.apontamento_id !== undefined) detail.registro = row.apontamento_id;
    return {
      kind: "op",
      label: row.op ? `OP ${row.op}` : "Sem OP",
      value: 1,
      children: [],
      detail: Object.keys(detail).length ? detail : null,
      truncated: false,
    };
  });
  const sum = children.length;
  const notes: string[] = [];
  if (filterTotal !== null && filterTotal !== undefined && Number.isFinite(filterTotal) && rows.length < filterTotal) {
    notes.push(`Contagem das ${rows.length} OPs carregadas; o filtro tem ${filterTotal} no total.`);
  }
  return {
    kind: "value",
    metric: "local.ordens.paradas",
    label: "OPs paradas",
    unit: "count",
    value: sum,
    reason: "É quantas OPs da lista estão com status Parada.",
    rule: "Conta cada OP carregada na tela cujo status é Parada. Cada OP vale 1.",
    children,
    excluded: [],
    reconciliation: { ok: true, sum, diff: 0 },
    calculated_at: localIso(now),
    truncated: false,
    notes,
  };
}

/** "Ocorrências" de Paradas/Setup: uma linha por ocorrência listada; soma contra o total do cartão. */
export function buildOccurrencesExplanation(
  label: string,
  items: SegmentRow[],
  count: number | null | undefined,
  now: Date = new Date(),
): ValueExplanation {
  const total = count ?? items.length;
  const children: ValueNode[] = items.map((row) => {
    const detail: ValueDetail = {};
    if (row.setor) detail.setor = row.setor;
    if (row.motivo) detail.motivo = displayName(row.motivo);
    if (row.segundos !== null && row.segundos !== undefined) detail.duracao = formatDuration(row.segundos);
    if (row.op) detail.op = row.op;
    return {
      kind: "event",
      label: formatResourceName(row.recurso ?? "Sem recurso"),
      value: 1,
      children: [],
      detail: Object.keys(detail).length ? detail : null,
      truncated: false,
    };
  });
  const sum = children.length;
  const diff = total - sum;
  const notes: string[] = [];
  if (Math.abs(diff) >= 1e-9) notes.push(`O cartão conta ${total} ocorrências, mas só ${sum} vieram na lista carregada.`);
  return {
    kind: "value",
    metric: "local.analises.ocorrencias",
    label,
    unit: "count",
    value: total,
    reason: "É quantas ocorrências aparecem na lista abaixo, no período e filtros escolhidos.",
    rule: "Conta cada ocorrência listada. Cada uma vale 1.",
    children,
    excluded: [],
    reconciliation: { ok: Math.abs(diff) < 1e-9, sum, diff },
    calculated_at: localIso(now),
    truncated: false,
    notes,
  };
}

export interface RowSumInput {
  metric: string;
  label: string;
  unit: "count" | "seconds";
  reason: string;
  rule: string;
  rows: Array<{ label: string; value: number | null | undefined; detail?: ValueDetail | null }>;
  cardValue: number;
  notes?: string[];
  now?: Date;
}

/** Soma de uma coluna da tabela da própria tela: cada linha vira um filho e a soma é conferida com o cartão. */
export function buildRowSumExplanation(input: RowSumInput): ValueExplanation {
  const children: ValueNode[] = input.rows
    .filter((row) => row.value !== null && row.value !== undefined && Number(row.value) !== 0)
    .map((row) => ({ kind: "resource", label: row.label, value: Number(row.value), children: [], detail: row.detail ?? null, truncated: false }));
  const sum = children.reduce((acc, node) => acc + Number(node.value), 0);
  const diff = input.cardValue - sum;
  const ok = Math.abs(diff) < 0.5;
  const notes = [...(input.notes ?? [])];
  if (!ok) notes.push("O cartão e a soma das linhas da tabela não fecham: a diferença está na reconciliação.");
  return {
    kind: "value",
    metric: input.metric,
    label: input.label,
    unit: input.unit,
    value: input.cardValue,
    reason: input.reason,
    rule: input.rule,
    children,
    excluded: [],
    reconciliation: { ok, sum, diff },
    calculated_at: localIso(input.now ?? new Date()),
    truncated: false,
    notes,
  };
}
