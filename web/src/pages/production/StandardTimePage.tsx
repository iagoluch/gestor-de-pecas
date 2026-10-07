import { useEffect, useId, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError } from "../../api/client";
import { AsyncButton } from "../../components/AsyncButton";
import { useConfirm } from "../../components/ConfirmDialog";
import { DataTable } from "../../components/DataTable";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { Notice } from "../../components/Notice";
import type { NoticeTone } from "../../components/Notice";
import { OperatorDialog } from "../../components/OperatorDialog";
import { PageFrame } from "../../components/PageFrame";
import { RowActions } from "../../components/RowActions";
import { SectionCard } from "../../components/SectionCard";
import { useApiQuery } from "../../hooks/useApiQuery";
import { useDebouncedValue } from "../../hooks/useDebouncedValue";
import type {
  StandardTimeHistoryEntry,
  StandardTimeListResponse,
  StandardTimeRecalculateSummary,
  StandardTimeRow,
  StandardTimeSource,
} from "../../types/standardTime";
import { displayName, formatDateTime, formatNumber } from "../../utils/format";
import { SETORES } from "../home/PausesPage";

const API = "/api/v1/management/standard-times";
const PAGE_SIZE = 100;
/** Mesmo teto do backend (`MAX_MANUAL_SECONDS_PER_PIECE`): a validação do servidor é a que vale. */
const MAX_SECONDS = 86400;

const TITLE = "Produção — Tempo padrão";
const SUBTITLE = "Cadastre o tempo padrão das operações sem padrão no Protheus e acompanhe as estimativas calculadas pelo histórico.";

/** Corte não recebe tempo manual: o previsto vem do SigmaNEST. */
const SETORES_FILTRO = SETORES.filter((setor) => setor !== "Corte");

const SOURCE_BADGE: Record<StandardTimeSource | "none", { label: string; tone: string }> = {
  protheus: { label: "Protheus", tone: "success" },
  manual: { label: "Manual", tone: "info" },
  estimado: { label: "Estimado", tone: "warning" },
  none: { label: "Sem padrão", tone: "neutral" },
};

const HISTORY_ACTION: Record<string, string> = {
  definido: "Definido",
  alterado: "Alterado",
  removido: "Removido",
};

/** Mensagem humana por `code`; nunca o código técnico. */
const ERROR_MESSAGES: Record<string, string> = {
  standard_time_access_denied: "Seu perfil não tem acesso ao tempo padrão. Só a engenharia de manufatura e a administração usam esta tela.",
  invalid_standard_time: "Tempo inválido. Informe um valor maior que zero e de até 86.400 segundos por peça.",
  invalid_standard_time_key: "Não foi possível identificar a operação. Atualize a lista e tente de novo.",
  standard_time_operation_not_found: "Esta operação não está mais no catálogo ativo. A lista foi atualizada.",
  standard_time_manual_not_found: "Não há tempo manual salvo para esta operação. A lista foi atualizada.",
  standard_time_defined_by_protheus: "O Protheus já define o tempo padrão desta operação, então o valor manual não é aceito. A lista foi atualizada.",
  standard_time_sector_without_standard: "O Corte não recebe tempo manual: o tempo previsto vem do SigmaNEST.",
  network_error: "Não foi possível acessar o servidor. Tente novamente.",
};

/** Erros que indicam que a linha mudou no servidor: vale recarregar a lista. */
const STALE_CODES = new Set([
  "standard_time_operation_not_found",
  "standard_time_manual_not_found",
  "standard_time_defined_by_protheus",
  "standard_time_sector_without_standard",
]);

export function standardTimeErrorMessage(reason: unknown) {
  if (reason instanceof ApiError) return ERROR_MESSAGES[reason.code] ?? "Não foi possível concluir a operação. Tente novamente.";
  return ERROR_MESSAGES.network_error;
}

const isStale = (reason: unknown) => reason instanceof ApiError && STALE_CODES.has(reason.code);

/**
 * Lê "45", "45,5", "45.5" ou "1.234,5" (pt-BR). Devolve o número ou a
 * mensagem de erro humana — a validação final é a do servidor.
 */
export function parseSeconds(text: string): { value: number } | { error: string } {
  const raw = text.trim().replace(/\s/g, "");
  if (!raw) return { error: "Informe o tempo em segundos por peça." };
  let normalized: string | null = null;
  if (raw.includes(",")) {
    if (/^\d{1,3}(\.\d{3})+,\d+$|^\d+,\d+$/.test(raw)) normalized = raw.replace(/\./g, "").replace(",", ".");
  } else if (/^\d+(\.\d+)?$/.test(raw)) {
    normalized = raw;
  }
  if (normalized === null) return { error: "Use só números, por exemplo 45 ou 45,5." };
  const value = Number(normalized);
  if (!Number.isFinite(value) || value <= 0) return { error: "O tempo precisa ser maior que zero." };
  if (value > MAX_SECONDS) return { error: "O tempo máximo é 86.400 segundos por peça (24 horas)." };
  return { value };
}

const seconds = (value: number | null | undefined) =>
  value == null ? "—" : `${formatNumber(value, 2)} s`;

/** Valor no campo de edição: vírgula decimal, sem separador de milhar. */
const toInput = (value: number) => String(value).replace(".", ",");

const shortDate = (value: string | null | undefined) => {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString("pt-BR");
};

/**
 * "Vale a partir de": aceita instante ISO (data e hora) e "YYYY-MM-DD" de backend antigo.
 * Data pura vira só a data, em hora local, para não escorregar um dia por fuso.
 */
export function validFromLabel(value: string | null | undefined) {
  if (!value) return "";
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value.trim());
  if (dateOnly) return new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3])).toLocaleDateString("pt-BR");
  return formatDateTime(value);
}

/** Chave mista: só algumas linhas do catálogo têm Protheus, então o manual não cobre todas as OPs. */
function mixedCoverage(row: StandardTimeRow) {
  const comProtheus = row.linhas_com_protheus ?? 0;
  const total = row.linhas_total ?? 0;
  if (comProtheus <= 0 || comProtheus >= total) return null;
  return { coberto: total - comProtheus, total };
}

/** Por que o campo manual não pode ser editado; `null` = editável. O backend confirma. */
function lockReason(row: StandardTimeRow) {
  if (row.tempo_protheus_segundos != null) return "Definido no Protheus";
  if (/^corte$/i.test((row.tipo_setor ?? "").trim())) return "Corte: o previsto vem do SigmaNEST";
  return null;
}

function operationLabel(row: StandardTimeRow) {
  return `${row.produto_codigo}, operação ${row.numero_operacao}, recurso ${row.codigo_recurso}`;
}

const keyParams = (row: StandardTimeRow) => new URLSearchParams({
  produto_codigo: row.produto_codigo,
  numero_operacao: row.numero_operacao,
  codigo_recurso: row.codigo_recurso,
}).toString();

interface Feedback {
  tone: NoticeTone;
  text: string;
}

export function StandardTimePage() {
  const [produto, setProduto] = useState("");
  const [setor, setSetor] = useState("");
  const [recurso, setRecurso] = useState("");
  const [somenteSemPadrao, setSomenteSemPadrao] = useState(true);
  const [offset, setOffset] = useState(0);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [historico, setHistorico] = useState<StandardTimeRow | null>(null);
  const [confirm, confirmDialog] = useConfirm();
  const debouncedProduto = useDebouncedValue(produto.trim());
  const debouncedRecurso = useDebouncedValue(recurso.trim());

  const path = useMemo(() => {
    const params = new URLSearchParams();
    if (debouncedProduto) params.set("produto", debouncedProduto);
    if (setor) params.set("setor", setor);
    if (debouncedRecurso) params.set("recurso", debouncedRecurso);
    params.set("somente_sem_padrao", String(somenteSemPadrao));
    params.set("limit", String(PAGE_SIZE));
    params.set("offset", String(offset));
    return `${API}?${params.toString()}`;
  }, [debouncedProduto, setor, debouncedRecurso, somenteSemPadrao, offset]);
  const query = useApiQuery<StandardTimeListResponse>(path, { ignoreLiveTick: true });

  const items = query.data?.items ?? [];
  const total = query.data?.total ?? 0;
  const filtered = Boolean(produto || setor || recurso);

  const changeFilter = (apply: () => void) => {
    apply();
    setOffset(0);
    setFeedback(null);
  };
  const clearFilters = () => changeFilter(() => {
    setProduto("");
    setSetor("");
    setRecurso("");
    setSomenteSemPadrao(true);
  });

  async function recalculate() {
    setFeedback(null);
    try {
      const summary = await api.post<StandardTimeRecalculateSummary>(`${API}/estimates/recalculate`);
      setFeedback({ tone: "success", text: recalculateMessage(summary) });
      query.reload();
    } catch (reason) {
      setFeedback({ tone: "error", text: standardTimeErrorMessage(reason) });
    }
  }

  async function removeManual(row: StandardTimeRow) {
    const accepted = await confirm({
      title: "Remover tempo manual",
      message: `O tempo manual de ${operationLabel(row)} será removido e a operação volta a usar o estimado, se houver. O histórico é mantido.`,
      confirmLabel: "Remover tempo manual",
      tone: "danger",
    });
    if (!accepted) return;
    try {
      await api.delete(`${API}/manual?${keyParams(row)}`);
      setFeedback({ tone: "success", text: `Tempo manual removido: ${row.produto_codigo}, operação ${row.numero_operacao}.` });
    } catch (reason) {
      setFeedback({ tone: "error", text: standardTimeErrorMessage(reason) });
      if (!isStale(reason)) return;
    }
    query.reload();
  }

  const header = (
    <AsyncButton type="button" className="button button--primary" pendingLabel="Recalculando…" onClick={recalculate}>
      Recalcular estimativas
    </AsyncButton>
  );

  return (
    <PageFrame sectionId="production" title={TITLE} subtitle={SUBTITLE} filters={false} actions={header} staleError={query.data ? query.error : null}>
      {feedback ? <Notice tone={feedback.tone}>{feedback.text}</Notice> : null}
      {confirmDialog}

      <div className="record-toolbar" role="search" aria-label="Filtros do tempo padrão">
        <div className="record-toolbar__fields">
          <label htmlFor="std-produto">
            Produto
            <input id="std-produto" className="std-time__filter-input" value={produto} placeholder="Código do produto"
              onChange={(event) => changeFilter(() => setProduto(event.target.value))} />
          </label>
          <label htmlFor="std-setor">
            Setor
            <select id="std-setor" value={setor} onChange={(event) => changeFilter(() => setSetor(event.target.value))}>
              <option value="">Todos os setores</option>
              {SETORES_FILTRO.map((nome) => <option key={nome} value={nome}>{nome}</option>)}
            </select>
          </label>
          <label htmlFor="std-recurso">
            Recurso
            <input id="std-recurso" className="std-time__filter-input" value={recurso} placeholder="Código do recurso"
              onChange={(event) => changeFilter(() => setRecurso(event.target.value))} />
          </label>
          <label className="std-time__toggle">
            <input type="checkbox" checked={somenteSemPadrao} onChange={(event) => changeFilter(() => setSomenteSemPadrao(event.target.checked))} />
            Somente sem padrão
          </label>
        </div>
        <div className="record-toolbar__meta">
          <span className="record-toolbar__summary">
            {query.data ? `${formatNumber(total)} operação(ões)${somenteSemPadrao ? " sem padrão" : ""}` : ""}
          </span>
          <button type="button" className="record-toolbar__reset" onClick={clearFilters} disabled={!filtered && somenteSemPadrao}>
            Limpar filtros
          </button>
        </div>
      </div>

      {query.data && query.data.sem_produto > 0 ? (
        <Notice>
          {formatNumber(query.data.sem_produto)} operação(ões) do catálogo estão sem código de produto e não aparecem nesta lista.
        </Notice>
      ) : null}

      <SectionCard
        title={somenteSemPadrao ? "Operações sem tempo padrão" : "Operações e tempos padrão"}
        className="content-section section-card--table"
        action={<span className="section-count">{query.data ? `${formatNumber(total)} no total` : ""}</span>}
      >
        {query.loading && !query.data ? <LoadingState /> : null}
        {query.error && !query.data ? <ErrorState error={query.error} onRetry={query.reload} /> : null}
        {query.data && !items.length ? (
          <EmptyState
            title={filtered || !somenteSemPadrao ? "Nenhuma operação neste filtro" : "Nenhuma operação sem padrão"}
            detail={filtered || !somenteSemPadrao
              ? "Ajuste produto, setor ou recurso, ou mostre também as operações que já têm padrão."
              : "Todas as operações do catálogo já têm tempo padrão do Protheus, manual ou estimado."}
          />
        ) : null}
        {query.data && items.length ? (
          <>
            <DataTable
              rows={items}
              rowKey={(row) => `${row.produto_codigo}|${row.numero_operacao}|${row.codigo_recurso}`}
              columns={[
                {
                  key: "produto",
                  label: "Produto",
                  sticky: true,
                  render: (row) => (
                    <span className="std-time__product">
                      <strong>{row.produto_codigo}</strong>
                      {row.produto_descricao ? <small>{row.produto_descricao}</small> : null}
                    </span>
                  ),
                },
                {
                  key: "operacao",
                  label: "Operação",
                  render: (row) => (
                    <span className="std-time__product">
                      <strong>{row.numero_operacao}</strong>
                      {row.descricao_operacao ? <small>{row.descricao_operacao}</small> : null}
                    </span>
                  ),
                },
                { key: "recurso", label: "Recurso", render: (row) => row.codigo_recurso },
                { key: "setor", label: "Setor", render: (row) => displayName(row.tipo_setor, "—") },
                { key: "protheus", label: "Protheus", render: (row) => <ProtheusCell row={row} /> },
                {
                  key: "manual",
                  label: "Manual (s/peça)",
                  render: (row) => <ManualTimeCell row={row} onSaved={(text) => { setFeedback({ tone: "success", text }); query.reload(); }} onStale={query.reload} />,
                },
                { key: "estimado", label: "Estimado", render: (row) => <EstimatedCell row={row} /> },
                { key: "fonte", label: "Fonte em uso", render: (row) => <SourceBadge source={row.fonte_efetiva} /> },
                {
                  key: "acoes",
                  label: "Ações",
                  render: (row) => (
                    <RowActions
                      label={operationLabel(row)}
                      primary={{ label: "Histórico", onClick: () => setHistorico(row), disabled: row.tempo_manual_segundos == null && !row.manual_alterado_em }}
                      actions={[{ label: "Remover manual", danger: true, disabled: row.tempo_manual_segundos == null, onClick: () => void removeManual(row) }]}
                    />
                  ),
                },
              ]}
            />
            <Pagination offset={offset} count={items.length} total={total} onChange={setOffset} />
          </>
        ) : null}
      </SectionCard>

      <p className="std-time__legend">Fonte em uso: o Protheus sempre vale; sem ele vale o tempo manual; sem os dois, o tempo estimado pelo histórico de execuções. Tempos manuais e estimados valem só dali em diante: não alteram períodos já passados.</p>

      {historico ? <HistoryDialog row={historico} onClose={() => setHistorico(null)} /> : null}
    </PageFrame>
  );
}

function recalculateMessage(summary: StandardTimeRecalculateSummary) {
  const periodo = summary.janela_inicio && summary.janela_fim
    ? ` entre ${shortDate(summary.janela_inicio)} e ${shortDate(summary.janela_fim)}`
    : "";
  return `Estimativas recalculadas: ${formatNumber(summary.chaves_estimadas)} de ${formatNumber(summary.chaves_avaliadas)} operações avaliadas ganharam tempo estimado `
    + `(mínimo de ${formatNumber(summary.amostra_minima)} execuções por operação), usando ${formatNumber(summary.execucoes_elegiveis)} execuções reais${periodo}.`;
}

function SourceBadge({ source }: { source: StandardTimeSource | null }) {
  const badge = SOURCE_BADGE[source ?? "none"] ?? SOURCE_BADGE.none;
  return <span className={`status-badge status-badge--${badge.tone}`}>{badge.label}</span>;
}

function ProtheusCell({ row }: { row: StandardTimeRow }) {
  const mixed = mixedCoverage(row);
  if (!mixed) return <>{seconds(row.tempo_protheus_segundos)}</>;
  return (
    <span className="std-time__estimated">
      <strong>{seconds(row.tempo_protheus_segundos)}</strong>
      <small className="std-time__mixed">
        {`Manual cobre ${formatNumber(mixed.coberto)} de ${formatNumber(mixed.total)} OPs (as demais usam Protheus)`}
      </small>
    </span>
  );
}

function EstimatedCell({ row }: { row: StandardTimeRow }) {
  if (row.tempo_estimado_segundos == null) return <>—</>;
  const amostras = row.estimado_amostras;
  const janela = row.estimado_janela_inicio && row.estimado_janela_fim
    ? `${shortDate(row.estimado_janela_inicio)} a ${shortDate(row.estimado_janela_fim)}`
    : null;
  const detalhe = [
    amostras != null ? `${formatNumber(amostras)} execuções reais` : null,
    janela ? `janela de ${janela}` : null,
    row.estimado_calculado_em ? `calculado em ${formatDateTime(row.estimado_calculado_em)}` : null,
  ].filter(Boolean).join(" · ");
  return (
    <span className="std-time__estimated" title={detalhe ? `Estimado: ${detalhe}` : "Estimado pelo histórico"}>
      <strong>{seconds(row.tempo_estimado_segundos)}</strong>
      <small>estimado{amostras != null ? ` · ${formatNumber(amostras)} amostras` : ""}</small>
      {row.estimado_vigente_desde ? <small>vale a partir de {validFromLabel(row.estimado_vigente_desde)}</small> : null}
    </span>
  );
}

function ManualTimeCell({ row, onSaved, onStale }: {
  row: StandardTimeRow;
  onSaved: (message: string) => void;
  onStale: () => void;
}) {
  const savedValue = row.tempo_manual_segundos == null ? "" : toInput(row.tempo_manual_segundos);
  const savedNote = row.manual_observacao ?? "";
  const [value, setValue] = useState(savedValue);
  const [note, setNote] = useState(savedNote);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const hintId = useId();
  const locked = lockReason(row);
  const dirty = value.trim() !== savedValue || note.trim() !== savedNote;

  // Depois de recarregar a lista, o campo volta a refletir o que está salvo.
  useEffect(() => {
    setValue(savedValue);
    setNote(savedNote);
    setError("");
  }, [savedValue, savedNote]);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (locked || saving) return;
    const parsed = parseSeconds(value);
    if ("error" in parsed) {
      setError(parsed.error);
      return;
    }
    setSaving(true);
    setError("");
    try {
      await api.put(`${API}/manual`, {
        produto_codigo: row.produto_codigo,
        numero_operacao: row.numero_operacao,
        codigo_recurso: row.codigo_recurso,
        segundos_por_peca: parsed.value,
        ...(note.trim() ? { observacao: note.trim() } : {}),
      });
      onSaved(`Tempo manual salvo: ${row.produto_codigo}, operação ${row.numero_operacao}, ${formatNumber(parsed.value, 2)} s por peça.`);
    } catch (reason) {
      setError(standardTimeErrorMessage(reason));
      if (isStale(reason)) onStale();
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="std-time__manual" onSubmit={(event) => void save(event)} noValidate>
      <div className="std-time__manual-row">
        <input
          className="std-time__seconds"
          type="text"
          inputMode="decimal"
          autoComplete="off"
          aria-label={`Tempo manual em segundos por peça: ${operationLabel(row)}`}
          aria-describedby={locked || error ? hintId : undefined}
          aria-invalid={error ? true : undefined}
          placeholder="s/peça"
          value={value}
          disabled={Boolean(locked) || saving}
          onChange={(event) => { setValue(event.target.value); setError(""); }}
        />
        {!locked ? (
          <button type="submit" className="button button--primary std-time__save" disabled={!dirty || saving}>
            {saving ? "Salvando…" : "Salvar"}
          </button>
        ) : null}
      </div>
      {!locked && (dirty || note) ? (
        <input
          className="std-time__note"
          type="text"
          maxLength={500}
          autoComplete="off"
          aria-label={`Observação do tempo manual: ${operationLabel(row)}`}
          placeholder="Observação (opcional)"
          value={note}
          disabled={saving}
          onChange={(event) => setNote(event.target.value)}
        />
      ) : null}
      {locked ? <small id={hintId} className="std-time__hint">{locked}</small> : null}
      {error ? <small id={hintId} className="std-time__error" role="alert">{error}</small> : null}
      {!locked && dirty ? (
        <small className="std-time__hint">Vale a partir do momento em que você salvar; não altera períodos já passados.</small>
      ) : null}
      {!dirty && row.manual_alterado_por && row.tempo_manual_segundos != null ? (
        <small className="std-time__hint">{row.manual_alterado_por}{row.manual_alterado_em ? `, ${formatDateTime(row.manual_alterado_em)}` : ""}</small>
      ) : null}
      {!dirty && row.manual_vigente_desde && row.tempo_manual_segundos != null ? (
        <small className="std-time__hint">vale a partir de {validFromLabel(row.manual_vigente_desde)}</small>
      ) : null}
    </form>
  );
}

function Pagination({ offset, count, total, onChange }: { offset: number; count: number; total: number; onChange: (offset: number) => void }) {
  if (total <= PAGE_SIZE) return null;
  const first = offset + 1;
  const last = offset + count;
  return (
    <nav className="insp-pagination std-time__pagination" aria-label="Paginação do tempo padrão">
      <span className="section-count">{`Mostrando ${formatNumber(first)}–${formatNumber(last)} de ${formatNumber(total)}`}</span>
      <button type="button" disabled={offset <= 0} onClick={() => onChange(Math.max(0, offset - PAGE_SIZE))}>Anterior</button>
      <button type="button" disabled={last >= total} onClick={() => onChange(offset + PAGE_SIZE)}>Próxima</button>
    </nav>
  );
}

function HistoryDialog({ row, onClose }: { row: StandardTimeRow; onClose: () => void }) {
  const query = useApiQuery<{ items: StandardTimeHistoryEntry[] }>(`${API}/manual/history?${keyParams(row)}`, { ignoreLiveTick: true });
  const entries = query.data?.items ?? [];
  return (
    <OperatorDialog title="Histórico do tempo manual" context={operationLabel(row)} onCancel={onClose} size="wide">
      {query.loading && !query.data ? <LoadingState /> : null}
      {query.error && !query.data ? <ErrorState error={query.error} onRetry={query.reload} /> : null}
      {query.data && !entries.length ? <EmptyState title="Sem alterações registradas" detail="Ainda não houve tempo manual nesta operação." /> : null}
      {entries.length ? (
        <DataTable
          rows={entries}
          rowKey={(entry, index) => `${entry.registrado_em}-${index}`}
          columns={[
            { key: "quando", label: "Quando", render: (entry) => formatDateTime(entry.registrado_em) },
            { key: "acao", label: "Ação", render: (entry) => HISTORY_ACTION[entry.acao] ?? displayName(entry.acao) },
            { key: "de", label: "Antes", render: (entry) => seconds(entry.segundos_anterior) },
            { key: "para", label: "Depois", render: (entry) => seconds(entry.segundos_novo) },
            { key: "vigente", label: "Vale a partir de", render: (entry) => validFromLabel(entry.vigente_desde) || "—" },
            { key: "quem", label: "Quem", render: (entry) => entry.usuario_nome || "—" },
            { key: "obs", label: "Observação", render: (entry) => entry.observacao || "—" },
          ]}
        />
      ) : null}
    </OperatorDialog>
  );
}
