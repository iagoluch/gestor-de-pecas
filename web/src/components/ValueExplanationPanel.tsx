import { useState } from "react";
import type { ValueDetail, ValueExplanation, ValueNode, ValueUnit } from "../types/valueExplanation";
import { formatHours, formatNumber, formatPercent } from "../utils/format";
import { clockTime, ExplanationDrawer } from "./ExplanationDrawer";
import "../styles/metric-explanation.css";

const brl = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });

const UNIT_HINT: Partial<Record<ValueUnit, string>> = { pcs: "peças", hours: "horas" };

/** Formata o número na unidade do contrato. `hours` chega em horas e vira "2h 30m". */
export function formatValue(value: number | string | null | undefined, unit: ValueUnit): string {
  if (value === null || value === undefined || value === "") return "Não disponível";
  if (unit === "text" || typeof value === "string") return String(value);
  if (!Number.isFinite(value)) return "Não disponível";
  switch (unit) {
    case "pct": return formatPercent(value);
    case "brl": return brl.format(value);
    case "hours": return formatHours(value * 3600);
    default: return formatNumber(value, 2);
  }
}

/** Entradas de fórmula (numerador/denominador) são quantidades, mesmo quando o resultado é %. */
function nodeValue(node: ValueNode, unit: ValueUnit) {
  return formatValue(node.value, node.kind === "input" && unit === "pct" ? "count" : unit);
}

const DETAIL_LABELS: Record<string, string> = {
  id: "Registro",
  record_id: "Registro",
  op: "OP",
  operador: "Operador",
  operator: "Operador",
  motivo: "Motivo",
  origem: "Origem",
  origin: "Origem",
  data: "Data",
  data_hora: "Data e hora",
  quando: "Quando",
  recurso: "Recurso",
  setor: "Setor",
  produto: "Produto",
  operacao: "Operação",
  fonte: "Fonte",
  formula: "Fórmula",
  rule: "Regra aplicada",
};

function detailLabel(key: string) {
  const known = DETAIL_LABELS[key.toLowerCase()];
  if (known) return known;
  const spaced = key.replace(/_/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function detailEntries(detail: ValueDetail | null) {
  return Object.entries(detail ?? {}).filter(([, value]) => value !== null && value !== undefined && value !== "");
}

function hasTruncated(nodes: ValueNode[]): boolean {
  return nodes.some((node) => node.truncated || hasTruncated(node.children));
}

function numericValue(value: number | string | null) {
  return typeof value === "number" && Number.isFinite(value) ? Math.abs(value) : 0;
}

function ValueRows({ nodes, unit, open, toggle, path }: {
  nodes: ValueNode[];
  unit: ValueUnit;
  open: Set<string>;
  toggle: (key: string) => void;
  path: string;
}) {
  // Barra de cada linha comparada à maior irmã: lê melhor que fatias do total.
  const scale = Math.max(0, ...nodes.map((node) => numericValue(node.value)));
  return (
    <>
      {nodes.map((node, index) => {
        const key = `${path}/${index}`;
        const details = detailEntries(node.detail);
        const expandable = node.children.length > 0 || details.length > 0;
        const expanded = open.has(key);
        const showBar = node.kind !== "input" && unit !== "text" && typeof node.value === "number";
        const share = scale > 0 ? Math.min(100, (numericValue(node.value) / scale) * 100) : 0;
        const value = nodeValue(node, unit);
        return (
          <div key={key} className={`mx-node mx-node--${node.kind}`}>
            {expandable ? (
              <button type="button" className="mx-row" aria-expanded={expanded} onClick={() => toggle(key)}>
                <span className="mx-row__name"><span aria-hidden="true" className="mx-row__chev">{expanded ? "▼" : "▶"}</span>{node.label}</span>
                <span className="mx-row__track" aria-hidden="true">{showBar ? <i style={{ width: `${share}%` }} /> : null}</span>
                <span className="mx-row__value">{value}</span>
              </button>
            ) : (
              <div className="mx-row mx-row--static">
                <span className="mx-row__name">{node.label}</span>
                <span className="mx-row__track" aria-hidden="true">{showBar ? <i style={{ width: `${share}%` }} /> : null}</span>
                <span className="mx-row__value">{value}</span>
              </div>
            )}
            {expanded ? (
              <div className="mx-children">
                {details.length ? (
                  <dl className="mx-record">
                    {details.map(([name, detailValue]) => (
                      <div key={name}><dt>{detailLabel(name)}</dt><dd>{String(detailValue)}</dd></div>
                    ))}
                  </dl>
                ) : null}
                <ValueRows nodes={node.children} unit={unit} open={open} toggle={toggle} path={key} />
                {node.truncated ? <p className="mx-dim">Há mais itens do que os mostrados aqui.</p> : null}
              </div>
            ) : null}
          </div>
        );
      })}
    </>
  );
}

function Reconciliation({ explanation }: { explanation: ValueExplanation }) {
  const { reconciliation, unit, children } = explanation;
  if (!children.length || reconciliation.sum === null) return null;
  const fromInputs = children.every((node) => node.kind === "input");
  const sum = formatValue(reconciliation.sum, unit);
  if (reconciliation.ok) {
    return (
      <p className="mx-check">
        <span aria-hidden="true">✓</span>{" "}
        {fromInputs ? `refazendo a conta com as entradas dá ${sum}, igual ao número clicado.` : `os itens somam ${sum}, igual ao número clicado.`}
      </p>
    );
  }
  const diff = reconciliation.diff === null ? null : formatValue(Math.abs(reconciliation.diff), unit);
  return (
    <p className="mx-check mx-check--bad" role="alert">
      {fromInputs ? `Atenção: refazendo a conta com as entradas dá ${sum}` : `Atenção: os itens somam ${sum}`}
      , mas o número clicado é {formatValue(explanation.value, unit)}{diff ? ` (diferença de ${diff})` : ""}.
    </p>
  );
}

/** Corpo do painel para `kind: "value"`: número, motivo, regra, árvore e conferência. */
export function ValueExplanationBody({ explanation }: { explanation: ValueExplanation }) {
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const toggle = (key: string) => setOpen((current) => {
    const next = new Set(current);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    return next;
  });
  const cut = explanation.truncated || hasTruncated(explanation.children);
  const hint = UNIT_HINT[explanation.unit];
  return (
    <>
      <div className="mx-hero">
        <strong className="mx-hero__value" data-testid="explanation-total">{formatValue(explanation.value, explanation.unit)}</strong>
        {hint && explanation.unit === "pcs" ? <p className="mx-hero__sub">{hint}</p> : null}
      </div>
      {explanation.reason ? <p className="mx-why">{explanation.reason}</p> : null}
      {explanation.rule ? <p className="mx-rule"><b>Regra:</b> {explanation.rule}</p> : null}
      {explanation.children.length ? (
        <div className="mx-rows">
          <ValueRows nodes={explanation.children} unit={explanation.unit} open={open} toggle={toggle} path="v" />
        </div>
      ) : null}
      {/* Numa taxa (pct) o que ficou de fora é quantidade de peças, não percentual. */}
      {explanation.excluded.length || explanation.notes.length ? (
        <ul className="mx-faint">
          {explanation.excluded.map((item) => (
            <li key={`${item.label}-${item.value}`}>({item.label} {formatValue(item.value, explanation.unit === "pct" ? "count" : explanation.unit)}: {item.reason})</li>
          ))}
          {explanation.notes.map((note) => <li key={note}>{note}</li>)}
        </ul>
      ) : null}
      {cut ? <p className="mx-warning">A lista foi cortada por tamanho: o total está certo, mas nem todos os itens aparecem.</p> : null}
      <Reconciliation explanation={explanation} />
      <p className="mx-stamp">calculado às {clockTime(explanation.calculated_at)}</p>
    </>
  );
}

/**
 * Painel para somas feitas no navegador: recebe a explicação já montada com as
 * mesmas linhas da soma (sem backend e sem chat de IA, porque não há métrica
 * no servidor para a IA consultar).
 */
export function LocalExplanationPanel({ explanation, onClose }: { explanation: ValueExplanation; onClose: () => void }) {
  return (
    <ExplanationDrawer title={explanation.label} onClose={onClose} testId="local-explanation-panel">
      <ValueExplanationBody explanation={explanation} />
    </ExplanationDrawer>
  );
}
