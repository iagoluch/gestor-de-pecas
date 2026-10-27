import { useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError } from "../../api/client";
import { DataTable } from "../../components/DataTable";
import type { TableColumn } from "../../components/DataTable";
import { LoadingState } from "../../components/DataState";
import { Notice } from "../../components/Notice";
import { PageFrame } from "../../components/PageFrame";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import { useApiQuery } from "../../hooks/useApiQuery";
import type {
  RncDecision,
  RncDecisionResponse,
  RncHistoryResponse,
  RncListItem,
  RncListResponse,
} from "../../types/qualityRnc";
import { formatDateTime, formatNumber } from "../../utils/format";

const API = "/api/v1/quality/rnc";
const TITLE = "Qualidade — Decisão de RNC";
const SUBTITLE = "Registre o que fazer com a peça de uma RNC. A decisão fica no histórico e não bloqueia nada: é só registro interno.";
const LIMIT = 100;
const JUSTIFICATION_MIN = 3;
const JUSTIFICATION_MAX = 500;

const ACCESS_DENIED = "Seu perfil não tem acesso às decisões de RNC. Só a Qualidade e a administração usam esta tela.";

export const DECISIONS: { value: RncDecision; label: string }[] = [
  { value: "usar_como_esta", label: "Usar como está" },
  { value: "retrabalhar", label: "Retrabalhar" },
  { value: "sucatear", label: "Sucatear" },
  { value: "quarentena", label: "Quarentena" },
];

export function decisionLabel(value: string) {
  return DECISIONS.find((item) => item.value === value)?.label ?? value;
}

/** Mensagem humana da falha ao decidir; nunca o código técnico. */
export function rncErrorMessage(reason: unknown) {
  if (!(reason instanceof ApiError)) return "Não foi possível acessar o servidor. Tente novamente.";
  if (reason.status === 403) return ACCESS_DENIED;
  if (reason.status === 404) return "Esta RNC não existe mais. A lista foi atualizada.";
  if (reason.status === 422) return `Escolha a decisão e escreva a justificativa (de ${JUSTIFICATION_MIN} a ${JUSTIFICATION_MAX} caracteres).`;
  return "Não foi possível registrar a decisão. Tente novamente.";
}

function History({ rncId }: { rncId: number }) {
  const query = useApiQuery<RncHistoryResponse>(`${API}/${rncId}/decisions`, { ignoreLiveTick: true });
  if (query.loading && !query.data) return <LoadingState />;
  if (query.error && !query.data) return <Notice tone="error">Não foi possível carregar o histórico desta RNC.</Notice>;
  const items = query.data?.items ?? [];
  if (!items.length) return <p className="section-count">Ainda sem decisão registrada.</p>;
  return (
    <ul className="change-audit__lines" aria-label="Histórico de decisões">
      {items.map((item) => (
        <li key={item.id}>
          <strong>{decisionLabel(item.decisao)}</strong>
          {item.vigente ? " (vigente)" : ""} · {item.decidido_por_nome ?? "Não informado"} · {formatDateTime(item.quando)} — {item.justificativa}
        </li>
      ))}
    </ul>
  );
}

export function QualityRncDecisionPage() {
  const [onlyPending, setOnlyPending] = useState(true);
  const [selected, setSelected] = useState<RncListItem | null>(null);
  const [decision, setDecision] = useState<RncDecision | "">("");
  const [justification, setJustification] = useState("");
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ tone: "success" | "error" | "info"; text: string } | null>(null);
  const [historyKey, setHistoryKey] = useState(0);
  const query = useApiQuery<RncListResponse>(`${API}?limite=${LIMIT}&somente_sem_decisao=${onlyPending}`, { ignoreLiveTick: true });
  const data = query.data;

  function choose(item: RncListItem) {
    setSelected(item);
    setDecision("");
    setJustification("");
    setFeedback(null);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!selected || !decision || busy) return;
    setBusy(true);
    setFeedback(null);
    try {
      const response = await api.post<RncDecisionResponse>(`${API}/${selected.id}/decisions`, {
        decisao: decision,
        justificativa: justification.trim(),
      });
      setFeedback(
        response.aviso
          ? { tone: "info", text: `Decisão registrada. Atenção: ${response.aviso}` }
          : { tone: "success", text: `Decisão "${decisionLabel(decision)}" registrada para ${selected.codigo}.` },
      );
      setDecision("");
      setJustification("");
      setHistoryKey((key) => key + 1);
    } catch (reason) {
      setFeedback({ tone: "error", text: rncErrorMessage(reason) });
      if (reason instanceof ApiError && reason.status === 404) setSelected(null);
    } finally {
      setBusy(false);
      query.reload();
    }
  }

  const columns: TableColumn<RncListItem>[] = [
    { key: "codigo", label: "RNC", render: (row) => row.codigo, sortValue: (row) => row.codigo, sticky: true },
    { key: "criada", label: "Aberta em", render: (row) => formatDateTime(row.criada_em), sortValue: (row) => row.criada_em },
    { key: "produto", label: "Produto / OP", render: (row) => [row.produto, row.op].filter(Boolean).join(" · ") || "Não informado" },
    { key: "resultado", label: "Resultado da peça", render: (row) => (row.resultado_peca ? <StatusBadge value={row.resultado_peca} /> : "Peça não encontrada") },
    {
      key: "vigente",
      label: "Decisão vigente",
      render: (row) => (row.decisao_vigente ? decisionLabel(row.decisao_vigente.decisao) : "Sem decisão"),
      sortValue: (row) => row.decisao_vigente?.decisao ?? "",
    },
    {
      key: "acao",
      label: "",
      render: (row) => (
        <button type="button" className="button" aria-label={`Decidir ${row.codigo}`} onClick={() => choose(row)}>
          {row.decisao_vigente ? "Rever" : "Decidir"}
        </button>
      ),
    },
  ];

  return (
    <PageFrame sectionId="quality" title={TITLE} subtitle={SUBTITLE} filters={false} staleError={data ? query.error : null}>
      <div className="segment-toggle maintenance-tabs" role="tablist" aria-label="Quais RNCs mostrar">
        {[{ pending: true, label: "Sem decisão" }, { pending: false, label: "Todas" }].map((item) => (
          <button
            key={item.label}
            type="button"
            role="tab"
            aria-selected={item.pending === onlyPending}
            className={`segment-toggle__btn${item.pending === onlyPending ? " segment-toggle__btn--active" : ""}`}
            onClick={() => setOnlyPending(item.pending)}
          >
            {item.label}
          </button>
        ))}
      </div>

      {feedback ? <Notice tone={feedback.tone} className="maintenance-feedback">{feedback.text}</Notice> : null}

      {query.loading && !data ? <LoadingState /> : null}
      {query.error && !data ? (
        <div className="state-box state-box--error" role="alert">
          <strong>Não foi possível carregar as RNCs</strong>
          <span>{query.error.status === 403 ? ACCESS_DENIED : "Tente novamente."}</span>
          {query.error.status === 403 ? null : <button type="button" onClick={query.reload}>Tentar novamente</button>}
        </div>
      ) : null}

      {data ? (
        <SectionCard title={onlyPending ? "RNCs sem decisão" : "Todas as RNCs"} className="content-section" action={<span className="section-count">{`${formatNumber(data.count)} RNC(s)`}</span>}>
          {data.count >= LIMIT ? <Notice tone="info">{`Mostrando as ${formatNumber(LIMIT)} mais recentes.`}</Notice> : null}
          <DataTable columns={columns} rows={data.items} rowKey={(row) => row.id} emptyTitle={onlyPending ? "Nenhuma RNC aguardando decisão." : "Nenhuma RNC registrada."} />
        </SectionCard>
      ) : null}

      {selected ? (
        <SectionCard title={`Decisão — ${selected.codigo}`} className="content-section">
          <p>
            {selected.motivo ?? "Sem motivo informado"}
            {selected.resultado_peca ? ` · Peça registrada como ${selected.resultado_peca}.` : ""}
          </p>
          <form className="filter-bar" onSubmit={submit} aria-label="Registrar decisão da RNC">
            <div className="filter-bar__row">
              <label>
                Decisão
                <select value={decision} disabled={busy} onChange={(event) => setDecision(event.target.value as RncDecision | "")}>
                  <option value="">Escolha…</option>
                  {DECISIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                </select>
              </label>
              <label>
                Justificativa
                <input
                  type="text"
                  maxLength={JUSTIFICATION_MAX}
                  placeholder="Por que esta decisão?"
                  value={justification}
                  disabled={busy}
                  onChange={(event) => setJustification(event.target.value)}
                />
              </label>
              <button type="submit" className="button button--primary" disabled={busy || !decision || justification.trim().length < JUSTIFICATION_MIN}>
                Registrar decisão
              </button>
            </div>
          </form>
          <History key={`${selected.id}-${historyKey}`} rncId={selected.id} />
        </SectionCard>
      ) : null}
    </PageFrame>
  );
}
