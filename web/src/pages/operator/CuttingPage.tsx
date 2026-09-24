import { useState } from "react";
import { api, apiErrorMessage } from "../../api/client";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { OperatorDialog } from "../../components/OperatorDialog";
import { StopReasonFields } from "../../components/StopReasonFields";
import { useApiQuery } from "../../hooks/useApiQuery";
import { useDebouncedValue } from "../../hooks/useDebouncedValue";
import type { StopReason } from "../../types/api";
import { formatDateTime, formatDuration } from "../../utils/format";
import { Notice } from "../../components/Notice";

/** Uma chapa física do programa: programa + chapa + repetição, vinda do SigmaNEST. */
interface CuttingSheet {
  apontamento_id?: number | null;
  plano_hash?: string;
  sequencia?: number;
  programa?: string;
  nome_chapa?: string | null;
  repeticao?: number | null;
  status?: string;
  tempo_previsto_segundos?: number | null;
  tempo_real_segundos?: number | null;
  quantidade_processo?: number | null;
  maquina?: string | null;
  operador_inicio?: string | null;
  operador_fim?: string | null;
  data_programa?: string | null;
  data_inicio?: string | null;
  data_fim?: string | null;
}

/** Uma OP do plano, com o produto já projetado localmente. */
interface CuttingOp {
  codigo_op?: string;
  id_peca?: string | null;
  produto_codigo?: string | null;
  produto_descricao?: string | null;
  quantidade?: number | null;
  quantidade_op?: number | null;
  setor_destino?: string | null;
}

/** Um plano da tarefa. Nesting só existe quando o plano repete a chapa. */
interface CuttingPlan {
  programa?: string;
  ordem?: number;
  estado?: string;
  chapas_total?: number;
  chapas_cortadas?: number;
  chapas_em_corte?: number;
  chapas_aguardando?: number;
  chapas_disponiveis_destaque?: number;
  libera_destaque?: boolean;
  repeticoes?: number[];
  nome_chapa?: string | null;
  quantidade_processo?: number;
  tempo_previsto_segundos?: number;
  tempo_real_segundos?: number;
  plano_hash?: string;
  plano_hashes_aguardando?: string[];
  apontamento_ids_em_processo?: number[];
  ops?: CuttingOp[];
  chapas?: CuttingSheet[];
}

interface CuttingRow extends Record<string, unknown> {
  id?: number;
  plano_hash?: string;
  codigo_tarefa?: string;
  programa?: string;
  programa_atual?: string;
  material?: string;
  espessura?: number;
  nome_chapa?: string;
  status?: string;
  nesting_count?: number;
  nestings_concluidos?: number;
  nestings_em_processo?: number;
  nestings_aguardando?: number;
  nesting_atual?: number;
  quantidade_processo?: number;
  tempo_previsto_segundos?: number;
  tempo_real_segundos?: number;
  apontamento_ids_em_processo?: number[];
  data_inicio?: string | null;
  data_fim?: string | null;
  data_programa?: string | null;
  ops_relacionadas?: string[];
  ops_sem_plano?: CuttingOp[];
  quantidade_chapas?: number;
  planos?: CuttingPlan[];
  planos_count?: number;
  expansivel?: boolean;
  chapas_por_programa?: Array<{ programa?: string; chapas?: number; chapas_concluidas?: number }>;
  nestings?: CuttingSheet[];
}

const PLAN_STATE_WAITING_CUT = "AGUARDANDO CORTE";

/** Planos da tarefa. O backend já os entrega; a derivação cobre respostas antigas. */
function planosDaTarefa(item: CuttingRow): CuttingPlan[] {
  if (item.planos?.length) return item.planos;
  const chapas = item.nestings ?? [];
  if (!chapas.length) return [];
  const programas: string[] = [];
  for (const chapa of chapas) {
    const programa = String(chapa.programa ?? "").trim();
    if (programa && !programas.includes(programa)) programas.push(programa);
  }
  return programas.map((programa, indice) => {
    const doPrograma = chapas.filter((chapa) => String(chapa.programa ?? "").trim() === programa);
    return {
      programa,
      ordem: indice + 1,
      estado: item.status === "Em processo" ? "EM CORTE" : PLAN_STATE_WAITING_CUT,
      chapas_total: doPrograma.length,
      chapas_cortadas: doPrograma.filter((chapa) => chapa.status === "Finalizado").length,
      chapas_aguardando: doPrograma.filter((chapa) => chapa.status === "Aguardando").length,
      plano_hash: doPrograma[0]?.plano_hash,
      plano_hashes_aguardando: doPrograma
        .filter((chapa) => chapa.status === "Aguardando")
        .map((chapa) => chapa.plano_hash ?? ""),
      ops: [],
      chapas: doPrograma,
    };
  });
}

function planoTemRepeticao(plano?: CuttingPlan) {
  return Number(plano?.chapas_total ?? plano?.chapas?.length ?? 0) > 1;
}

function planoAtivo(item?: CuttingRow) {
  if (!item) return undefined;
  const planos = planosDaTarefa(item);
  return planos.find((plano) => (
    plano.estado === "EM CORTE"
    || Number(plano.chapas_em_corte ?? 0) > 0
    || plano.chapas?.some((chapa) => chapa.status === "Em processo")
    || (item.programa_atual && plano.programa === item.programa_atual)
  ));
}

function progressoCorteAtivo(item: CuttingRow) {
  const planos = planosDaTarefa(item);
  const ativo = planoAtivo(item);
  if (!ativo) return null;
  if (!planoTemRepeticao(ativo)) {
    const indice = Math.max(0, planos.indexOf(ativo)) + 1;
    return `Plano ${indice}/${planos.length}`;
  }
  const chapas = ativo.chapas ?? [];
  const emProcesso = chapas.findIndex((chapa) => chapa.status === "Em processo");
  const atual = emProcesso >= 0
    ? emProcesso + 1
    : Math.min(Number(ativo.chapas_cortadas ?? 0) + 1, Number(ativo.chapas_total ?? chapas.length));
  return `Nesting ${atual}/${ativo.chapas_total ?? chapas.length}`;
}

function slug(value: string) {
  return value
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replaceAll(" ", "-");
}

function produtoDaOp(op: CuttingOp) {
  const codigo = op.produto_codigo ?? op.id_peca;
  if (op.produto_descricao && codigo) return `${codigo} — ${op.produto_descricao}`;
  return op.produto_descricao ?? codigo ?? "—";
}

interface CuttingSyncState {
  ultima_sincronizacao?: string | null;
  executando?: boolean;
  ciclos?: number;
  erro?: string | null;
  erro_em?: string | null;
  tarefas_novas?: number;
  tarefas_atualizadas?: number;
  chapas_novas?: number;
  automatica?: boolean;
}

interface QueueResponse { resource: string; resource_state?: { categoria?: string; motivo?: string } | null; items: CuttingRow[]; sync?: CuttingSyncState }
interface HistoryResponse { resource: string; status: string; items: CuttingRow[] }

export function CuttingPage({ resource }: { resource: string }) {
  const [search, setSearch] = useState("");
  const appliedSearch = useDebouncedValue(search.trim(), 250);
  const [message, setMessage] = useState("Fila automática — novas tarefas aparecem sozinhas.");
  const [stopOpen, setStopOpen] = useState(false);
  // Atividade diária do posto: só o Sim/Não fica na tela, o tipo é do backend.
  const [activityPrompt, setActivityPrompt] = useState<"Início" | "Finalizado" | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  // Estado só de apresentação: as tarefas chegam recolhidas e o operador
  // expande o que precisa ver. Nada disso precisa existir no banco.
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState("");
  const query = `/api/v1/cutting/queue?resource=${encodeURIComponent(resource)}${appliedSearch ? `&search=${encodeURIComponent(appliedSearch)}` : ""}`;
  const queue = useApiQuery<QueueResponse>(query);
  const reasons = useApiQuery<{ items: StopReason[] }>("/api/v1/operator/stop-reasons");
  const history = useApiQuery<HistoryResponse>(historyOpen ? `/api/v1/cutting/history?resource=${encodeURIComponent(resource)}&status=Finalizado` : null);
  const active = queue.data?.items.find((item) => item.status === "Em processo");
  const activePlan = planoAtivo(active);
  const stopped = queue.data?.resource_state?.categoria === "parada";
  // Atividade sem plano selecionado: trabalho real do posto que não pertence a
  // nenhum nesting. Começa e termina no recurso, como a parada sem nesting.
  const activityInProgress = queue.data?.resource_state?.categoria === "atividade_sem_op";
  const sync = queue.data?.sync;

  // O botão existe para observabilidade: a fila já chega sozinha. Ele dispara
  // o MESMO ciclo do backend e, se um ciclo já estiver rodando, adere a ele.
  async function atualizarTarefas() {
    setSyncing(true);
    setSyncMessage("Atualizando...");
    try {
      const response = await api.post<{ ok: boolean; message?: string }>(
        `/api/v1/cutting/sync?resource=${encodeURIComponent(resource)}`, {},
      );
      const horario = new Date().toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
      setSyncMessage(response.ok
        ? `Atualizado às ${horario} — ${response.message ?? "nenhuma tarefa nova"}`
        : response.message ?? "Não foi possível atualizar as tarefas. Exibindo a última fila sincronizada.");
      queue.reload();
    } catch {
      // A fila local continua na tela: indisponibilidade da origem não apaga
      // o que já foi sincronizado.
      setSyncMessage("Não foi possível atualizar as tarefas. Exibindo a última fila sincronizada.");
    } finally {
      setSyncing(false);
    }
  }

  function toggleTask(codigo: string) {
    setExpanded((atual) => {
      const proximo = new Set(atual);
      if (proximo.has(codigo)) proximo.delete(codigo);
      else proximo.add(codigo);
      return proximo;
    });
  }

  async function action(payload: Record<string, unknown>) {
    setBusy(true);
    try {
      const response = await api.post<{ message: string }>("/api/v1/cutting/actions", { resource, ...payload });
      setMessage(response.message);
      setStopOpen(false);
      setActivityPrompt(null);
      queue.reload();
    } catch (reason) {
      setMessage(apiErrorMessage(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="cutting-page">
      {/* A pesquisa é apenas um filtro do que já está na fila. Descobrir uma
          tarefa nova não depende dela: a fila chega sozinha. */}
      <form className="cutting-search" onSubmit={(event) => event.preventDefault()}>
        <label>Filtrar a fila<input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Tarefa, programa, material ou chapa" /></label>
        <button type="button" className="button button--primary" disabled={syncing} onClick={() => void atualizarTarefas()}>
          {syncing ? "Atualizando..." : "Atualizar tarefas"}
        </button>
        <button type="button" className="button" onClick={() => setHistoryOpen(true)}>Histórico</button>
        {search ? <button type="button" className="button" onClick={() => setSearch("")}>Limpar filtro</button> : null}
      </form>
      <p className="cutting-sync">
        <span>Última sincronização: {formatDateTime(sync?.ultima_sincronizacao)}</span>
        {syncMessage ? <strong className={syncMessage.startsWith("Não foi possível") ? "cutting-sync__erro" : undefined}>{syncMessage}</strong> : null}
      </p>
      <div className="cutting-toolbar">
        <Notice>{message}</Notice>
        <div>
          {/* Retomar não depende de haver OP ativa: uma parada registrada sem
              nesting em processo também precisa de saída pela tela. */}
          {stopped ? <button type="button" className="button button--primary" disabled={busy} onClick={() => void action({ action: "Retomada" })}>Retomar corte</button> : null}
          {!stopped ? <button type="button" className="button operator-danger" disabled={busy} onClick={() => setStopOpen(true)}>Registrar parada</button> : null}
          {/* Sem plano em processo o Início do posto é a atividade diária. */}
          {activityInProgress ? <button type="button" className="button button--primary" disabled={busy} onClick={() => setActivityPrompt("Finalizado")}>Finalizar atividade</button> : null}
          {!stopped && !activityInProgress && !active ? <button type="button" className="button" disabled={busy} onClick={() => setActivityPrompt("Início")}>Iniciar atividade</button> : null}
          {active && !stopped ? <button type="button" className="button button--primary" disabled={busy} onClick={() => void action({ action: "Finalizado", appointment_id: active.apontamento_ids_em_processo?.[0] ?? active.id })}>{planoTemRepeticao(activePlan) ? "Finalizar nesting" : "Finalizar plano"}</button> : null}
        </div>
      </div>
      {stopped ? <Notice tone="error">Recurso parado{queue.data?.resource_state?.motivo ? ` — ${queue.data.resource_state.motivo}` : ""}. Retome antes de finalizar.</Notice> : null}
      {activityInProgress ? <Notice>{queue.data?.resource_state?.motivo || "Atividade diária"} em andamento neste recurso. Finalize para iniciar um corte.</Notice> : null}
      {queue.loading && !queue.data ? <LoadingState label="Carregando fila do Corte…" /> : queue.error && !queue.data ? <ErrorState error={queue.error} onRetry={queue.reload} /> : queue.data?.items.length ? (
        <>
          {queue.error ? <Notice tone="stale">Atualização temporariamente indisponível. Os dados exibidos podem estar desatualizados.</Notice> : null}
          <div className="cutting-queue">
            {queue.data.items.map((item, index) => (
              <CuttingTaskCard
                key={`${item.codigo_tarefa}-${item.plano_hash}-${index}`}
                item={item}
                busy={busy}
                collapsed={!expanded.has(String(item.codigo_tarefa ?? index))}
                onToggle={() => toggleTask(String(item.codigo_tarefa ?? index))}
                onStart={(planHash) => void action({ action: "Início", plan_hash: planHash })}
              />
            ))}
          </div>
        </>
      ) : <EmptyState title={appliedSearch ? "Nenhuma tarefa corresponde ao filtro" : "Nenhum plano na fila"} detail={appliedSearch ? "Limpe o filtro para ver toda a fila do recurso." : "Assim que uma tarefa entrar no planejamento, ela aparece aqui automaticamente."} />}
      {activityPrompt ? (
        <OperatorDialog title="Atividade diária" size="compact" context={<div className="operator-context-line"><span><small>Recurso</small><strong>{resource}</strong></span></div>} onCancel={() => setActivityPrompt(null)}>
          <p>{activityPrompt === "Início" ? "Iniciar uma atividade diária neste recurso?" : "Finalizar a atividade diária em andamento?"}</p>
          <div className="operator-dialog__actions">
            <button type="button" onClick={() => setActivityPrompt(null)}>Não</button>
            <button type="button" className="button button--primary" disabled={busy} onClick={() => void action({ action: activityPrompt })}>Sim</button>
          </div>
        </OperatorDialog>
      ) : null}
      {stopOpen ? <CutStopDialog resource={resource} reasons={reasons.data?.items ?? []} onCancel={() => setStopOpen(false)} onConfirm={(code, comment) => void action({ action: "Parada", stop_reason_code: code, comment })} /> : null}
      {historyOpen ? (
        <OperatorDialog title="Histórico do Corte" size="wide" context={<div className="operator-context-line"><span><small>Recurso</small><strong>{resource}</strong></span></div>} onCancel={() => setHistoryOpen(false)}>
          {history.loading ? <LoadingState label="Carregando histórico…" /> : history.error && !history.data ? <ErrorState error={history.error} onRetry={history.reload} /> : history.data?.items.length ? (
            <div className="table-scroll">
              <table>
                <thead><tr><th>Tarefa</th><th>Programa / plano</th><th>Chapa / repetição</th><th>Máquina</th><th>OPs</th><th>Qtd.</th><th>Publicado SigmaNEST</th><th>Início</th><th>Fim</th><th>Realizado</th><th>Estado final</th></tr></thead>
                <tbody>
                  {history.data.items.flatMap((row, rowIndex) => {
                    const nestings = row.nestings?.length ? row.nestings : [{
                      plano_hash: row.plano_hash,
                      programa: row.programa,
                      nome_chapa: row.nome_chapa,
                      status: row.status,
                      quantidade_processo: row.quantidade_processo,
                      data_programa: row.data_programa,
                      data_inicio: row.data_inicio,
                      data_fim: row.data_fim,
                      tempo_real_segundos: row.tempo_real_segundos,
                      maquina: resource,
                    }];
                    return nestings.map((nesting, nestingIndex) => (
                      <tr key={nesting.plano_hash ?? `${row.codigo_tarefa}-${rowIndex}-${nestingIndex}`}>
                        <td>{row.codigo_tarefa ?? "—"}</td>
                        <td>{nesting.programa ?? "—"}</td>
                        <td>{nesting.nome_chapa ?? "—"}{nesting.repeticao != null ? ` · ${nesting.repeticao}` : ""}</td>
                        <td>{nesting.maquina ?? resource}</td>
                        <td>{row.ops_relacionadas?.length ? row.ops_relacionadas.join(", ") : "—"}</td>
                        <td>{nesting.quantidade_processo ?? 0}</td>
                        <td>{formatDateTime(nesting.data_programa)}</td>
                        <td>{formatDateTime(nesting.data_inicio)}</td>
                        <td>{formatDateTime(nesting.data_fim)}</td>
                        <td>{nesting.tempo_real_segundos == null ? "—" : formatDuration(nesting.tempo_real_segundos)}</td>
                        <td>{nesting.status ?? "—"}</td>
                      </tr>
                    ));
                  })}
                </tbody>
              </table>
            </div>
          ) : <EmptyState title="Nenhum corte finalizado neste recurso" />}
        </OperatorDialog>
      ) : null}
    </section>
  );
}

/** Uma tarefa da fila, com a hierarquia TAREFA -> PLANO -> OP -> PRODUTO. */
function CuttingTaskCard({ item, busy, collapsed, onToggle, onStart }: {
  item: CuttingRow;
  busy: boolean;
  collapsed: boolean;
  onToggle: () => void;
  onStart: (planHash?: string) => void;
}) {
  const planos = planosDaTarefa(item);
  const codigo = item.codigo_tarefa ?? "—";
  return (
    <article className={`cutting-card cutting-card--${slug(String(item.status ?? "aguardando"))}`}>
      <header>
        <button type="button" className="cutting-card__toggle" aria-expanded={!collapsed} onClick={onToggle}>
          <span className="cutting-card__chevron" aria-hidden="true">{collapsed ? "▶" : "▼"}</span>
          <span><small>Tarefa</small><h2>{codigo}</h2></span>
        </button>
        <span className="operator-state">{item.status ?? "Aguardando"}</span>
      </header>
      <dl>
        <div><dt>Material</dt><dd>{item.material ?? "—"}</dd></div>
        <div><dt>Espessura</dt><dd>{item.espessura ?? "—"}</dd></div>
        <div><dt>Planos</dt><dd>{item.planos_count ?? planos.length}</dd></div>
        <div><dt>Chapas</dt><dd>{item.quantidade_chapas ?? item.nesting_count ?? 0}</dd></div>
        <div><dt>Quantidade</dt><dd>{item.quantidade_processo ?? 0}</dd></div>
        <div><dt>Situação</dt><dd>{item.nestings_concluidos ?? 0} cortada(s) · {item.nestings_aguardando ?? 0} aguardando</dd></div>
        <div><dt>Tempo previsto</dt><dd>{formatDuration(item.tempo_previsto_segundos ?? 0)}</dd></div>
        <div><dt>Tempo realizado</dt><dd>{item.tempo_real_segundos == null ? "—" : formatDuration(item.tempo_real_segundos)}</dd></div>
      </dl>
      {collapsed ? null : (
        <div className="cutting-plans">
          {planos.length ? planos.map((plano, indice) => (
            <CuttingPlanBlock
              key={plano.plano_hash ?? plano.programa ?? indice}
              plano={plano}
              busy={busy}
              // O Corte trabalha um nesting por vez na máquina: com a tarefa em
              // processo o comando disponível é Finalizar, na barra de ações.
              podeIniciar={item.status === "Aguardando"}
              onStart={onStart}
            />
          )) : <p className="cutting-plans__vazio">Nenhum plano publicado para esta tarefa.</p>}
          {item.ops_sem_plano?.length ? (
            <p className="cutting-plans__vazio">
              OPs sem plano identificado: {item.ops_sem_plano.map((op) => op.codigo_op).join(", ")}
            </p>
          ) : null}
        </div>
      )}
      {item.status === "Em processo" && progressoCorteAtivo(item) ? <p>Em execução: <strong>{progressoCorteAtivo(item)}</strong></p> : null}
    </article>
  );
}

/** Um plano: suas OPs, seus produtos e suas chapas físicas. */
function CuttingPlanBlock({ plano, busy, podeIniciar, onStart }: { plano: CuttingPlan; busy: boolean; podeIniciar: boolean; onStart: (planHash?: string) => void }) {
  const estado = plano.estado ?? PLAN_STATE_WAITING_CUT;
  const aguardando = plano.plano_hashes_aguardando?.[0];
  // Fechado por padrão: o operador vê Plano/estado/chapas de cara e só abre
  // o detalhe (OPs, produtos, chapas) quando precisa conferir algo.
  const [aberto, setAberto] = useState(false);
  return (
    <section className={`cutting-plan cutting-plan--${slug(estado)}`}>
      <button type="button" className="cutting-plan__toggle" aria-expanded={aberto} onClick={() => setAberto((atual) => !atual)}>
        <span className="cutting-card__chevron" aria-hidden="true">{aberto ? "▼" : "▶"}</span>
        <div><small>Plano</small><strong>{plano.programa ?? "—"}</strong></div>
        <span className="cutting-plan__resumo-curto">{plano.chapas_cortadas ?? 0} de {plano.chapas_total ?? 0} chapas</span>
        <span className="cutting-plan__estado">{estado}</span>
      </button>
      {aberto ? (
        <>
          <dl className="cutting-plan__resumo">
            <div><dt>Chapas</dt><dd>{plano.chapas_cortadas ?? 0} de {plano.chapas_total ?? 0}</dd></div>
            <div><dt>Repetição</dt><dd>{plano.repeticoes?.length ? plano.repeticoes.join(", ") : "—"}</dd></div>
            <div><dt>Chapa</dt><dd>{plano.nome_chapa ?? "—"}</dd></div>
            <div><dt>Tempo previsto</dt><dd>{formatDuration(plano.tempo_previsto_segundos ?? 0)}</dd></div>
          </dl>
          {plano.ops?.length ? (
            <div className="cutting-plan__ops-cabecalho" role="row">
              <span>OP</span><span>Produto</span><span className="cutting-plan__qtd">Qtd</span>
            </div>
          ) : null}
          <ul className="cutting-plan__ops">
            {plano.ops?.length ? plano.ops.map((op) => (
              <li key={op.codigo_op}>
                <strong>OP {op.codigo_op}</strong>
                <span>{produtoDaOp(op)}</span>
                <span className="cutting-plan__qtd">{op.quantidade ?? op.quantidade_op ?? "—"}</span>
              </li>
            )) : <li className="cutting-plan__ops--vazio">Nenhuma OP vinculada a este plano.</li>}
          </ul>
          {plano.chapas?.length ? (
            <div className="cutting-nestings">
              <div className="table-scroll">
                <table>
                  <thead><tr><th>#</th><th>Chapa</th><th>Repetição</th><th>Status</th><th>Previsto</th><th>Realizado</th></tr></thead>
                  <tbody>
                    {plano.chapas.map((chapa) => (
                      <tr key={chapa.plano_hash ?? chapa.sequencia}>
                        <td>{chapa.sequencia ?? "—"}</td>
                        <td>{chapa.nome_chapa ?? "—"}</td>
                        <td>{chapa.repeticao ?? "—"}</td>
                        <td>{chapa.status ?? "—"}</td>
                        <td>{formatDuration(chapa.tempo_previsto_segundos)}</td>
                        <td>{chapa.tempo_real_segundos == null ? "—" : formatDuration(chapa.tempo_real_segundos)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}
        </>
      ) : null}
      {podeIniciar && aguardando ? (
        <button type="button" className="button button--primary" disabled={busy} onClick={() => onStart(aguardando)}>
          Iniciar corte
        </button>
      ) : null}
    </section>
  );
}

function CutStopDialog({ resource, reasons, onCancel, onConfirm }: { resource: string; reasons: StopReason[]; onCancel: () => void; onConfirm: (code: string, comment: string) => void }) {
  const [code, setCode] = useState("");
  const [comment, setComment] = useState("");
  const selected = reasons.find((reason) => reason.codigo === code);
  return <OperatorDialog title="Parada do Corte" size="wide" context={<div className="operator-context-line"><span><small>Recurso</small><strong>{resource}</strong></span></div>} onCancel={onCancel}><StopReasonFields reasons={reasons} code={code} comment={comment} onCodeChange={setCode} onCommentChange={setComment} /><div className="operator-dialog__actions"><button type="button" onClick={onCancel}>Cancelar</button><button type="button" className="button operator-danger" disabled={!code || Boolean(selected?.requer_comentario && !comment.trim())} onClick={() => onConfirm(code, comment)}>Confirmar parada</button></div></OperatorDialog>;
}
