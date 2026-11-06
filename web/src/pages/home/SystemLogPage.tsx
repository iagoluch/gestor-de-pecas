import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { DataTable } from "../../components/DataTable";
import type { TableColumn } from "../../components/DataTable";
import { LoadingState } from "../../components/DataState";
import { Notice } from "../../components/Notice";
import { PageFrame } from "../../components/PageFrame";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import { useApiQuery } from "../../hooks/useApiQuery";
import type { LogLevel, SystemLogEntry, SystemLogResponse, SystemLogSummaryResponse } from "../../types/systemLog";
import { formatDateTime, formatNumber } from "../../utils/format";

const API = "/api/v1/management/system-log";
const LIMIT = 300;
const REFRESH_MS = 10_000;

const LEVELS: Record<LogLevel, string> = { info: "Informação", aviso: "Aviso", erro: "Erro" };
const EMPTY = { nivel: "", busca: "", usuario: "", desde: "", ate: "" };

function toQuery(area: string, filters: typeof EMPTY) {
  const params = new URLSearchParams({ limite: String(LIMIT) });
  if (area) params.set("area", area);
  for (const [key, value] of Object.entries(filters)) {
    if (!value.trim()) continue;
    params.set(key, value.trim());
  }
  return params.toString();
}

/** Log do sistema por área (migration 74). Só admin; a rota e o backend exigem o mesmo. */
export function SystemLogPage() {
  const [area, setArea] = useState("");
  const [draft, setDraft] = useState(EMPTY);
  const [applied, setApplied] = useState(EMPTY);
  const [auto, setAuto] = useState(true);
  const query = useApiQuery<SystemLogResponse>(`${API}?${toQuery(area, applied)}`, { ignoreLiveTick: true });
  const summary = useApiQuery<SystemLogSummaryResponse>(`${API}/summary?horas=24`, { ignoreLiveTick: true });
  const { reload: reloadList } = query;
  const { reload: reloadSummary } = summary;
  const data = query.data;

  useEffect(() => {
    if (!auto) return undefined;
    const timer = window.setInterval(() => {
      reloadList();
      reloadSummary();
    }, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [auto, reloadList, reloadSummary]);

  function submit(event: FormEvent) {
    event.preventDefault();
    setApplied(draft);
  }

  function clear() {
    setDraft(EMPTY);
    setApplied(EMPTY);
    setArea("");
  }

  const columns: TableColumn<SystemLogEntry>[] = [
    { key: "quando", label: "Quando", render: (row) => formatDateTime(row.quando), sortValue: (row) => row.quando, sticky: true },
    { key: "nivel", label: "Nível", render: (row) => <StatusBadge value={LEVELS[row.nivel]} />, sortValue: (row) => row.nivel },
    { key: "area", label: "Área", render: (row) => summary.data?.areas.find((item) => item.area === row.area)?.rotulo ?? row.area, sortValue: (row) => row.area },
    { key: "usuario", label: "Quem", render: (row) => row.usuario ?? "—", sortValue: (row) => row.usuario },
    {
      key: "mensagem",
      label: "O que aconteceu",
      render: (row) => (
        <details>
          <summary>{row.mensagem}</summary>
          <ul className="change-audit__lines">
            <li>{`Evento: ${row.evento}`}</li>
            {row.rota ? <li>{`Rota: ${row.metodo ?? ""} ${row.rota}`}</li> : null}
            {row.status_http ? <li>{`Resposta: ${row.status_http}${row.duracao_ms != null ? ` em ${formatNumber(row.duracao_ms)} ms` : ""}`}</li> : null}
            {row.request_id ? <li>{`Requisição: ${row.request_id}`}</li> : null}
            {row.detalhe ? <li>{`Detalhe: ${JSON.stringify(row.detalhe)}`}</li> : null}
          </ul>
        </details>
      ),
    },
  ];

  return (
    <PageFrame
      sectionId="dev"
      title="Log do Sistema"
      subtitle="O que muda ou falha no sistema, separado por área: ações dos usuários, erros, integrações e serviços. Leituras normais de tela não entram. Guardado por 30 dias. Só leitura."
      filters={false}
      staleError={data ? query.error : null}
    >
      <div className="filter-bar__row" role="group" aria-label="Áreas do log">
        <button type="button" className={`button${area === "" ? " button--primary" : ""}`} aria-pressed={area === ""} onClick={() => setArea("")}>
          Todas
        </button>
        {(summary.data?.areas ?? []).map((item) => (
          <button
            key={item.area}
            type="button"
            className={`button${area === item.area ? " button--primary" : ""}`}
            aria-pressed={area === item.area}
            onClick={() => setArea(item.area)}
            title={`Últimas 24 h: ${item.total} evento(s), ${item.aviso} aviso(s), ${item.erro} erro(s)`}
          >
            {`${item.rotulo} · ${formatNumber(item.total)}${item.erro ? ` · ${formatNumber(item.erro)} erro(s)` : ""}`}
          </button>
        ))}
      </div>

      <form className="filter-bar" onSubmit={submit} aria-label="Filtros do log">
        <div className="filter-bar__row">
          <label>
            Nível
            <select value={draft.nivel} onChange={(event) => setDraft({ ...draft, nivel: event.target.value })}>
              <option value="">Todos</option>
              {Object.entries(LEVELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label>
            Texto
            <input type="text" placeholder="Mensagem, rota ou evento" maxLength={120} value={draft.busca} onChange={(event) => setDraft({ ...draft, busca: event.target.value })} />
          </label>
          <label>
            Quem
            <input type="text" placeholder="Usuário" maxLength={80} value={draft.usuario} onChange={(event) => setDraft({ ...draft, usuario: event.target.value })} />
          </label>
          <label>
            De
            <input type="date" value={draft.desde} onChange={(event) => setDraft({ ...draft, desde: event.target.value })} />
          </label>
          <label>
            Até
            <input type="date" value={draft.ate} onChange={(event) => setDraft({ ...draft, ate: event.target.value })} />
          </label>
          <button type="submit" className="button button--primary">Filtrar</button>
          <button type="button" className="button" onClick={clear}>Limpar</button>
          <label>
            <input type="checkbox" checked={auto} onChange={(event) => setAuto(event.target.checked)} />
            {" Atualizar sozinho (10 s)"}
          </label>
        </div>
      </form>

      {query.loading && !data ? <LoadingState /> : null}
      {query.error && !data ? (
        <div className="state-box state-box--error" role="alert">
          <strong>Não foi possível carregar o log</strong>
          <span>{query.error.status === 403 ? "Esta tela é exclusiva da conta de administração." : "Tente novamente."}</span>
          {query.error.status === 403 ? null : <button type="button" onClick={query.reload}>Tentar novamente</button>}
        </div>
      ) : null}

      {data ? (
        <SectionCard title="Mais recentes primeiro" className="content-section" action={<span className="section-count">{`${formatNumber(data.count)} registro(s)`}</span>}>
          {data.count >= LIMIT ? <Notice tone="info">{`Mostrando os ${formatNumber(LIMIT)} mais recentes. Use os filtros para ver os anteriores.`}</Notice> : null}
          <DataTable columns={columns} rows={data.items} rowKey={(row) => row.id} emptyTitle="Nenhum registro para este filtro." />
        </SectionCard>
      ) : null}
    </PageFrame>
  );
}
