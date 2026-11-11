import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, apiErrorMessage } from "../../api/client";
import { AsyncButton } from "../../components/AsyncButton";
import { DataTable } from "../../components/DataTable";
import type { TableColumn } from "../../components/DataTable";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { MetricCard } from "../../components/MetricCard";
import { PageFrame } from "../../components/PageFrame";
import { SectionCard } from "../../components/SectionCard";
import { useManagementFilters } from "../../filters/FilterContext";
import type { FilterField } from "../../filters/FilterContext";
import { useApiQuery } from "../../hooks/useApiQuery";
import { formatDateTime, formatHours, formatNumber } from "../../utils/format";
import {
  PRODUCTION_COLUMNS,
  STATUS_COLUMNS,
  STATUS_PAGE_SIZE,
  SearchPick,
  productionRowKey,
  statusClassName,
  statusRowClass,
  toOptions,
} from "./AuditPages";
import type { ProductionEvent, StatusEvent } from "./AuditPages";

type Tipo = string;
type Row = Record<string, unknown>;

interface Campo { chave: string; rotulo: string }
interface TipoInfo {
  id: Tipo;
  grupo: string;
  titulo: string;
  somente_consulta: boolean;
  descricao: string;
  filtros_comuns: string[];
  filtros_proprios: string[];
  campos: Campo[];
}
interface Catalogo { regra_periodo: string; grupos: string[]; tipos: TipoInfo[] }

interface Relatorio {
  tipo: Tipo;
  titulo: string;
  as_of: string;
  estado: "com_dados" | "zero" | "sem_registros" | "indisponivel";
  fontes: Record<string, string>;
  avisos: string[];
  regra_periodo: string;
  campos: Campo[];
  summary: Record<string, unknown> | null;
  opcoes?: { status: string[]; classes: string[] } | null;
  items: Row[];
  page: { page: number; page_size: number; total: number };
}

/** Campo da barra de filtros → nome do filtro na API (o mesmo do catálogo). */
const FIELD_PARAM: Record<FilterField, string> = {
  sector: "setor", resource: "recurso", op: "op", operation: "operacao", product: "produto", operator: "operador",
};
const FIELD_LABEL: Record<FilterField, string> = {
  sector: "Setor", resource: "Recurso", op: "OP", operation: "Operação", product: "Produto", operator: "Colaborador",
};
const ALL_FIELDS = Object.keys(FIELD_PARAM) as FilterField[];

const EMPTY_TABLE = { status: "", classe: "", aberto: "" };

/** Valor de qualquer campo do registro, para o detalhe. */
function fieldValue(key: string, value: unknown) {
  if (value == null || value === "") return "—";
  if (typeof value === "boolean") return value ? "Sim" : "Não";
  if (key.endsWith("_segundos") && typeof value === "number") return `${formatHours(value)} (${formatNumber(value)} s)`;
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(value)) return formatDateTime(value);
  if (typeof value === "number") return formatNumber(value);
  return String(value);
}

/** "media_ponderada_segundos" → "Media ponderada segundos" (o resumo vem pronto do servidor). */
const summaryLabel = (key: string) => (key.charAt(0).toUpperCase() + key.slice(1)).replaceAll("_", " ");

function Metrics({ tipo, summary }: { tipo: Tipo; summary: Record<string, unknown> | null }) {
  const n = (key: string) => formatNumber(Number(summary?.[key] ?? 0));
  if (tipo === "01") {
    return (
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Eventos de status" value={n("eventos")} />
        <MetricCard label="Recursos" value={n("recursos")} accent="teal" />
        <MetricCard label="Paradas não planejadas" value={n("paradas_nao_planejadas")} accent="danger" />
        <MetricCard label="Em aberto" value={n("em_aberto")} detail="Status que ainda não terminou" accent="warning" />
      </div>
    );
  }
  if (tipo !== "02") {
    // Demais tipos: um cartão por valor simples do resumo; null = sem dado, nunca 0.
    const entries = Object.entries(summary ?? {}).filter(([, value]) => value === null || ["number", "string"].includes(typeof value));
    if (!entries.length) return null;
    return (
      <div className="metric-grid metric-grid--four">
        {entries.slice(0, 8).map(([key, value]) => (
          <MetricCard key={key} label={summaryLabel(key)} value={value === null ? "sem registros" : fieldValue(key, value)} />
        ))}
      </div>
    );
  }
  const orphans = Number(summary?.quantidade_sem_evento ?? 0);
  return (
    <div className="metric-grid metric-grid--four">
      <MetricCard label="Eventos de produção" value={n("eventos")} detail={orphans ? `${formatNumber(orphans)} quantidade(s) sem evento` : undefined} />
      <MetricCard label="Peças boas" value={n("quantidade_boa")} accent="success" />
      <MetricCard label="Refugo" value={n("quantidade_refugo")} accent="danger" />
      <MetricCard label="Retrabalho" value={n("quantidade_retrabalho")} accent="warning" />
    </div>
  );
}

/**
 * Auditoria analítica: um seletor de tipo de relatório sobre as mesmas fontes
 * das telas de eventos. Os filtros comuns (barra global) ficam ao trocar de
 * tipo; o que não vale no tipo escolhido é avisado, nunca apagado.
 */
export function AuditAnalyticsPage() {
  const filters = useManagementFilters();
  const [searchParams, setSearchParams] = useSearchParams();
  const asked = searchParams.get("tipo") ?? "01";
  const [table, setTable] = useState(EMPTY_TABLE);
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<number | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  const catalog = useApiQuery<Catalogo>("/api/v1/audit/reports");
  // Tipo fora do catálogo desta conta: abre o primeiro que ela pode ver.
  const tipo: Tipo = !catalog.data || catalog.data.tipos.some((item) => item.id === asked) ? asked : (catalog.data.tipos[0]?.id ?? "01");
  const info = catalog.data?.tipos.find((item) => item.id === tipo);
  const accepted = new Set([...(info?.filtros_comuns ?? []), ...(info?.filtros_proprios ?? [])]);
  const fields = info ? ALL_FIELDS.filter((field) => accepted.has(FIELD_PARAM[field])) : ALL_FIELDS;
  const base = filters.queryFor(fields);

  // Filtro mudou: volta à página 1 e fecha o detalhe.
  const resetKey = `${tipo}|${base}|${table.status}|${table.classe}|${table.aberto}`;
  const [lastKey, setLastKey] = useState(resetKey);
  if (lastKey !== resetKey) {
    setLastKey(resetKey);
    setPage(1);
    setSelected(null);
  }

  const own = new URLSearchParams();
  if (tipo === "01") {
    if (table.status) own.set("evento_status", table.status);
    if (table.classe) own.set("evento_classe", table.classe);
    if (table.aberto) own.set("em_aberto", "true");
  }
  const filterQuery = own.toString() ? `${base}&${own}` : base;
  const paging = new URLSearchParams({ page: String(page), page_size: String(STATUS_PAGE_SIZE) });
  // Espera o catálogo: assim um tipo sem acesso nunca é pedido à API.
  const query = useApiQuery<Relatorio>(catalog.data ? `/api/v1/audit/reports/${tipo}?${filterQuery}&${paging}` : null);
  // Mostra o último resultado do mesmo tipo enquanto o novo chega (sem piscar).
  const [kept, setKept] = useState<Relatorio | null>(null);
  if (query.data && query.data !== kept) setKept(query.data);
  const data = query.data ?? (kept?.tipo === tipo ? kept : null);

  // Avisos de filtro: ativo na barra, mas este tipo não recorta por ele.
  const ignored = ALL_FIELDS.filter((field) => filters.filters[field].trim() && !fields.includes(field)).map((field) => FIELD_LABEL[field]);
  if (tipo !== "01" && (table.status || table.classe || table.aberto)) ignored.push("Status, Classificação e Situação (só valem nos Eventos de status)");

  const title = "Auditoria analítica";
  const subtitle = info?.descricao ?? "Escolha o tipo de relatório; os filtros comuns continuam valendo ao trocar de tipo.";
  const change = (patch: Partial<typeof EMPTY_TABLE>) => setTable((current) => ({ ...current, ...patch }));
  const chooseTipo = (value: string) => {
    const next = new URLSearchParams(searchParams);
    next.set("tipo", value);
    setSearchParams(next, { replace: true });
  };
  const extraFilters = (
    <>
      <label>Tipo de relatório
        <select value={tipo} onChange={(event) => chooseTipo(event.target.value)}>
          {catalog.data ? (
            catalog.data.grupos.map((grupo) => {
              const tipos = catalog.data!.tipos.filter((item) => item.grupo === grupo);
              return tipos.length ? (
                <optgroup key={grupo} label={grupo}>
                  {tipos.map((item) => <option key={item.id} value={item.id}>{item.id} — {item.titulo}</option>)}
                </optgroup>
              ) : null;
            })
          ) : (
            <option value={tipo}>{tipo}</option>
          )}
        </select>
      </label>
      {tipo === "01" ? (
        <>
          <SearchPick label="Status" value={table.status} options={toOptions(data?.opcoes?.status)} onPick={(value) => change({ status: value })} />
          <SearchPick label="Classificação" value={table.classe} options={toOptions(data?.opcoes?.classes, statusClassName)} onPick={(value) => change({ classe: value })} />
          <label>Situação
            <select value={table.aberto} onChange={(event) => change({ aberto: event.target.value })}>
              <option value="">Todos</option>
              <option value="1">Só em aberto</option>
            </select>
          </label>
        </>
      ) : null}
    </>
  );

  async function exportXlsx() {
    setExportError(null);
    try {
      await api.download(`/api/v1/audit/reports/${tipo}/export.xlsx?${filterQuery}`, `auditoria_tipo_${tipo}.xlsx`);
    } catch (reason) {
      setExportError(`Não foi possível exportar. ${apiErrorMessage(reason)}`);
    }
  }

  const frame = {
    sectionId: "audit" as const,
    title,
    subtitle,
    filterFields: fields,
    extraFilters,
    onClearFilters: () => setTable(EMPTY_TABLE),
    actions: (
      <div className="download-action">
        <div className="download-action__buttons">
          <AsyncButton className="button button--primary" pendingLabel="Gerando…" title="Baixar planilha Excel com todas as linhas, todos os campos, o filtro e o as_of" onClick={exportXlsx}>Exportar Excel</AsyncButton>
        </div>
        {exportError ? <span role="alert" className="download-action__error">{exportError}</span> : null}
      </div>
    ),
  };
  if (catalog.error && !catalog.data) return <PageFrame {...frame}><ErrorState error={catalog.error} onRetry={catalog.reload} /></PageFrame>;
  if (!data && !query.error) return <PageFrame {...frame}><LoadingState /></PageFrame>;
  if (query.error && !data) return <PageFrame {...frame}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  if (!data) return null;

  const total = data.page.total;
  const pages = Math.max(1, Math.ceil(total / STATUS_PAGE_SIZE));
  const items = data.items;
  const detail = selected != null ? items[selected] : null;
  const viewColumn: TableColumn<Row> = {
    key: "view",
    label: "Detalhe",
    render: (row) => {
      const index = items.indexOf(row);
      return (
        <button type="button" className="filter-bar__reset" aria-pressed={selected === index} onClick={() => setSelected(selected === index ? null : index)}>
          {selected === index ? "Fechar" : "Ver"}
        </button>
      );
    },
  };
  const table01 = tipo === "01";
  const genericColumns: TableColumn<Row>[] = data.campos.map((campo) => ({
    key: campo.chave,
    label: campo.rotulo,
    render: (row) => fieldValue(campo.chave, row[campo.chave]),
  }));

  const hasMetrics = data.estado !== "indisponivel" && data.estado !== "sem_registros";
  // Ordem da tela: cards principais (com o as_of) no topo, depois filtros, depois a tabela.
  const summary = (
    <>
      {hasMetrics ? <Metrics tipo={tipo} summary={data.summary} /> : null}
      <p className="chart-note">
        Referência (as_of): <strong>{formatDateTime(data.as_of)}</strong>. {data.regra_periodo}
      </p>
      {data.estado === "zero" ? <p className="chart-note" role="status">Há registros, mas a medida principal soma zero.</p> : null}
    </>
  );

  return (
    <PageFrame staleError={query.error} summary={summary} {...frame}>
      {ignored.length ? (
        <p className="chart-note" role="status">Filtro que não vale neste tipo e foi ignorado: {ignored.join("; ")}.</p>
      ) : null}
      {info?.somente_consulta ? (
        <p className="chart-note" role="status">Só consulta: as ações deste assunto continuam na tela própria.</p>
      ) : null}
      {data.avisos.map((aviso) => <p key={aviso} className="chart-note" role="status">{aviso}</p>)}
      {data.estado === "indisponivel" ? (
        <EmptyState title="Fonte indisponível" detail="Uma fonte obrigatória deste relatório não existe nesta instalação. Isto não quer dizer zero." state="indisponivel" />
      ) : data.estado === "sem_registros" ? (
        <EmptyState title="Sem registros" detail="Nenhum registro no período e nos filtros escolhidos." />
      ) : (
        <>
          <SectionCard title={`${data.tipo} — ${data.titulo}`} className="content-section section-card--table">
            {table01 ? (
              <DataTable<Row>
                rows={items}
                rowKey={(row) => row.id as number}
                rowClassName={(row) => statusRowClass(row as unknown as StatusEvent)}
                columns={[viewColumn, ...(STATUS_COLUMNS as unknown as TableColumn<Row>[])]}
              />
            ) : tipo === "02" ? (
              <DataTable<Row>
                rows={items}
                rowKey={(row, index) => productionRowKey(row as ProductionEvent, index)}
                columns={[viewColumn, ...(PRODUCTION_COLUMNS as unknown as TableColumn<Row>[])]}
              />
            ) : (
              <DataTable<Row> rows={items} rowKey={(_row, index) => `${tipo}-${page}-${index}`} columns={[viewColumn, ...genericColumns]} />
            )}
            {total > STATUS_PAGE_SIZE ? (
              <div className="filter-bar__row" role="navigation" aria-label="Páginas do relatório">
                <button type="button" className="filter-bar__reset" disabled={page <= 1} onClick={() => { setPage(page - 1); setSelected(null); }}>Anterior</button>
                <span>
                  {formatNumber((page - 1) * STATUS_PAGE_SIZE + 1)}–{formatNumber(Math.min(page * STATUS_PAGE_SIZE, total))} de {formatNumber(total)}
                </span>
                <button type="button" className="filter-bar__reset" disabled={page >= pages} onClick={() => { setPage(page + 1); setSelected(null); }}>Próxima</button>
              </div>
            ) : null}
          </SectionCard>
          {detail ? (
            <SectionCard title="Detalhe do registro" className="content-section">
              <dl className="audit-detail">
                {data.campos.map((campo) => (
                  <div key={campo.chave}>
                    <dt>{campo.rotulo}</dt>
                    <dd>{fieldValue(campo.chave, detail[campo.chave])}</dd>
                  </div>
                ))}
              </dl>
            </SectionCard>
          ) : null}
        </>
      )}
    </PageFrame>
  );
}
