import { useMemo, useState } from "react";
import { api, ApiError } from "../../api/client";
import { AsyncButton } from "../../components/AsyncButton";
import { DataTable } from "../../components/DataTable";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { Notice } from "../../components/Notice";
import type { NoticeTone } from "../../components/Notice";
import { PageFrame } from "../../components/PageFrame";
import { SectionCard } from "../../components/SectionCard";
import { useApiQuery } from "../../hooks/useApiQuery";
import { useDebouncedValue } from "../../hooks/useDebouncedValue";
import { NO_PROTHEUS_STANDARD_TEXT, NO_STANDARD_LABEL } from "../../types/standardTime";
import type {
  StandardTimeListResponse,
  StandardTimeRecalculateStatus,
  StandardTimeRecalculateSummary,
  StandardTimeRow,
  StandardTimeSource,
} from "../../types/standardTime";
import { displayName, formatDateTime, formatNumber } from "../../utils/format";
import { SETORES } from "../home/PausesPage";
import { StandardTimeExplainable } from "./StandardTimeExplainable";

const API = "/api/v1/management/standard-times";
const PAGE_SIZE = 100;

/**
 * Só leitura (decisão de 04/11/2026): o Gestor não cadastra tempo padrão manual.
 * Vale o tempo do Protheus; sem ele, "n/a". O estimado é leitura separada.
 */
const TITLE = "Manufatura — Tempo padrão";
const SUBTITLE = "Consulta do tempo padrão do Protheus por produto, operação e recurso. Sem tempo no Protheus aparece n/a: a engenharia de manufatura ajusta direto no ERP.";

/** Corte fica fora: o previsto vem do SigmaNEST. */
const SETORES_FILTRO = SETORES.filter((setor) => setor !== "Corte");

const SOURCE_BADGE: Record<StandardTimeSource | "none", { label: string; tone: string }> = {
  protheus: { label: "Protheus", tone: "success" },
  estimado: { label: "Estimado", tone: "warning" },
  none: { label: NO_STANDARD_LABEL, tone: "neutral" },
};

/** Mensagem humana por `code`; nunca o código técnico. */
const ERROR_MESSAGES: Record<string, string> = {
  standard_time_access_denied: "Seu perfil não tem acesso ao tempo padrão. Só a engenharia de manufatura e a administração usam esta tela.",
  network_error: "Não foi possível acessar o servidor. Tente novamente.",
};

export function standardTimeErrorMessage(reason: unknown) {
  if (reason instanceof ApiError) return ERROR_MESSAGES[reason.code] ?? "Não foi possível concluir a operação. Tente novamente.";
  return ERROR_MESSAGES.network_error;
}

const explainTarget = (metric: string, row: StandardTimeRow) => ({
  metric,
  produto: row.produto_codigo,
  operacao: row.numero_operacao,
  recurso: row.codigo_recurso,
});

const seconds = (value: number | null | undefined) =>
  value == null ? "—" : `${formatNumber(value, 2)} s`;

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

/** Chave mista: só algumas linhas do catálogo têm Protheus; as demais ficam "n/a". */
function mixedCoverage(row: StandardTimeRow) {
  const comProtheus = row.linhas_com_protheus ?? 0;
  const total = row.linhas_total ?? 0;
  if (comProtheus <= 0 || comProtheus >= total) return null;
  return { comProtheus, total };
}

function operationLabel(row: StandardTimeRow) {
  return `${row.produto_codigo}, operação ${row.numero_operacao}, recurso ${row.codigo_recurso}`;
}

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
      // O servidor responde 202 e calcula em segundo plano; um 409 significa
      // que outro recálculo já está rodando, então só acompanhamos o dele.
      await api.post(`${API}/estimates/recalculate`).catch((reason) => {
        if (!(reason instanceof ApiError && reason.code === RECALCULATING_CODE)) throw reason;
      });
      const summary = await waitForRecalculation();
      setFeedback({ tone: "success", text: recalculateMessage(summary) });
      query.reload();
    } catch (reason) {
      setFeedback({
        tone: "error",
        text: reason instanceof RecalculationFailed
          ? "O recálculo não terminou. Tente de novo; se repetir, avise o suporte."
          : standardTimeErrorMessage(reason),
      });
    }
  }

  const header = (
    <>
      <StandardTimeExplainable context="último recálculo das estimativas" target={{ metric: "std.recalculo" }}>
        Ver como foi o último recálculo
      </StandardTimeExplainable>
      <AsyncButton type="button" className="button button--primary" pendingLabel="Recalculando…" onClick={recalculate}>
        Recalcular estimativas
      </AsyncButton>
    </>
  );

  return (
    <PageFrame sectionId="manufacturing" title={TITLE} subtitle={SUBTITLE} filters={false} actions={header} staleError={query.data ? query.error : null}>
      {feedback ? <Notice tone={feedback.tone}>{feedback.text}</Notice> : null}

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
            Somente sem tempo no Protheus
          </label>
        </div>
        <div className="record-toolbar__meta">
          <span className="record-toolbar__summary">
            {query.data ? `${formatNumber(total)} operação(ões)${somenteSemPadrao ? " sem tempo no Protheus" : ""}` : ""}
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
        title={somenteSemPadrao ? "Operações sem tempo padrão no Protheus" : "Operações e tempos padrão"}
        className="content-section section-card--table"
        action={<span className="section-count">{query.data ? `${formatNumber(total)} no total` : ""}</span>}
      >
        {query.loading && !query.data ? <LoadingState /> : null}
        {query.error && !query.data ? <ErrorState error={query.error} onRetry={query.reload} /> : null}
        {query.data && !items.length ? (
          <EmptyState
            title={filtered || !somenteSemPadrao ? "Nenhuma operação neste filtro" : "Nenhuma operação sem tempo no Protheus"}
            detail={filtered || !somenteSemPadrao
              ? "Ajuste produto, setor ou recurso, ou mostre também as operações que já têm tempo no Protheus."
              : "Todas as operações do catálogo já têm tempo padrão do Protheus."}
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
                { key: "protheus", label: "Tempo padrão (Protheus)", render: (row) => <ProtheusCell row={row} /> },
                { key: "estimado", label: "Estimado", render: (row) => <EstimatedCell row={row} /> },
                {
                  key: "fonte",
                  label: "Fonte em uso",
                  render: (row) => (
                    <StandardTimeExplainable context={`Fonte em uso: ${operationLabel(row)}`} target={explainTarget("std.fonte", row)}>
                      <SourceBadge source={row.fonte_efetiva} />
                    </StandardTimeExplainable>
                  ),
                },
              ]}
            />
            <Pagination offset={offset} count={items.length} total={total} onChange={setOffset} />
          </>
        ) : null}
      </SectionCard>

      <p className="std-time__legend">Só vale o tempo padrão do Protheus; quando ele não tem tempo, aparece {NO_STANDARD_LABEL} e a engenharia de manufatura ajusta direto no ERP. O tempo estimado pelo histórico de execuções fica em coluna separada, não entra na Performance oficial e vale só dali em diante.</p>
    </PageFrame>
  );
}

const RECALCULATING_CODE = "standard_time_recalculation_in_progress";
const RECALCULATE_POLL_MS = 2000;

class RecalculationFailed extends Error {}

/** Consulta o status até o servidor terminar. ponytail: sem tempo limite; fechar a tela encerra o laço pelo fim da página. */
async function waitForRecalculation(): Promise<StandardTimeRecalculateSummary> {
  for (;;) {
    const state = await api.get<StandardTimeRecalculateStatus>(`${API}/estimates/recalculate/status`);
    if (state.status === "done" && state.summary) return state.summary;
    if (state.status === "error" || state.status === "idle") throw new RecalculationFailed();
    await new Promise((resolve) => setTimeout(resolve, RECALCULATE_POLL_MS));
  }
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

/** Tempo do Protheus; sem ele, "n/a" com a explicação de onde se ajusta. */
function ProtheusCell({ row }: { row: StandardTimeRow }) {
  if (row.tempo_protheus_segundos == null) {
    return (
      <span className="std-time__estimated std-time__na" title={NO_PROTHEUS_STANDARD_TEXT}>
        <strong>{NO_STANDARD_LABEL}</strong>
        <small>{NO_PROTHEUS_STANDARD_TEXT}</small>
      </span>
    );
  }
  const value = (
    <StandardTimeExplainable context={`Tempo Protheus ${seconds(row.tempo_protheus_segundos)}: ${operationLabel(row)}`} target={explainTarget("std.protheus", row)}>
      {seconds(row.tempo_protheus_segundos)}
    </StandardTimeExplainable>
  );
  const mixed = mixedCoverage(row);
  if (!mixed) return <>{value}</>;
  return (
    <span className="std-time__estimated">
      <strong>{value}</strong>
      <small className="std-time__mixed">
        {`Protheus em ${formatNumber(mixed.comProtheus)} de ${formatNumber(mixed.total)} OPs (as demais ficam ${NO_STANDARD_LABEL})`}
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
      <strong>
        <StandardTimeExplainable context={`Tempo estimado ${seconds(row.tempo_estimado_segundos)}: ${operationLabel(row)}`} target={explainTarget("std.estimado", row)}>
          {seconds(row.tempo_estimado_segundos)}
        </StandardTimeExplainable>
      </strong>
      <small>estimado{amostras != null ? ` · ${formatNumber(amostras)} amostras` : ""}</small>
      {row.estimado_vigente_desde ? <small>vale a partir de {validFromLabel(row.estimado_vigente_desde)}</small> : null}
    </span>
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
