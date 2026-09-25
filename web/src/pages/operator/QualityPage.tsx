import { FormEvent, useMemo, useState } from "react";
import { api, apiErrorMessage } from "../../api/client";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { OperatorDialog } from "../../components/OperatorDialog";
import { assets } from "../../config/assets";
import { useApiQuery } from "../../hooks/useApiQuery";
import type { QualityHistoryItem, QualityQueue, QualityQueueItem, QualitySummary } from "../../types/api";
import { formatDateTime, formatMeasurement } from "../../utils/format";
import { QualityInspectionPage } from "./QualityInspectionPage";
import { Notice } from "../../components/Notice";

const SUMMARY_CARDS: { key: keyof QualitySummary; label: string; tone: string }[] = [
  { key: "aguardando", label: "Aguardando inspeção", tone: "info" },
  { key: "aprovadas", label: "Aprovadas", tone: "ok" },
  { key: "retrabalho", label: "Retrabalho", tone: "warning" },
  { key: "refugo", label: "Refugo", tone: "danger" },
];

const PAGE_SIZE = 8;

function SummaryCards({ resumo }: { resumo: QualitySummary }) {
  return (
    <div className="insp-summary">
      {SUMMARY_CARDS.map((card) => (
        <div key={card.key} className={`insp-summary__card insp-summary__card--${card.tone}`}>
          <span>{card.label}</span>
          <strong>{resumo[card.key]}</strong>
          <small>peças</small>
        </div>
      ))}
    </div>
  );
}

/**
 * Fila de inspeção dimensional (operação INSPECAO). Sem rota de propósito desde a Wave 6B:
 * o posto perdeu a aba Qualidade e o operador entra pelo popup do Iniciar. A tela fica
 * guardada, coberta por `quality.test.tsx`, até o novo ponto de entrada ser definido.
 */
export function QualityPage({ sector }: { sector: string }) {
  const [search, setSearch] = useState("");
  const [applied, setApplied] = useState("");
  const [resource, setResource] = useState("");
  const [page, setPage] = useState(1);
  const [inspection, setInspection] = useState<number | null>(null);
  const [notice, setNotice] = useState("");
  const [opening, setOpening] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [bypass, setBypass] = useState<QualityQueueItem | null>(null);

  const params = new URLSearchParams();
  if (applied) params.set("search", applied);
  if (resource) params.set("resource", resource);
  const query = params.toString();
  const queue = useApiQuery<QualityQueue>(`/api/v1/quality/queue${query ? `?${query}` : ""}`);

  const items = useMemo(() => queue.data?.items ?? [], [queue.data]);
  const pages = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
  const current = Math.min(page, pages);
  const visible = items.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE);

  if (inspection !== null) {
    return (
      <QualityInspectionPage
        inspectionId={inspection}
        onBack={() => {
          setInspection(null);
          queue.reload();
        }}
        onFinished={(message) => {
          setInspection(null);
          setNotice(message);
          queue.reload();
        }}
      />
    );
  }

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    setApplied(search.trim());
    setPage(1);
    setNotice("");
  }

  async function open(item: QualityQueueItem) {
    setOpening(item.op);
    setNotice("");
    try {
      const response = await api.post<{ message: string; data: { id: number } }>(
        "/api/v1/quality/inspections",
        { op: item.op },
      );
      setInspection(response.data.id);
    } catch (reason) {
      setNotice(apiErrorMessage(reason));
    } finally {
      setOpening("");
    }
  }

  // Regra transitória da implantação: enquanto os operadores das máquinas são
  // treinados para inspecionar as próprias peças, a inspeção pode ser pulada.
  // Pular NÃO registra aprovação, cota nem RNC — registra a decisão.
  async function dispensar(item: QualityQueueItem, badge: string, motivo: string) {
    setNotice("");
    try {
      const response = await api.post<{ message: string }>(
        "/api/v1/quality/inspections/bypass",
        { op: item.op, badges: [badge], motivo: motivo || null },
      );
      setNotice(response.message);
      setBypass(null);
      queue.reload();
    } catch (reason) {
      setNotice(apiErrorMessage(reason));
    }
  }

  // A pesquisa é um filtro da fila local: quando não encontra, o backend
  // explica o estado do roteiro. Nenhuma consulta é feita ao ERP por aqui.
  const searchNotice = queue.data?.busca?.message ?? "";

  return (
    <section className="insp-page">
      <SummaryCards resumo={queue.data?.resumo ?? { aguardando: 0, aprovadas: 0, retrabalho: 0, refugo: 0 }} />

      <div className="insp-toolbar">
        <form className="insp-search" onSubmit={submitSearch} role="search">
          <img src={assets.search} alt="" aria-hidden="true" />
          <input
            aria-label="Buscar OP, produto ou data"
            placeholder="Buscar OP, produto ou data"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <button type="submit">Buscar</button>
        </form>
        <label className="insp-filter">
          Máquinas
          <select
            value={resource}
            onChange={(event) => {
              setResource(event.target.value);
              setPage(1);
            }}
          >
            <option value="">Todas</option>
            {(queue.data?.recursos ?? []).map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <button type="button" className="insp-history-button" onClick={() => setHistoryOpen(true)}>Histórico</button>
      </div>

      {notice ? <Notice>{notice}</Notice> : null}
      {searchNotice ? <Notice>{searchNotice}</Notice> : null}

      {queue.loading && !queue.data ? <LoadingState label="Carregando fila de inspeção…" /> : queue.error ? <ErrorState error={queue.error} onRetry={queue.reload} /> : items.length === 0 && !searchNotice ? (
        <EmptyState title="Nenhuma OP aguardando inspeção" detail="A OP entra aqui quando o roteiro chega na operação de inspeção." />
      ) : items.length === 0 ? null : (
        <>
          <div className="insp-table-wrapper">
            <table className="insp-table">
              <thead>
                <tr>
                  <th scope="col">OP</th>
                  <th scope="col">Desc.</th>
                  <th scope="col">Produto</th>
                  <th scope="col">Recurso</th>
                  <th scope="col">Quantidade</th>
                  <th scope="col">Data</th>
                  <th scope="col"><span className="visually-hidden">Ação</span></th>
                </tr>
              </thead>
              <tbody>
                {visible.map((item) => (
                  <tr key={`${item.op}-${item.operacao}`}>
                    <td>{item.op}</td>
                    <td className="insp-table__description">{item.descricao || "—"}</td>
                    <td>{item.produto}</td>
                    <td>{item.recurso_nome || item.recurso}</td>
                    <td>{item.inspecionadas ? `${item.inspecionadas}/${item.quantidade}` : item.quantidade}</td>
                    <td>{item.data ? formatDateTime(item.data) : "—"}</td>
                    <td className="insp-table__acoes">
                      <button
                        type="button"
                        className="insp-skip"
                        aria-label={`Seguir sem inspeção na OP ${item.op}`}
                        disabled={opening === item.op}
                        onClick={() => setBypass(item)}
                      >
                        Sem inspeção
                      </button>
                      <button
                        type="button"
                        className="insp-open"
                        aria-label={`Inspecionar OP ${item.op}`}
                        disabled={opening === item.op}
                        onClick={() => void open(item)}
                      >
                        →
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {pages > 1 ? (
            <nav className="insp-pagination" aria-label="Paginação da fila">
              <button type="button" aria-label="Página anterior" disabled={current <= 1} onClick={() => setPage(current - 1)}>‹</button>
              {Array.from({ length: pages }, (_item, index) => index + 1).map((number) => (
                <button
                  key={number}
                  type="button"
                  aria-current={number === current ? "page" : undefined}
                  className={number === current ? "is-current" : ""}
                  onClick={() => setPage(number)}
                >
                  {number}
                </button>
              ))}
              <button type="button" aria-label="Próxima página" disabled={current >= pages} onClick={() => setPage(current + 1)}>›</button>
            </nav>
          ) : null}
        </>
      )}

      {bypass ? <QualityBypassDialog item={bypass} onCancel={() => setBypass(null)} onConfirm={(badge, motivo) => void dispensar(bypass, badge, motivo)} /> : null}
      {historyOpen ? <QualityHistoryDialog sector={sector} onClose={() => setHistoryOpen(false)} /> : null}
    </section>
  );
}

/**
 * Seguir sem a inspeção formal. O diálogo deixa explícito que **nada** de
 * qualidade será registrado: a OP apenas prossegue, com autor e crachá.
 */
function QualityBypassDialog({ item, onCancel, onConfirm }: { item: QualityQueueItem; onCancel: () => void; onConfirm: (badge: string, motivo: string) => void }) {
  const [badge, setBadge] = useState("");
  const [motivo, setMotivo] = useState("");
  return (
    <OperatorDialog
      title="Seguir sem inspeção"
      size="compact"
      context={<div className="operator-context-line"><span><small>OP</small><strong>{item.op}</strong></span><span><small>Produto</small><strong>{item.produto}</strong></span><span><small>Quantidade</small><strong>{item.quantidade}</strong></span></div>}
      onCancel={onCancel}
    >
      <p>A OP seguirá para a próxima etapa sem a inspeção dimensional.</p>
      <p className="operator-help">
        Nenhuma peça será aprovada, nenhuma cota será medida e nenhuma RNC será
        aberta. Fica registrado apenas que a inspeção foi dispensada.
      </p>
      <label>Crachá de quem autoriza<input value={badge} onChange={(event) => setBadge(event.target.value)} autoFocus /></label>
      <label>Motivo (opcional)<input value={motivo} onChange={(event) => setMotivo(event.target.value)} placeholder="Ex.: operador treinado inspecionou na máquina" /></label>
      <div className="operator-dialog__actions">
        <button type="button" onClick={onCancel}>Cancelar</button>
        <button type="button" className="button button--primary" disabled={!badge.trim()} onClick={() => onConfirm(badge.trim(), motivo.trim())}>
          Confirmar e seguir
        </button>
      </div>
    </OperatorDialog>
  );
}

function QualityHistoryDialog({ sector, onClose }: { sector: string; onClose: () => void }) {
  const [filters, setFilters] = useState({ op: "", product: "", resource: "", result: "", start: "", end: "" });
  const [applied, setApplied] = useState(filters);
  const [detail, setDetail] = useState<number | null>(null);
  const params = new URLSearchParams();
  Object.entries(applied).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  params.set("page_size", "100");
  const history = useApiQuery<{ items: QualityHistoryItem[]; has_more: boolean }>(
    `/api/v1/quality/history?${params.toString()}`,
  );
  const cotas = useApiQuery<{ cotas: { sequencia: number; descricao: string | null; padrao: string; unidade: string | null; medida: string; status: string }[] }>(
    detail === null ? null : `/api/v1/quality/history/pieces/${detail}`,
  );

  return (
    <OperatorDialog title={`Histórico da Qualidade — ${sector}`} size="wide" onCancel={onClose}>
      <div className="insp-history-filters">
        <label>OP<input value={filters.op} onChange={(event) => setFilters({ ...filters, op: event.target.value })} /></label>
        <label>Produto<input value={filters.product} onChange={(event) => setFilters({ ...filters, product: event.target.value })} /></label>
        <label>Recurso<input value={filters.resource} onChange={(event) => setFilters({ ...filters, resource: event.target.value })} /></label>
        <label>
          Resultado
          <select value={filters.result} onChange={(event) => setFilters({ ...filters, result: event.target.value })}>
            <option value="">Todos</option>
            <option value="APROVADA">Aprovada</option>
            <option value="RETRABALHO">Retrabalho</option>
            <option value="REFUGO">Refugo</option>
          </select>
        </label>
        <label>De<input type="date" value={filters.start} onChange={(event) => setFilters({ ...filters, start: event.target.value })} /></label>
        <label>Até<input type="date" value={filters.end} onChange={(event) => setFilters({ ...filters, end: event.target.value })} /></label>
        <button type="button" className="button button--primary" onClick={() => setApplied({ ...filters })}>Filtrar</button>
      </div>
      {history.loading && !history.data ? <LoadingState label="Carregando histórico…" /> : history.error ? <ErrorState error={history.error} onRetry={history.reload} /> : !history.data?.items.length ? (
        <EmptyState title="Sem inspeções registradas no filtro atual" />
      ) : (
        <div className="insp-table-wrapper">
          <table className="insp-table insp-table--history">
            <thead>
              <tr>
                <th scope="col">Data/Hora</th>
                <th scope="col">OP</th>
                <th scope="col">Produto</th>
                <th scope="col">Peça</th>
                <th scope="col">Recurso</th>
                <th scope="col">Operador</th>
                <th scope="col">Resultado</th>
                <th scope="col">RNC</th>
                <th scope="col"><span className="visually-hidden">Detalhes</span></th>
              </tr>
            </thead>
            <tbody>
              {history.data.items.map((item) => (
                <tr key={item.peca_id}>
                  <td>{formatDateTime(item.data)}</td>
                  <td>{item.op}</td>
                  <td>{item.produto}</td>
                  <td>{item.peca}</td>
                  <td>{item.recurso}</td>
                  <td>{item.operador}</td>
                  <td><span className={`insp-result insp-result--${item.resultado.toLowerCase()}`}>{item.resultado}</span></td>
                  <td>{item.rnc ?? "—"}</td>
                  <td>
                    <button type="button" className="insp-detail-button" onClick={() => setDetail(item.peca_id === detail ? null : item.peca_id)}>
                      {detail === item.peca_id ? "Ocultar" : "Ver detalhes"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {detail !== null ? (
        <div className="insp-history-detail">
          <strong>Cotas medidas na peça</strong>
          {cotas.loading ? <LoadingState label="Carregando cotas…" /> : (
            <table className="insp-table">
              <thead><tr><th scope="col">Cota</th><th scope="col">Padrão</th><th scope="col">Medida</th><th scope="col">Status</th></tr></thead>
              <tbody>
                {(cotas.data?.cotas ?? []).map((cota) => (
                  <tr key={cota.sequencia}>
                    <td>{cota.sequencia}{cota.descricao ? ` — ${cota.descricao}` : ""}</td>
                    <td>{formatMeasurement(cota.padrao)} mm</td>
                    <td>{cota.medida}</td>
                    <td><span className={`insp-status insp-status--${cota.status.toLowerCase()}`}>{cota.status === "CONFORME" ? "Conforme" : "Não conforme"}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ) : null}
      <div className="operator-dialog__actions"><button type="button" onClick={onClose}>Fechar</button></div>
    </OperatorDialog>
  );
}
