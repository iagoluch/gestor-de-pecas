import { useEffect, useMemo, useState } from "react";
import { api, apiErrorMessage } from "../../api/client";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { OperatorDialog } from "../../components/OperatorDialog";
import { StopReasonFields } from "../../components/StopReasonFields";
import { assets } from "../../config/assets";
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

/** OP dentro de um plano de Corte — mesma projeção usada na tela de Corte. */
interface HighlightCuttingOp {
  codigo_op?: string;
  id_peca?: string | null;
  produto_codigo?: string | null;
  produto_descricao?: string | null;
  quantidade?: number | null;
  quantidade_op?: number | null;
  setor_destino?: string | null;
}

interface HighlightCuttingPlan {
  programa?: string;
  ops?: HighlightCuttingOp[];
}

interface HighlightCuttingRow {
  codigo_tarefa?: string;
  planos?: HighlightCuttingPlan[];
}

interface HighlightPayload {
  task: { id: number; codigo_tarefa: string; status?: string | null; material?: string | null; espessura?: number | null };
  operations: HighlightOperation[];
  state: { estado: "aguardando" | "inicio" | "retomada" | "parada" | "fim"; evento?: { motivo?: string; comentario?: string } | null };
  timing: { availability: string; started_at?: string | null; state_since?: string | null; current_mode?: "execucao" | "parada" | null; execution_seconds: number; stopped_seconds: number };
  plans?: HighlightPlan[];
  progress?: HighlightProgress;
  history?: HighlightHistoryRow[];
  // Fila de Corte da mesma tarefa: já traz as OPs por programa (peça,
  // descrição e setor de destino), então o Destaque não precisa duplicar
  // essa projeção — só casa pelo nome do programa.
  cutting?: HighlightCuttingRow[];
}

/** Estado físico do posto. A parada sem tarefa vive aqui, não na tarefa. */
interface HighlightResourceState { categoria?: string; motivo?: string; op?: string | null }
interface HighlightQueueResponse {
  items: HighlightQueueTask[];
  count: number;
  planos_disponiveis: number;
  resource_state?: HighlightResourceState | null;
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

function planoTemRepeticao(plano: HighlightPlan, planos: HighlightPlan[]) {
  const programa = String(plano.programa ?? "").trim();
  return Boolean(
    programa
    && planos.filter((item) => String(item.programa ?? "").trim() === programa).length > 1
  );
}

function rotuloPlano(plano: HighlightPlan, planos: HighlightPlan[]) {
  const programa = plano.programa ?? "—";
  return planoTemRepeticao(plano, planos)
    ? `Nesting ${plano.repeticao ?? plano.sequencia ?? "—"} do plano ${programa}`
    : `Plano ${programa}`;
}

export function HighlightPage() {
  const [filterText, setFilterText] = useState("");
  const [loadedTask, setLoadedTask] = useState("");
  const [message, setMessage] = useState("Selecione uma tarefa e um plano liberado pelo Corte.");
  const [dialog, setDialog] = useState<"stop" | "finish" | "history" | "ops" | "activityStart" | "activityFinish" | null>(null);
  const [opsPlano, setOpsPlano] = useState<HighlightPlan | null>(null);
  const [busy, setBusy] = useState(false);
  // Só apresentação: clicar de novo na tarefa já carregada minimiza os
  // planos, sem precisar recarregar nada do backend.
  const [plansCollapsed, setPlansCollapsed] = useState(false);
  const task = useApiQuery<HighlightPayload>(loadedTask ? `/api/v1/highlight/tasks/${encodeURIComponent(loadedTask)}` : null);
  const reasons = useApiQuery<{ items: StopReason[] }>("/api/v1/operator/stop-reasons");
  // A tela do Destaque não tem fila numerada de máquina: ela mostra as
  // tarefas cujo Corte já liberou pelo menos uma chapa.
  const queue = useApiQuery<HighlightQueueResponse>("/api/v1/highlight/queue");
  const [planoSelecionado, setPlanoSelecionado] = useState<HighlightPlan | null>(null);

  useEffect(() => {
    if (task.data) setMessage(`Tarefa ${task.data.task.codigo_tarefa} carregada.`);
  }, [task.data?.task.codigo_tarefa]);

  async function action(
    actionName: "Início" | "Parada" | "Retomar" | "Fim",
    extra: Record<string, unknown> = {},
    // A atividade sem OP é do posto: ela nunca leva a tarefa carregada junto,
    // mesmo quando o operador está consultando uma na tela.
    atividadeSemOp = false,
  ) {
    // Parada e retomada do posto correm sem tarefa: elas atuam no estado
    // físico do Destaque, não no destaque de uma tarefa.
    const semTarefa = atividadeSemOp || actionName === "Parada" || actionName === "Retomar";
    if (!loadedTask && !semTarefa) return;
    setBusy(true);
    try {
      const response = await api.post<{ message: string; current?: HighlightPayload }>("/api/v1/highlight/actions", {
        action: actionName,
        task_code: atividadeSemOp || actionName === "Retomar" ? null : loadedTask || null,
        ...extra,
      });
      setMessage(response.message);
      if (response.current) task.replaceData(response.current);
      setDialog(null);
      if (actionName === "Fim") setPlanoSelecionado(null);
      // A resposta da mutação já traz o read model recalculado. O reload fica
      // como reconciliação quando o endpoint não tem uma tarefa em escopo
      // (parada/retomada do posto) ou em backends antigos.
      if (!response.current) task.reload();
      queue.reload();
    } catch (reason) {
      setMessage(apiErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  // Defesa de apresentação: mesmo que um backend antigo devolva a hierarquia
  // completa, o posto do Destaque nunca oferece plano ainda não cortado.
  const plans = useMemo(
    () => (task.data?.plans ?? []).filter((plano) => plano.status_corte === "Finalizado"),
    [task.data?.plans],
  );
  const progress = task.data?.progress;
  const history = task.data?.history ?? [];
  // As OPs por plano já vêm prontas na fila de Corte da mesma tarefa (mesma
  // projeção usada na tela de Corte); o Destaque só casa pelo programa —
  // uma chapa e suas repetições compartilham as mesmas OPs.
  function opsDoPlano(plano: HighlightPlan): HighlightCuttingOp[] {
    const programa = String(plano.programa ?? "").trim();
    if (!programa) return [];
    for (const linha of task.data?.cutting ?? []) {
      const encontrado = linha.planos?.find((item) => String(item.programa ?? "").trim() === programa);
      if (encontrado?.ops?.length) return encontrado.ops;
    }
    return [];
  }
  const queueItems = queue.data?.items ?? [];
  const filter = filterText.trim().toLocaleUpperCase("pt-BR");
  const filteredQueueItems = filter
    ? queueItems.filter((item) => (
      item.codigo_tarefa.toLocaleUpperCase("pt-BR").includes(filter)
      || String(item.material ?? "").toLocaleUpperCase("pt-BR").includes(filter)
      || item.planos.some((plano) => (
        plano.status_corte === "Finalizado"
        && String(plano.programa ?? "").toLocaleUpperCase("pt-BR").includes(filter)
      ))
    ))
    : queueItems;
  const selectedPlan = planoSelecionado
    ? plans.find((plano) => plano.plano_hash === planoSelecionado.plano_hash) ?? null
    : null;
  const selectedState = selectedPlan?.estado_destaque ?? "aguardando";
  const selectedRunning = ["inicio", "retomada"].includes(selectedState);
  const selectedPaused = selectedState === "parada";

  useEffect(() => {
    setPlanoSelecionado((current) => {
      if (current) {
        const updated = plans.find((plano) => plano.plano_hash === current.plano_hash);
        if (updated) return updated;
      }
      return plans.find((plano) => ["inicio", "retomada", "parada"].includes(plano.estado_destaque ?? ""))
        ?? plans.find((plano) => plano.estado_destaque === "aguardando")
        ?? null;
    });
  }, [plans]);
  // Parada registrada sem tarefa: não existe destaque para retomar pelo
  // Início, então a retomada é do próprio posto.
  const resourceState = queue.data?.resource_state;
  const stoppedWithoutTask = Boolean(
    resourceState?.categoria === "parada" && !String(resourceState?.op ?? "").trim(),
  );
  // Atividade sem tarefa: trabalho real do posto que não pertence a nenhum
  // destaque. Sem plano selecionado o Iniciar abre a atividade, e o Finalizar
  // dela dispensa o crachá — não existe destaque para encerrar.
  const activityInProgress = resourceState?.categoria === "atividade_sem_op";
  const startsActivity = !stoppedWithoutTask && !activityInProgress && !selectedPlan;
  return (
    <section className="highlight-page">
      <div className="highlight-search">
        <label>Filtrar tarefas liberadas<input value={filterText} onChange={(event) => setFilterText(event.target.value)} placeholder="Tarefa, plano ou material" autoFocus /></label>
        {filterText ? <button type="button" className="button" onClick={() => setFilterText("")}>Limpar filtro</button> : null}
      </div>
      <div className="highlight-actions">
        <button
          type="button"
          className="operator-action operator-action--start"
          disabled={busy || (!stoppedWithoutTask && !startsActivity && (!selectedPlan || !["aguardando", "parada"].includes(selectedState)))}
          onClick={() => {
            if (stoppedWithoutTask) return void action("Retomar");
            if (startsActivity) return setDialog("activityStart");
            void action("Início", { plan_hash: selectedPlan?.plano_hash });
          }}
        >
          <img src={assets.operator.actions.start} alt="" />
          <span>{stoppedWithoutTask || selectedPaused ? "Retomar" : startsActivity ? "Iniciar atividade" : "Iniciar"}</span>
        </button>
        <button type="button" className="operator-action operator-action--stop" disabled={busy || stoppedWithoutTask || selectedPaused || (selectedPlan ? !selectedRunning : false)} onClick={() => setDialog("stop")}><img src={assets.operator.actions.stop} alt="" /><span>Parada</span></button>
        <button type="button" className="operator-action operator-action--finish" disabled={busy || (!activityInProgress && (!selectedPlan || !selectedRunning))} onClick={() => setDialog(activityInProgress ? "activityFinish" : "finish")}><img src={assets.operator.actions.finish} alt="" /><span>{activityInProgress ? "Finalizar atividade" : "Finalizar"}</span></button>
      </div>
      <p className="operator-notice" role="status">{message}</p>
      {filteredQueueItems.length ? (
        <div className="highlight-queue" aria-label="Tarefas liberadas pelo Corte">
          {filteredQueueItems.map((item) => (
            <button
              type="button"
              key={item.tarefa_id}
              aria-pressed={loadedTask === item.codigo_tarefa}
              aria-expanded={loadedTask === item.codigo_tarefa ? !plansCollapsed : undefined}
              className={`highlight-queue__task highlight-queue__task--${(item.situacao ?? "PARCIAL").toLowerCase()}${loadedTask === item.codigo_tarefa ? " is-selected" : ""}`}
              onClick={() => {
                if (loadedTask === item.codigo_tarefa) {
                  setPlansCollapsed((current) => !current);
                  return;
                }
                setLoadedTask(item.codigo_tarefa);
                setPlanoSelecionado(null);
                setPlansCollapsed(false);
              }}
            >
              <header>
                <strong>Tarefa {item.codigo_tarefa}</strong>
                <span className="operator-state">{item.situacao === "COMPLETA" ? "Corte concluído" : "Corte parcial"}</span>
              </header>
              <small>{item.chapas_disponiveis ?? 0} plano(s) pronto(s) para destacar</small>
              <small>{item.material ?? "Material não informado"} · {item.espessura ?? "—"} mm</small>
            </button>
          ))}
        </div>
      ) : !task.data ? <EmptyState title={filter ? "Nenhuma tarefa corresponde ao filtro" : "Nenhuma tarefa liberada pelo Corte"} detail={filter ? "Limpe o filtro para restaurar a lista completa." : "Assim que um plano do Laser Ensis for concluído, ele aparece aqui."} /> : null}
      {stoppedWithoutTask ? (
        <p className="operator-notice operator-notice--error">
          Posto parado{resourceState?.motivo ? ` — ${resourceState.motivo}` : ""}. Retome para voltar a apontar.
        </p>
      ) : null}
      {activityInProgress ? (
        <p className="operator-notice">
          {resourceState?.motivo || "Atividade diária"} em andamento neste posto. Finalize para voltar a apontar.
        </p>
      ) : null}
      {task.loading && loadedTask && !task.data ? <LoadingState label="Carregando tarefa…" /> : task.error && !task.data ? <ErrorState error={task.error} onRetry={task.reload} /> : task.data ? (
        <div className="highlight-detail">
          {task.error ? <p className="operator-notice operator-notice--stale" role="alert">Atualização temporariamente indisponível. Os dados exibidos podem estar desatualizados.</p> : null}
          <header><div><small>Tarefa selecionada</small><h2>{task.data.task.codigo_tarefa}</h2></div><span className="operator-state">{plans.length} plano(s) liberado(s)</span></header>
          <dl className="highlight-metrics"><div><dt>Material</dt><dd>{task.data.task.material ?? "Não informado"}</dd></div><div><dt>Espessura</dt><dd>{task.data.task.espessura ?? "Não informada"}</dd></div><div><dt>Tempo em destaque</dt><dd>{formatDuration(task.data.timing.execution_seconds)}</dd></div></dl>

          {plansCollapsed ? null : (
          <section className="highlight-block">
            <header>
              <h3>Escolha o plano para apontar</h3>
              <span>
                {progress?.situacao === "COMPLETA" ? "Corte concluído" : "Corte parcial"}
                {progress?.progresso_corte ? ` · ${progress.progresso_corte}` : ""}
              </span>
            </header>
            {plans.length ? (
              <div className="highlight-plans">
                {plans.map((plano) => {
                  const destacado = plano.estado_destaque === "fim";
                  return (
                    <article
                      key={plano.plano_hash}
                      className={`highlight-plan highlight-plan--${destacado ? "destacado" : "disponivel"}${selectedPlan?.plano_hash === plano.plano_hash ? " highlight-plan--selecionado" : ""}`}
                    >
                      <button
                        type="button"
                        className="highlight-plan__select"
                        aria-pressed={selectedPlan?.plano_hash === plano.plano_hash}
                        disabled={busy}
                        onClick={() => setPlanoSelecionado(plano)}
                      >
                        <header>
                          <small>{selectedPlan?.plano_hash === plano.plano_hash ? "Selecionado" : "Toque para selecionar"}</small>
                          <strong>{rotuloPlano(plano, plans)}</strong>
                        </header>
                        <dl>
                          <div><dt>Chapa</dt><dd>{plano.nome_chapa ?? "—"}</dd></div>
                          <div><dt>Máquina</dt><dd>{plano.maquina ?? "—"}</dd></div>
                          <div><dt>Peças</dt><dd>{plano.quantidade_processo ?? 0}</dd></div>
                          <div><dt>Liberado em</dt><dd>{formatDateTime(plano.cortada_em)}</dd></div>
                        </dl>
                        <span className="operator-state">{PLANO_DESTAQUE_LABEL[plano.estado_destaque ?? "aguardando"]}</span>
                        {destacado ? <small>Concluído por {plano.destaque_operador ?? "—"} em {formatDateTime(plano.destaque_em)}</small> : null}
                      </button>
                      <button
                        type="button"
                        className="highlight-plan__info"
                        aria-label={`Ver OPs do plano ${plano.programa ?? ""}`}
                        onClick={() => { setOpsPlano(plano); setDialog("ops"); }}
                      >
                        <span aria-hidden="true">i</span>
                      </button>
                    </article>
                  );
                })}
              </div>
            ) : <EmptyState title="Nenhum plano liberado" detail="Somente planos concluídos no Laser Ensis aparecem para apontamento." />}
          </section>
          )}

          <section className="highlight-block operator-card-section--history">
            <header><h3>Histórico</h3><div className="operator-card-heading-actions"><span>{history.length}</span><button type="button" onClick={() => setDialog("history")}>Ver mais</button></div></header>
            {history.length ? (
              <div className="operator-card-list">
                {history.slice(-5).reverse().map((row) => <HighlightHistoryCard key={row.id} row={row} />)}
              </div>
            ) : <EmptyState title="Sem eventos registrados" detail="O histórico aparece após o primeiro apontamento do Destaque." />}
          </section>
        </div>
      ) : null}
      {dialog === "stop" ? <HighlightStopDialog taskCode={loadedTask || "—"} planLabel={selectedRunning && selectedPlan ? rotuloPlano(selectedPlan, plans) : undefined} reasons={reasons.data?.items ?? []} onCancel={() => setDialog(null)} onConfirm={(code, comment) => void action("Parada", { stop_reason_code: code, comment, plan_hash: selectedRunning ? selectedPlan?.plano_hash : null })} /> : null}
      {dialog === "finish" ? <HighlightFinishDialog taskCode={loadedTask} planLabel={selectedPlan ? rotuloPlano(selectedPlan, plans) : undefined} operations={task.data?.operations ?? []} onCancel={() => setDialog(null)} onConfirm={(badge) => void action("Fim", { badge, plan_hash: selectedPlan?.plano_hash ?? null })} /> : null}
      {dialog === "activityStart" || dialog === "activityFinish" ? (
        <OperatorDialog title="Atividade diária" size="compact" onCancel={() => setDialog(null)}>
          <p>{dialog === "activityStart" ? "Iniciar uma atividade diária neste posto?" : "Finalizar a atividade diária em andamento?"}</p>
          <div className="operator-dialog__actions">
            <button type="button" onClick={() => setDialog(null)}>Não</button>
            <button
              type="button"
              className="button button--primary"
              disabled={busy}
              onClick={() => void action(dialog === "activityStart" ? "Início" : "Fim", {}, true)}
            >
              Sim
            </button>
          </div>
        </OperatorDialog>
      ) : null}
      {dialog === "history" ? (
        <OperatorDialog title="Histórico do Destaque" size="wide" context={<div className="operator-context-line"><span><small>Tarefa</small><strong>{loadedTask || "—"}</strong></span></div>} onCancel={() => setDialog(null)}>
          {history.length ? (
            <div className="operator-dialog-card-list">
              {[...history].reverse().map((row) => <HighlightHistoryCard key={row.id} row={row} />)}
            </div>
          ) : <EmptyState title="Sem eventos registrados" />}
        </OperatorDialog>
      ) : null}
      {dialog === "ops" && opsPlano ? (
        <OperatorDialog
          title="OPs do plano"
          size="wide"
          context={<div className="operator-context-line"><span><small>Plano</small><strong>{rotuloPlano(opsPlano, plans)}</strong></span></div>}
          onCancel={() => { setDialog(null); setOpsPlano(null); }}
        >
          {opsDoPlano(opsPlano).length ? (
            <ul className="highlight-plan-ops">
              {opsDoPlano(opsPlano).map((op) => (
                <li key={op.codigo_op}>
                  <strong>OP {op.codigo_op}</strong>
                  <span>{op.produto_descricao ? `${op.produto_codigo ?? op.id_peca ?? "—"} — ${op.produto_descricao}` : (op.produto_codigo ?? op.id_peca ?? "—")}</span>
                  <span className="operator-state">{op.setor_destino ?? "Destino não informado"}</span>
                </li>
              ))}
            </ul>
          ) : <EmptyState title="Nenhuma OP encontrada para este plano" />}
        </OperatorDialog>
      ) : null}
    </section>
  );
}

function HighlightHistoryCard({ row }: { row: HighlightHistoryRow }) {
  return (
    <article className="operator-production-card">
      <div><strong>{ESTADO_LABEL[String(row.estado ?? "")] ?? row.estado ?? "—"}</strong><span className="operator-state">{formatDateTime(row.data_hora)}</span></div>
      <dl>
        <div><dt>Motivo</dt><dd>{row.motivo ?? "—"}</dd></div>
        <div><dt>Operador</dt><dd>{row.operador ?? "—"}</dd></div>
      </dl>
      {row.comentario ? <small>{row.comentario}</small> : null}
    </article>
  );
}

function HighlightStopDialog({ taskCode, planLabel, reasons, onCancel, onConfirm }: { taskCode: string; planLabel?: string; reasons: StopReason[]; onCancel: () => void; onConfirm: (code: string, comment: string) => void }) {
  const [code, setCode] = useState(""); const [comment, setComment] = useState(""); const selected = reasons.find((reason) => reason.codigo === code);
  return <OperatorDialog title="Parar Destaque" size="wide" context={<div className="operator-context-line"><span><small>Tarefa</small><strong>{taskCode}</strong></span>{planLabel ? <span><small>Plano</small><strong>{planLabel}</strong></span> : null}</div>} onCancel={onCancel}><StopReasonFields reasons={reasons} code={code} comment={comment} onCodeChange={setCode} onCommentChange={setComment} /><div className="operator-dialog__actions"><button type="button" onClick={onCancel}>Cancelar</button><button type="button" className="button operator-danger" disabled={!code || Boolean(selected?.requer_comentario && !comment.trim())} onClick={() => onConfirm(code, comment)}>Confirmar parada</button></div></OperatorDialog>;
}

/**
 * Conferência das OPs antes do fim do Destaque. A checagem é do operador; ela
 * não altera a regra canônica de finalização, que continua encerrando a tarefa
 * inteira no backend.
 */
function HighlightFinishDialog({ taskCode, planLabel, operations, onCancel, onConfirm }: { taskCode: string; planLabel?: string; operations: HighlightOperation[]; onCancel: () => void; onConfirm: (badge: string) => void }) {
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
      context={<div className="operator-context-line"><span><small>Tarefa</small><strong>{taskCode}</strong></span><span><small>Escopo</small><strong>{planLabel ?? "Plano selecionado"}</strong></span><span><small>Conferidas</small><strong>{checked.length} de {operations.length}</strong></span></div>}
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
