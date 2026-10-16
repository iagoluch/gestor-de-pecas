import { useId, useRef, useState } from "react";
import { ApiError } from "../api/client";
import { useDialogFocus } from "../hooks/useDialogFocus";
import { useMetricExplanation } from "../hooks/useMetricExplanation";
import type { ExplanationNode, ExplanationTree, OverviewFilters } from "../types/explanation";
import { formatHours } from "../utils/format";
import { LoadingState } from "./DataState";
import { MetricExplanationChat } from "./MetricExplanationChat";
import "../styles/metric-explanation.css";

const SIBLING_COLORS = ["var(--warning)", "var(--teal)", "var(--purple)", "var(--orange)", "var(--accent)"];

function errorMessage(error: ApiError) {
  if (error.status === 403 || error.code === "management_access_denied") return "Você não tem acesso a esta explicação.";
  return "Não foi possível carregar a explicação agora.";
}

/** Hora do cálculo (HH:MM). O backend manda horário local sem fuso; com fuso, converte. */
function clockTime(iso: string) {
  const naive = /T(\d{2}):(\d{2})/.exec(iso);
  if (naive && !/(Z|[+-]\d{2}:?\d{2})$/i.test(iso)) return `${naive[1]}:${naive[2]}`;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return naive ? `${naive[1]}:${naive[2]}` : iso;
  return date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

function plural(count: number, one: string, many: string) {
  return `${count} ${count === 1 ? one : many}`;
}

function hasTruncated(nodes: ExplanationNode[]): boolean {
  return nodes.some((node) => node.truncated || hasTruncated(node.children));
}

function averageLine(tree: ExplanationTree) {
  if (tree.average_seconds === null || tree.resource_count <= 0 || !Number.isFinite(tree.average_seconds)) {
    // Sem divisor (ou métrica de calendário): a explicação dos motivos vem do backend.
    return tree.resource_count > 0 ? tree.rule : null;
  }
  const scope = [plural(tree.resource_count, "recurso", "recursos")];
  if (tree.day_count > 1) scope.push(plural(tree.day_count, "dia", "dias"));
  return `média ${formatHours(tree.average_seconds)} por recurso (${scope.join(", ")})`;
}

function SiblingBar({ tree }: { tree: ExplanationTree }) {
  const parts = tree.siblings.filter((item) => item.seconds > 0);
  if (!parts.length || tree.parent_total_seconds <= 0) return null;
  const base = Math.max(tree.parent_total_seconds, parts.reduce((sum, item) => sum + item.seconds, 0));
  let other = 0;
  const colored = parts.map((item) => ({
    ...item,
    color: item.metric === tree.metric ? "var(--primary)" : SIBLING_COLORS[other++ % SIBLING_COLORS.length],
  }));
  return (
    <>
      <div className="mx-stack" aria-hidden="true">
        {colored.map((item) => (
          <i key={item.metric} style={{ width: `${(item.seconds / base) * 100}%`, background: item.color }} />
        ))}
      </div>
      <div className="mx-legend">
        {colored.map((item) => (
          <span key={item.metric}><b style={{ background: item.color }} />{item.label} {formatHours(item.seconds)}</span>
        ))}
        <span className="mx-dim">· total do turno {formatHours(tree.parent_total_seconds)}</span>
      </div>
    </>
  );
}

function StretchRecord({ node }: { node: ExplanationNode }) {
  const detail = node.detail;
  if (!detail) return null;
  return (
    <dl className="mx-record">
      {detail.record_id ? <div><dt>Registro</dt><dd>{detail.record_id}</dd></div> : null}
      {detail.origin ? <div><dt>Origem</dt><dd>{detail.origin}</dd></div> : null}
      {detail.rule ? <div><dt>Regra aplicada</dt><dd>{detail.rule}</dd></div> : null}
    </dl>
  );
}

function NodeRows({ nodes, depth, total, open, toggle, path }: {
  nodes: ExplanationNode[];
  depth: number;
  total: number;
  open: Set<string>;
  toggle: (key: string) => void;
  path: string;
}) {
  // Setor: fatia do total. Recurso: comparado ao maior irmão, para a barra ler melhor.
  const scale = depth === 0 ? total : Math.max(0, ...nodes.map((node) => node.seconds));
  return (
    <>
      {nodes.map((node, index) => {
        const key = `${path}/${index}`;
        const expandable = node.children.length > 0 || node.kind === "stretch";
        const expanded = open.has(key);
        const share = scale > 0 ? Math.min(100, (node.seconds / scale) * 100) : 0;
        if (node.kind === "stretch") {
          const detail = node.detail;
          const summary = [detail?.who, detail?.motivo].filter(Boolean).join(" · ");
          return (
            <div key={key} className="mx-stretch-block">
              <button type="button" className="mx-stretch" aria-expanded={expanded} onClick={() => toggle(key)}>
                <span className="mx-stretch__when">{node.label}</span>
                <span className="mx-stretch__time">{formatHours(node.seconds)}</span>
                {summary ? <span className="mx-stretch__who">{summary}</span> : null}
              </button>
              {expanded ? <StretchRecord node={node} /> : null}
            </div>
          );
        }
        return (
          <div key={key} className={`mx-node mx-node--${node.kind}`}>
            {expandable ? (
              <button type="button" className="mx-row" aria-expanded={expanded} onClick={() => toggle(key)}>
                <span className="mx-row__name"><span aria-hidden="true" className="mx-row__chev">{expanded ? "▼" : "▶"}</span>{node.label}</span>
                <span className="mx-row__track" aria-hidden="true"><i style={{ width: `${share}%` }} /></span>
                <span className="mx-row__value">{formatHours(node.seconds)}</span>
              </button>
            ) : (
              <div className="mx-row mx-row--static">
                <span className="mx-row__name">{node.label}</span>
                <span className="mx-row__track" aria-hidden="true"><i style={{ width: `${share}%` }} /></span>
                <span className="mx-row__value">{formatHours(node.seconds)}</span>
              </div>
            )}
            {expanded ? (
              <div className="mx-children">
                <NodeRows nodes={node.children} depth={depth + 1} total={total} open={open} toggle={toggle} path={key} />
                {node.truncated ? <p className="mx-dim">Há mais itens do que os mostrados aqui.</p> : null}
              </div>
            ) : null}
          </div>
        );
      })}
    </>
  );
}

function Explanation({ tree }: { tree: ExplanationTree }) {
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const toggle = (key: string) => setOpen((current) => {
    const next = new Set(current);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    return next;
  });
  const average = averageLine(tree);
  const reconciliation = tree.reconciliation;
  const cut = tree.truncated || hasTruncated(tree.children);
  return (
    <>
      <div className="mx-hero">
        <strong className="mx-hero__value" data-testid="explanation-total">{formatHours(tree.total_seconds)}</strong>
        {average ? <p className="mx-hero__sub">{average}</p> : null}
        <SiblingBar tree={tree} />
      </div>
      <p className="mx-why">{tree.reason}</p>
      {tree.children.length ? (
        <div className="mx-rows">
          <NodeRows nodes={tree.children} depth={0} total={tree.total_seconds} open={open} toggle={toggle} path="n" />
        </div>
      ) : null}
      {tree.excluded.length || tree.notes.length ? (
        <ul className="mx-faint">
          {tree.excluded.map((item) => (
            <li key={`${item.label}-${item.seconds}`}>({item.label} {formatHours(item.seconds)}: {item.reason})</li>
          ))}
          {tree.notes.map((note) => <li key={note}>{note}</li>)}
        </ul>
      ) : null}
      {cut ? <p className="mx-warning">A lista foi cortada por tamanho: o total está certo, mas nem todos os itens aparecem.</p> : null}
      {tree.children.length || tree.total_seconds > 0 ? (
        reconciliation.ok ? (
          <p className="mx-check"><span aria-hidden="true">✓</span> os setores somam {formatHours(reconciliation.sum_seconds)}, igual ao número clicado.</p>
        ) : (
          <p className="mx-check mx-check--bad" role="alert">
            Atenção: os setores somam {formatHours(reconciliation.sum_seconds)}, mas o número clicado é {formatHours(tree.total_seconds)} (diferença de {formatHours(Math.abs(reconciliation.diff_seconds))}).
          </p>
        )
      ) : null}
      <p className="mx-stamp">calculado às {clockTime(tree.calculated_at)}</p>
    </>
  );
}

/**
 * Painel lateral "de onde vem este número": desliza por cima da tela (sem rota
 * nem aba nova) e abre setor, recurso e trecho por dentro. Só mostra o que o
 * backend calculou; nada é recalculado aqui.
 */
export function MetricExplanationPanel({ metric, filters, onClose }: {
  metric: string;
  filters: OverviewFilters;
  onClose: () => void;
}) {
  const panelRef = useRef<HTMLElement>(null);
  const titleId = useId();
  useDialogFocus(panelRef, true, onClose);
  const query = useMetricExplanation(metric, filters);
  const tree = query.data;
  return (
    <div
      className="insight-drawer-backdrop"
      role="presentation"
      data-testid="metric-explanation-panel"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <aside ref={panelRef} className="insight-drawer metric-explanation" role="dialog" aria-modal="true" aria-labelledby={titleId}>
        <header>
          <div>
            <small>De onde vem este número</small>
            <h2 id={titleId}>{tree?.label ?? "Explicação"}</h2>
          </div>
          <button type="button" onClick={onClose} aria-label="Fechar explicação">×</button>
        </header>
        <div className="insight-drawer__body metric-explanation__body">
          {query.loading ? <LoadingState label="Carregando explicação…" /> : null}
          {!query.loading && query.error && !tree ? (
            <div className="state-box state-box--error" role="alert">
              <strong>{errorMessage(query.error)}</strong>
              {query.error.status === 403 ? null : <button type="button" onClick={query.reload}>Tentar novamente</button>}
            </div>
          ) : null}
          {tree ? <Explanation tree={tree} /> : null}
        </div>
        <div className="metric-explanation__chat" data-testid="explanation-chat-slot">
          {tree ? <MetricExplanationChat key={`${metric}|${JSON.stringify(filters)}`} metric={metric} label={tree.label} filters={filters} /> : null}
        </div>
      </aside>
    </div>
  );
}
