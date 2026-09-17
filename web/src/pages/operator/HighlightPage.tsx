import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, apiErrorMessage } from "../../api/client";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { OperatorDialog } from "../../components/OperatorDialog";
import { StopReasonFields } from "../../components/StopReasonFields";
import { useApiQuery } from "../../hooks/useApiQuery";
import type { StopReason } from "../../types/api";
import { formatDateTime, formatDuration } from "../../utils/format";

interface HighlightOperation {
  id: number;
  codigo_op: string;
  id_peca?: string;
  quantidade_atual?: number;
  quantidade_original?: number;
  setor_destino_atual?: string;
}

interface HighlightPlan {
  plano_hash: string;
  programa?: string | null;
  nome_chapa?: string | null;
  sequencia?: number | null;
  repeticao?: number | null;
  maquina?: string | null;
  quantidade_processo?: number | null;
  status_corte?: string;
  cortada_em?: string | null;
  estado_destaque?: "aguardando" | "inicio" | "retomada" | "parada" | "fim";
  destaque_em?: string | null;
  destaque_operador?: string | null;
}

interface HighlightProgress {
  situacao?: "PARCIAL" | "COMPLETA" | null;
  chapas_total?: number | null;
  chapas_cortadas?: number | null;
  chapas_destacadas?: number | null;
  chapas_disponiveis?: number | null;
  progresso_corte?: string | null;
}

interface HighlightQueueTask extends HighlightProgress {
  tarefa_id: number;
  codigo_tarefa: string;
  status_tarefa?: string | null;
  material?: string | null;
  espessura?: number | null;
  planos: HighlightPlan[];
}

interface HighlightHistoryRow {
  id: number;
  estado?: string;
  motivo?: string | null;
  comentario?: string | null;
  operador?: string | null;
  data_hora?: string | null;
}

interface HighlightPayload {
  task: { id: number; codigo_tarefa: string; status?: string | null; material?: string | null; espessura?: number | null };
  operations: HighlightOperation[];
  state: { estado: "aguardando" | "inicio" | "retomada" | "parada" | "fim"; evento?: { motivo?: string; comentario?: string } | null };
  timing: { availability: string; started_at?: string | null; state_since?: string | null; current_mode?: "execucao" | "parada" | null; execution_seconds: number; stopped_seconds: number };
  plans?: HighlightPlan[];
  progress?: HighlightProgress;
  history?: HighlightHistoryRow[];
}

const PLANO_DESTAQUE_LABEL: Record<string, string> = {
  aguardando: "Aguardando destaque",
  inicio: "Destaque em execução",
  retomada: "Destaque em execução",
  parada: "Destaque parado",
  fim: "Destaque concluído",
};

const ESTADO_LABEL: Record<string, string> = {
  inicio: "Em execução",
  retomada: "Em execução",
  parada: "Parada",
  fim: "Finalizada",
  aguardando: "Aguardando",
};

export function HighlightPage() {
  const [taskCode, setTaskCode] = useState("");
  const [loadedTask, setLoadedTask] = useState("");
  const [message, setMessage] = useState("Busque uma tarefa para iniciar o Destaque.");
  const [dialog, setDialog] = useState<"stop" | "finish" | "history" | null>(null);
  const [busy, setBusy] = useState(false);
  const task = useApiQuery<HighlightPayload>(loadedTask ? `/api/v1/highlight/tasks/${encodeURIComponent(loadedTask)}` : null);
  const reasons = useApiQuery<{ items: StopReason[] }>("/api/v1/operator/stop-reasons");
  // A tela do Destaque não tem fila numerada de máquina: ela mostra as
  // tarefas cujo Corte já liberou pelo menos uma chapa.
  const queue = useApiQuery<{ items: HighlightQueueTask[]; count: number; planos_disponiveis: number }>("/api/v1/highlight/queue");
  const [planoSelecionado, setPlanoSelecionado] = useState<HighlightPlan | null>(null);

  useEffect(() => {
    if (task.data) setMessage(`Tarefa ${task.data.task.codigo_tarefa} carregada.`);
  }, [task.data?.task.codigo_tarefa]);

  function search(event: FormEvent) {
    event.preventDefault();
    const value = taskCode.trim().toUpperCase();
    if (!value) return;
    setLoadedTask(value);
  }

  function clearSearch() {
    setTaskCode("");
    setLoadedTask("");
    setPlanoSelecionado(null);
    setMessage("Filtro removido. Todas as tarefas liberadas estão visíveis.");
  }

  async function action(actionName: "Início" | "Parada" | "Fim", extra: Record<string, unknown> = {}) {
    if (!loadedTask && actionName !== "Parada") return;
    setBusy(true);
    try {
      const response = await api.post<{ message: string }>("/api/v1/highlight/actions", { action: actionName, task_code: loadedTask || null, ...extra });
      setMessage(response.message);
      setDialog(null);
      if (actionName === "Fim") setPlanoSelecionado(null);
      task.reload();
      queue.reload();
    } catch (reason) {
      setMessage(apiErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  const state = task.data?.state.estado;
  const plans = task.data?.plans ?? [];
  const progress = task.data?.progress;
  const history = task.data?.history ?? [];
  const queueItems = queue.data?.items ?? [];
  const filter = taskCode.trim().toLocaleUpperCase("pt-BR");
  const filteredQueueItems = filter
    ? queueItems.filter((item) => item.codigo_tarefa.toLocaleUpperCase("pt-BR").includes(filter))
    : queueItems;
  const wholeTaskReady = progress?.situacao === "COMPLETA"
    && Number(progress?.chapas_disponiveis ?? 0) > 0;
  return (
    <section className="highlight-page">
      <form className="highlight-search" onSubmit={search}>
        <label>Buscar tarefa<input value={taskCode} onChange={(event) => setTaskCode(event.target.value)} placeholder="Código da tarefa" autoFocus /></label>
        <button type="submit" className="button button--primary">Buscar</button>
        {taskCode || loadedTask ? <button type="button" className="button" onClick={clearSearch}>Limpar filtro</button> : null}
      </form>
      <div className="highlight-actions">
        <button type="button" className="operator-action operator-action--start" disabled={!task.data || busy || !wholeTaskReady || !["aguardando", "parada"].includes(state ?? "")} onClick={() => { setPlanoSelecionado(null); void action("Início"); }}><span>Início</span></button>
        <button type="button" className="operator-action operator-action--stop" disabled={busy || state === "parada"} onClick={() => setDialog("stop")}><span>Parada</span></button>
        <button type="button" className="operator-action operator-action--finish" disabled={!task.data || busy || !wholeTaskReady || !["inicio", "retomada"].includes(state ?? "")} onClick={() => { setPlanoSelecionado(null); setDialog("finish"); }}><span>Fim</span></button>
      </div>
      <p className="operator-notice" role="status">{message}</p>
      {task.loading && loadedTask ? <LoadingState label="Carregando tarefa…" /> : task.error ? <ErrorState error={task.error} onRetry={task.reload} /> : task.data ? (
        <div className="highlight-detail">
          <header><div><small>Tarefa</small><h2>{task.data.task.codigo_tarefa}</h2></div><span className="operator-state">{ESTADO_LABEL[state ?? "aguardando"]}</span></header>
          <dl className="highlight-metrics"><div><dt>Material</dt><dd>{task.data.task.material ?? "Não informado"}</dd></div><div><dt>Espessura</dt><dd>{task.data.task.espessura ?? "Não informada"}</dd></div><div><dt>Tempo em execução</dt><dd>{formatDuration(task.data.timing.execution_seconds)}</dd></div><div><dt>Tempo parado</dt><dd>{formatDuration(task.data.timing.stopped_seconds)}</dd></div><div><dt>Estado desde</dt><dd>{formatDateTime(task.data.timing.state_since)}</dd></div><div><dt>Início</dt><dd>{formatDateTime(task.data.timing.started_at)}</dd></div></dl>

          <section className="highlight-block">
            <header>
              <h3>Planos da tarefa</h3>
              <span>
                {progress?.situacao === "COMPLETA" ? "Corte concluído" : "Corte parcial"}
                {progress?.progresso_corte ? ` · ${progress.progresso_corte}` : ""}
              </span>
            </header>
            {plans.length ? (
              <div className="highlight-plans">
                {plans.map((plano) => {
                  const cortado = plano.status_corte === "Finalizado";
                  const destacado = plano.estado_destaque === "fim";
                  return (
                    <article
                      key={plano.plano_hash}
                      className={`highlight-plan highlight-plan--${destacado ? "destacado" : cortado ? "disponivel" : "aguardando"}${planoSelecionado?.plano_hash === plano.plano_hash ? " highlight-plan--selecionado" : ""}`}
                    >
                      <header>
                        {/* O plano nunca aparece solto: a tarefa pai encabeça o bloco. */}
                        <small>Tarefa {task.data?.task.codigo_tarefa}</small>
                        {/* Chapas repetidas do mesmo programa só se distinguem
                            pela repetição: ela precisa ficar no título. */}
                        <strong>Plano {plano.programa ?? "—"}{plano.repeticao ? ` · chapa ${plano.repeticao}` : ""}</strong>
                      </header>
                      <dl>
                        <div><dt>Chapa</dt><dd>{plano.nome_chapa ?? "—"}</dd></div>
                        <div><dt>Máquina</dt><dd>{plano.maquina ?? "—"}</dd></div>
                        <div><dt>Peças</dt><dd>{plano.quantidade_processo ?? 0}</dd></div>
                        <div><dt>Corte</dt><dd>{plano.status_corte ?? "Aguardando"}</dd></div>
                      </dl>
                      <span className="operator-state">{PLANO_DESTAQUE_LABEL[plano.estado_destaque ?? "aguardando"]}</span>
                      {cortado && !destacado && ["aguardando", "parada"].includes(plano.estado_destaque ?? "aguardando") ? (
                        <button
                          type="button"
                          className="button button--primary"
                          disabled={busy}
                          onClick={() => {
                            setPlanoSelecionado(plano);
                            void action("Início", { plan_hash: plano.plano_hash });
                          }}
                        >
                          {plano.estado_destaque === "parada" ? "Retomar plano" : "Destacar este plano"}
                        </button>
                      ) : null}
                      {cortado && !destacado && ["inicio", "retomada"].includes(plano.estado_destaque ?? "") ? (
                        <button type="button" className="button" disabled={busy} onClick={() => { setPlanoSelecionado(plano); setDialog("finish"); }}>
                          Concluir plano
                        </button>
                      ) : null}
                      {destacado ? <small>Concluído por {plano.destaque_operador ?? "—"} em {formatDateTime(plano.destaque_em)}</small> : null}
                    </article>
                  );
                })}
              </div>
            ) : <EmptyState title="Nenhum plano cortado ainda" detail="Assim que o Corte concluir uma chapa, ela aparece aqui." />}
          </section>

          <section className="highlight-block">
            <header><h3>OPs da tarefa</h3><span>{task.data.operations.length}</span></header>
            <div className="table-scroll"><table><thead><tr><th>OP</th><th>Peça</th><th>Quantidade</th><th>Destino</th></tr></thead><tbody>{task.data.operations.map((row) => <tr key={row.id}><td>{row.codigo_op}</td><td>{row.id_peca ?? "—"}</td><td>{row.quantidade_atual ?? row.quantidade_original ?? 0}</td><td>{row.setor_destino_atual ?? "—"}</td></tr>)}</tbody></table></div>
          </section>

          <section className="highlight-block">
            <header><h3>Histórico</h3><div className="operator-card-heading-actions"><span>{history.length}</span><button type="button" onClick={() => setDialog("history")}>Ver mais</button></div></header>
            {history.length ? <HighlightHistoryTable rows={history.slice(-5).reverse()} /> : <EmptyState title="Sem eventos registrados" detail="O histórico aparece após o primeiro apontamento do Destaque." />}
          </section>
        </div>
      ) : null}
      {filteredQueueItems.length ? (
        <div className="highlight-queue">
          {filteredQueueItems.map((item) => (
            <button
              type="button"
              key={item.tarefa_id}
              className={`highlight-queue__task highlight-queue__task--${(item.situacao ?? "PARCIAL").toLowerCase()}`}
              onClick={() => { setTaskCode(item.codigo_tarefa); setLoadedTask(item.codigo_tarefa); }}
            >
              <header>
                <strong>Tarefa {item.codigo_tarefa}</strong>
                <span className="operator-state">{item.situacao === "COMPLETA" ? "Corte concluído" : "Corte parcial"}</span>
              </header>
              <small>{item.progresso_corte}</small>
              <small>{item.chapas_disponiveis ?? 0} plano(s) disponível(is) para destaque · {item.chapas_destacadas ?? 0} já destacado(s)</small>
              <small>{item.material ?? "Material não informado"} · {item.espessura ?? "—"} mm</small>
            </button>
          ))}
        </div>
      ) : !task.data ? <EmptyState title={filter ? "Nenhuma tarefa corresponde ao filtro" : "Nenhuma tarefa liberada pelo Corte"} detail={filter ? "Limpe o filtro para restaurar a lista completa." : "Assim que uma chapa for concluída no Corte, a tarefa aparece aqui."} /> : null}
      {dialog === "stop" ? <HighlightStopDialog taskCode={loadedTask || "—"} reasons={reasons.data?.items ?? []} onCancel={() => setDialog(null)} onConfirm={(code, comment) => void action("Parada", { stop_reason_code: code, comment })} /> : null}
      {dialog === "finish" ? <HighlightFinishDialog taskCode={loadedTask} plano={planoSelecionado} operations={task.data?.operations ?? []} onCancel={() => { setDialog(null); setPlanoSelecionado(null); }} onConfirm={(badge) => void action("Fim", { badge, plan_hash: planoSelecionado?.plano_hash ?? null })} /> : null}
      {dialog === "history" ? <OperatorDialog title="Histórico do Destaque" size="wide" context={<div className="operator-context-line"><span><small>Tarefa</small><strong>{loadedTask || "—"}</strong></span></div>} onCancel={() => setDialog(null)}>{history.length ? <HighlightHistoryTable rows={[...history].reverse()} /> : <EmptyState title="Sem eventos registrados" />}</OperatorDialog> : null}
    </section>
  );
}

function HighlightHistoryTable({ rows }: { rows: HighlightHistoryRow[] }) {
  return (
    <div className="table-scroll">
      <table>
        <thead><tr><th>Data</th><th>Evento</th><th>Motivo</th><th>Comentário</th><th>Operador</th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>{formatDateTime(row.data_hora)}</td>
              <td>{ESTADO_LABEL[String(row.estado ?? "")] ?? row.estado ?? "—"}</td>
              <td>{row.motivo ?? "—"}</td>
              <td>{row.comentario ?? "—"}</td>
              <td>{row.operador ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function HighlightStopDialog({ taskCode, reasons, onCancel, onConfirm }: { taskCode: string; reasons: StopReason[]; onCancel: () => void; onConfirm: (code: string, comment: string) => void }) {
  const [code, setCode] = useState(""); const [comment, setComment] = useState(""); const selected = reasons.find((reason) => reason.codigo === code);
  return <OperatorDialog title="Parar Destaque" size="wide" context={<div className="operator-context-line"><span><small>Tarefa</small><strong>{taskCode}</strong></span></div>} onCancel={onCancel}><StopReasonFields reasons={reasons} code={code} comment={comment} onCodeChange={setCode} onCommentChange={setComment} /><div className="operator-dialog__actions"><button type="button" onClick={onCancel}>Cancelar</button><button type="button" className="button operator-danger" disabled={!code || Boolean(selected?.requer_comentario && !comment.trim())} onClick={() => onConfirm(code, comment)}>Confirmar parada</button></div></OperatorDialog>;
}

/**
 * Conferência das OPs antes do fim do Destaque. A checagem é do operador; ela
 * não altera a regra canônica de finalização, que continua encerrando a tarefa
 * inteira no backend.
 */
function HighlightFinishDialog({ taskCode, plano, operations, onCancel, onConfirm }: { taskCode: string; plano?: HighlightPlan | null; operations: HighlightOperation[]; onCancel: () => void; onConfirm: (badge: string) => void }) {
  const [badge, setBadge] = useState("");
  const [search, setSearch] = useState("");
  const [checked, setChecked] = useState<number[]>([]);

  const visible = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase("pt-BR");
    if (!needle) return operations;
    return operations.filter((item) =>
      String(item.codigo_op ?? "").toLocaleLowerCase("pt-BR").includes(needle)
      || String(item.id_peca ?? "").toLocaleLowerCase("pt-BR").includes(needle));
  }, [operations, search]);

  const allChecked = operations.length > 0 && checked.length === operations.length;
  const pending = operations.length - checked.length;

  function toggle(id: number) {
    setChecked((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id]);
  }

  return (
    <OperatorDialog
      title="Finalizar Destaque"
      size="wide"
      context={<div className="operator-context-line"><span><small>Tarefa</small><strong>{taskCode}</strong></span><span><small>Escopo</small><strong>{plano ? `Plano ${plano.programa ?? "—"}${plano.repeticao ? ` · chapa ${plano.repeticao}` : ""}` : "Tarefa completa"}</strong></span><span><small>Conferidas</small><strong>{checked.length} de {operations.length}</strong></span></div>}
      onCancel={onCancel}
    >
      <p>Confira cada OP separada antes de encerrar o Destaque desta tarefa.</p>
      <div className="highlight-checklist__toolbar">
        <label>Buscar peça ou OP<input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Código da OP ou da peça" /></label>
        <button type="button" onClick={() => setChecked(allChecked ? [] : operations.map((item) => item.id))}>
          {allChecked ? "Desmarcar todas" : "Marcar todas"}
        </button>
      </div>
      <div className="highlight-checklist" role="group" aria-label="Conferência das OPs">
        {visible.length ? visible.map((item) => (
          <label key={item.id} className={checked.includes(item.id) ? "highlight-checklist__item highlight-checklist__item--checked" : "highlight-checklist__item"}>
            <input type="checkbox" checked={checked.includes(item.id)} onChange={() => toggle(item.id)} />
            <span>
              <strong>{item.codigo_op}</strong>
              <small>{item.id_peca ?? "Peça não informada"} • {item.quantidade_atual ?? item.quantidade_original ?? 0} un • {item.setor_destino_atual ?? "Destino não informado"}</small>
            </span>
          </label>
        )) : <EmptyState title="Nenhuma OP corresponde à busca" />}
      </div>
      {pending > 0 ? <p className="operator-help">{pending} OP(s) ainda não conferida(s).</p> : null}
      <label>Crachá do operador<input value={badge} onChange={(event) => setBadge(event.target.value)} /></label>
      <div className="operator-dialog__actions">
        <button type="button" onClick={onCancel}>Cancelar</button>
        <button type="button" className="button button--primary" disabled={!badge.trim() || !allChecked} onClick={() => onConfirm(badge.trim())}>Confirmar fim</button>
      </div>
    </OperatorDialog>
  );
}
