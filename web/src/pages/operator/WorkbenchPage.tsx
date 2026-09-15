import { FormEvent, useEffect, useMemo, useState } from "react";
import { ApiError } from "../../api/client";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { OperatorDialog } from "../../components/OperatorDialog";
import { StopReasonFields } from "../../components/StopReasonFields";
import { assets } from "../../config/assets";
import { useApiQuery } from "../../hooks/useApiQuery";
import type {
  FirstPieceGate,
  FirstPieceState,
  OperatorCard,
  OperatorDrawing,
  OperatorOperation,
  QualityDimension,
  StopReason,
} from "../../types/api";
import { formatDateTime } from "../../utils/format";
import {
  type DraftDimension,
  TemplateEditor,
  previewStatus,
  rangeLabel,
} from "./QualityInspectionPage";
import { operatorErrorMessage, postOperator } from "./OperatorPortalPage";

type DialogState =
  | { kind: "stop" }
  | { kind: "finish" }
  | { kind: "confirm"; action: "Setup" | "Retrabalho" }
  | { kind: "authorization"; action: string; code: string; details?: Record<string, unknown> }
  | { kind: "list"; source: "production" | "queue" | "history" }
  | { kind: "route"; operationKey: string }
  | { kind: "gate" }
  | { kind: "drawing" }
  | null;

/** Códigos em que a recusa do backend é a própria orientação ao operador:
 *  a primeira peça ainda não foi conferida, e quem abre o checklist é o botão
 *  Setup. Depois da primeira peça aprovada, Iniciar e Finalizar seguem o fluxo
 *  normal do setor e não passam por aqui. */
const GATE_CODES = ["primeira_peca_gate_obrigatorio", "primeira_peca_bloqueada"];

interface OperationsSync { source?: string; pending?: boolean; remote_available?: boolean; status?: string; message?: string; found?: boolean }
interface OperationsResponse { items: OperatorOperation[]; sync?: OperationsSync }
interface WorkbenchResponse { sector: string; resource: string; queue: OperatorCard[]; production: OperatorCard[] }
interface HistoryResponse { sector: string; resource: string; items: OperatorCard[]; page: number; page_size: number; has_more: boolean }
interface OperatorBadge { cracha: string; nome: string; ativo?: boolean }
interface OperationContext {
  op: string;
  operation: string;
  resource: string;
  product: string;
  description: string;
  planned: number;
  registeredGood: number;
  registeredScrap: number;
  attended: number;
  balance: number;
}

function operationLabel(item: OperatorOperation) {
  return [item.numero_operacao ?? item.codigo, item.descricao_operacao ?? item.recurso_nome].filter(Boolean).join(" - ");
}

function routeStepKey(item: OperatorOperation | undefined) {
  if (!item) return "";
  const id = item.id ?? item.catalogo_operacao_id;
  if (id != null) return `id:${String(id)}`;
  const number = String(item.numero_operacao ?? item.codigo ?? "").trim();
  return number ? `number:${number}` : "";
}

function routeStateLabel(item: OperatorOperation) {
  return item.visual_status === "done" ? "Concluída" : item.visual_status === "current" ? "Atual" : "Próxima";
}

/** O backend é a autoridade. `selectable` chega dele; a leitura antiga
 *  (somente a etapa atual apontável) permanece como retrocompatibilidade. */
function isSelectable(item: OperatorOperation | undefined) {
  if (!item) return false;
  if (typeof item.selectable === "boolean") return item.selectable;
  return item.actionable !== false && item.visual_status !== "done";
}

/** Etapa diferente da atual exige confirmação explícita antes de selecionar. */
function needsRouteConfirmation(item: OperatorOperation | undefined) {
  if (!item || !isSelectable(item)) return false;
  if (typeof item.requires_confirmation === "boolean") return item.requires_confirmation;
  return item.visual_status !== "current";
}

function cardKey(item: OperatorCard) {
  return `${String(item.op ?? "").trim()}::${String(item.catalogo_operacao_id ?? item.id ?? item.numero_operacao ?? item.operation ?? "").trim()}`;
}

function OperatorCardView({ item, onSelect, selected = false }: { item: OperatorCard; onSelect: (item: OperatorCard) => void; selected?: boolean }) {
  return (
    <button type="button" className={`operator-production-card ${selected ? "operator-production-card--selected" : ""}`} aria-pressed={selected} onClick={() => onSelect(item)}>
      <div><strong>{selected ? <span className="operator-card-check" aria-hidden="true">✓ </span> : null}OP: {String(item.op ?? "—")}</strong><span className={`operator-state operator-state--${String(item.status ?? "aguardando").toLowerCase().replaceAll(" ", "-")}`}>{String(item.status ?? "Aguardando")}</span></div>
      <dl>
        <div><dt>Operação</dt><dd>{String(item.operation ?? item.numero_operacao ?? "—")}</dd></div>
        <div><dt>Produto</dt><dd>{String(item.product ?? "—")}</dd></div>
        <div><dt>Descrição</dt><dd>{String(item.description ?? "—")}</dd></div>
        <div><dt>Quantidade</dt><dd>{String(item.qty ?? 0)}</dd></div>
        <div><dt>Boas</dt><dd>{String(item.good ?? 0)}</dd></div>
        <div><dt>Refugo</dt><dd>{String(item.scrap ?? 0)}</dd></div>
      </dl>
      {item.elapsed ? <small>Tempo: {item.elapsed}</small> : null}
      {item.last_updated_at ? <small>Última atualização: {formatDateTime(item.last_updated_at)}</small> : null}
      {item.motivo_parada ? <small className="operator-card-alert">Motivo: {item.motivo_parada}</small> : null}
      {item.stopped_since ? <small className="operator-card-alert">Desde: {formatDateTime(item.stopped_since)}</small> : null}
      {item.status_elapsed ? <small className="operator-card-alert">Tempo parado: {item.status_elapsed}</small> : null}
    </button>
  );
}

function CardSection({ title, items, emptyTitle, onSelect, onMore, selectedKey, className = "" }: { title: string; items: OperatorCard[]; emptyTitle: string; onSelect: (item: OperatorCard) => void; onMore: () => void; selectedKey: string; className?: string }) {
  return <section className={className}><header><h2>{title}</h2><div className="operator-card-heading-actions"><span>{items.length}</span><button type="button" onClick={onMore}>Ver mais</button></div></header><div className="operator-card-list">{items.length ? items.slice(0, 2).map((item, index) => <OperatorCardView key={`${item.id ?? item.op}-${index}`} item={item} selected={cardKey(item) === selectedKey} onSelect={onSelect} />) : <EmptyState title={emptyTitle} />}</div></section>;
}

export function WorkbenchPage({ sector, resource, hasSetup = true }: { sector: string; resource: string; hasSetup?: boolean }) {
  const [op, setOp] = useState("");
  const [loadedOp, setLoadedOp] = useState("");
  const [routeSelection, setRouteSelection] = useState<{ op: string; operationKey: string } | null>(null);
  const [message, setMessage] = useState("Produção e fila atualizadas.");
  const [submitting, setSubmitting] = useState(false);
  const [dialog, setDialog] = useState<DialogState>(null);
  // Busca sob demanda: a OP digitada pode existir só no TOTVS. O operador não
  // abre o PCPA109 e não precisa saber se ela já foi sincronizada antes.
  const [remoteSearch, setRemoteSearch] = useState<"idle" | "searching">("idle");
  const [searchedOp, setSearchedOp] = useState("");
  const operationsPath = loadedOp
    ? `/api/v1/operator/operations/${encodeURIComponent(loadedOp)}?resource=${encodeURIComponent(resource)}`
    : null;
  const operations = useApiQuery<OperationsResponse>(operationsPath);
  const cards = useApiQuery<WorkbenchResponse>(`/api/v1/operator/workbench?resource=${encodeURIComponent(resource)}`);
  const historyQuery = useApiQuery<HistoryResponse>(`/api/v1/operator/history?resource=${encodeURIComponent(resource)}&page=1&page_size=100`);
  const reasons = useApiQuery<{ items: StopReason[] }>("/api/v1/operator/stop-reasons");
  const operators = useApiQuery<{ items: OperatorBadge[] }>("/api/v1/operator/operators");
  // Desenho da peça: o backend resolve o arquivo na rede e devolve só o
  // metadado. O operador nunca escolhe pasta e nunca vê caminho de rede.
  const drawing = useApiQuery<OperatorDrawing>(
    loadedOp ? `/api/v1/operator/drawings?op=${encodeURIComponent(loadedOp)}` : null,
  );
  // Wave 6B — o portão Setup/Qualidade é lido só quando o popup abre. Fora
  // dele o roteiro já traz o estado que a tela precisa.
  const [gateOperationKey, setGateOperationKey] = useState("");
  const gate = useApiQuery<FirstPieceState>(gateOperationKey || null);

  // Uma OP nova por digitação: a busca remota anterior não vale para outra OP.
  useEffect(() => {
    setRemoteSearch("idle");
    setSearchedOp("");
  }, [loadedOp]);

  // A OP não está no Gestor, mas pode existir no TOTVS. Pede UMA vez por OP:
  // repetir a mesma consulta não pode virar carga no ERP.
  useEffect(() => {
    const sync = operations.data?.sync;
    const rows = operations.data?.items ?? [];
    if (!loadedOp || rows.length || !sync?.pending || searchedOp === loadedOp) return;
    const op = loadedOp;
    setSearchedOp(op);
    setRemoteSearch("searching");
    setMessage("Buscando OP no TOTVS...");
    postOperator<{ sync?: OperationsSync }>(`/api/v1/operator/operations/${encodeURIComponent(op)}/sync?resource=${encodeURIComponent(resource)}`, {})
      .then((result) => {
        setRemoteSearch("idle");
        if (result.sync?.found) {
          // A OP entrou pelo pipeline canônico; o roteiro vem do backend.
          operations.reload();
          return;
        }
        setMessage(result.sync?.message ?? "OP não encontrada no TOTVS.");
      })
      .catch((reason) => {
        setRemoteSearch("idle");
        // O backend já devolve a frase de operador; nada técnico chega aqui.
        setMessage(operatorErrorMessage(reason));
      });
  }, [loadedOp, operations, searchedOp]);

  useEffect(() => {
    const rows = operations.data?.items ?? [];
    if (!rows.length) return;
    const selectedStillExists = routeSelection?.op === loadedOp
      && rows.some((item) => routeStepKey(item) === routeSelection.operationKey);
    // Atualizações SSE substituem `operations.data`. Uma seleção já
    // confirmada pertence ao operador e não pode ser sobrescrita pelo
    // `visual_current` devolvido no novo snapshot.
    if (selectedStillExists) return;
    const current = rows.findIndex((item) => item.visual_current || item.visual_status === "current");
    const next = current >= 0 ? current : rows.findIndex((item) => item.visual_status !== "done");
    const currentOperation = rows[next];
    const currentName = operationLabel(currentOperation);
    setMessage(
      next < 0
        ? "Roteiro concluído. Etapas finalizadas não podem ser reabertas."
        : currentOperation?.actionable !== false
          ? `OP encontrada. Etapa atual: ${currentName}.`
          : `OP encontrada. Etapa atual: ${currentName}. Ainda não disponível para ${sector}.`,
    );
  }, [loadedOp, operations.data, routeSelection, sector]);

  const routeRows = operations.data?.items ?? [];
  const selectedIndex = routeSelection?.op === loadedOp
    ? routeRows.findIndex((item) => routeStepKey(item) === routeSelection.operationKey)
    : -1;
  const currentIndex = routeRows.findIndex((item) => item.visual_current || item.visual_status === "current");
  const fallbackIndex = currentIndex >= 0 ? currentIndex : routeRows.findIndex((item) => item.visual_status !== "done");
  const operationIndex = selectedIndex >= 0 ? selectedIndex : fallbackIndex;
  const selected = routeRows[operationIndex];
  const selectedCard = useMemo(() => {
    const items = [...(cards.data?.production ?? []), ...(cards.data?.queue ?? []), ...(historyQuery.data?.items ?? [])];
    return items.find((item) => {
      if (String(item.op ?? "").trim() !== loadedOp) return false;
      const selectedId = selected?.id ?? selected?.catalogo_operacao_id;
      const cardId = item.catalogo_operacao_id ?? item.id;
      if (selectedId != null && cardId != null) return selectedId === cardId;
      return String(item.numero_operacao ?? item.operation ?? "").includes(String(selected?.numero_operacao ?? selected?.codigo ?? ""));
    });
  }, [cards.data, historyQuery.data, loadedOp, selected]);
  const selectedKey = selectedCard ? cardKey(selectedCard) : "";
  const context = useMemo<OperationContext>(() => ({
    op: loadedOp,
    operation: selected ? operationLabel(selected) : "",
    resource,
    product: String(selected?.produto_codigo ?? selectedCard?.product ?? ""),
    description: String(selected?.produto_descricao ?? selectedCard?.description ?? ""),
    planned: Number(selected?.quantidade_planejada ?? selectedCard?.qty ?? selected?.quantidade ?? 0),
    registeredGood: Number(selected?.quantidade_boa_registrada ?? selectedCard?.good ?? 0),
    registeredScrap: Number(selected?.quantidade_refugo_registrada ?? selectedCard?.scrap ?? 0),
    attended: Number(selected?.quantidade_atendida ?? selectedCard?.attended ?? 0),
    balance: Number(selected?.saldo_quantidade ?? selected?.saldo_quantidade_boa ?? selectedCard?.balance ?? 0),
  }), [loadedOp, selected, selectedCard, resource]);
  // Setup é apontamento de estado do posto (tempo de preparação da máquina).
  // Quais setores possuem Setup é decisão do domínio (`SECTORS_WITHOUT_SETUP`):
  // a tela recebe a resposta pronta em `/operator/context` em vez de manter uma
  // segunda lista, que já nascia desatualizada a cada setor novo.
  const showSetup = hasSetup;
  const currentStatus = String(selectedCard?.status ?? "");
  const startAction = currentStatus === "Parada"
    ? "Retomar"
    : currentStatus === "Setup"
      ? "Retornar"
      : selectedCard?.rework_return
        ? "Retrabalho"
        : "Início";
  const startLabel = selectedCard?.rework_return
    ? "Iniciar retrabalho"
    : startAction === "Início" ? "Iniciar" : startAction;
  const canPoint = isSelectable(selected);
  const activeCard = (cards.data?.production ?? []).find((item) =>
    ["Em processo", "Parada", "Setup", "Retrabalho"].includes(String(item.status ?? "")),
  );
  // Wave 5: quem decide se Finalizar pode ser oferecido é o backend. A tela
  // apenas lê `pode_finalizar` e explica o motivo com a frase que veio de lá.
  const firstPiece: FirstPieceGate | undefined = selected?.primeira_peca;
  // Wave 6B: o portão Setup/Qualidade é do **Finalizar**. Quem diz isso é o
  // backend (`exige_gate_primeira_peca` e o código da pendência); a tela não
  // conhece a lista de setores nem recalcula o portão. Iniciar é livre.
  const gateRequired = Boolean(
    selected?.exige_gate_primeira_peca
      ?? (firstPiece?.gate_estruturado && !firstPiece?.liberado),
  );
  // O Finalizar continua clicável com o portão pendente: o clique é que
  // entrega a orientação ao operador, em vez de um botão morto.
  const canFinish = canPoint && ((selected?.pode_finalizar ?? true) || gateRequired);
  const canStart = canPoint && currentStatus !== "Retrabalho" && !firstPiece?.bloqueio_ativo;
  const stopContext = activeCard ? {
    op: String(activeCard.op ?? ""),
    operation: String(activeCard.operation ?? activeCard.numero_operacao ?? ""),
    resource,
    product: String(activeCard.product ?? ""),
    description: String(activeCard.description ?? ""),
    planned: Number(activeCard.qty ?? 0),
    registeredGood: Number(activeCard.good ?? 0),
    registeredScrap: Number(activeCard.scrap ?? 0),
    attended: Number(activeCard.attended ?? 0),
    balance: Number(activeCard.balance ?? 0),
  } : context;

  function applyRouteStep(operationKey: string) {
    const item = routeRows.find((row) => routeStepKey(row) === operationKey);
    if (!item) return;
    setRouteSelection({ op: loadedOp, operationKey });
    setMessage(
      needsRouteConfirmation(item)
        ? `Operação ${operationLabel(item)} selecionada. Ela não é a etapa atual da OP.`
        : `Etapa atual selecionada: ${operationLabel(item)}.`,
    );
  }

  // Selecionar um card nunca registra evento produtivo. Quando a etapa não é a
  // atual, o operador precisa confirmar antes mesmo da seleção.
  function selectRouteStep(index: number) {
    const item = routeRows[index];
    if (!isSelectable(item)) return;
    if (index === operationIndex) return;
    const operationKey = routeStepKey(item);
    if (!operationKey) return;
    if (needsRouteConfirmation(item)) {
      setDialog({ kind: "route", operationKey });
      return;
    }
    applyRouteStep(operationKey);
  }

  function loadOperations(event?: FormEvent) {
    event?.preventDefault();
    const normalized = op.trim().toUpperCase();
    if (!normalized) {
      setMessage("Informe o código da OP.");
      return;
    }
    if (normalized !== loadedOp) setRouteSelection(null);
    setLoadedOp(normalized);
  }

  function selectCard(item: OperatorCard) {
    const cardOp = String(item.op ?? "").trim();
    if (!cardOp) return;
    setOp(cardOp);
    setLoadedOp(cardOp);
    const operationId = item.catalogo_operacao_id ?? item.id;
    setRouteSelection(operationId == null ? null : { op: cardOp, operationKey: `id:${String(operationId)}` });
    setMessage(`OP ${cardOp} selecionada no card.`);
  }

  /** Abre o portão Setup/Qualidade: o popup é a entrada do botão Iniciar. */
  function openGate() {
    if (!loadedOp || !selected) {
      setMessage("Carregue e selecione uma operação antes de iniciar.");
      return;
    }
    const operationId = selected.id ?? selected.catalogo_operacao_id;
    setGateOperationKey(
      `/api/v1/operator/first-piece?op=${encodeURIComponent(loadedOp)}`
      + `&resource=${encodeURIComponent(resource)}`
      + (operationId == null ? "" : `&operation_id=${encodeURIComponent(String(operationId))}`),
    );
    setDialog({ kind: "gate" });
  }

  function closeGate() {
    // Fechar ou cancelar o popup nunca libera a OP: nenhuma ação é enviada.
    setDialog(null);
    setGateOperationKey("");
  }

  function finishAppointment() {
    if (gateRequired) {
      // A primeira peça ainda não foi aprovada. A frase é a do backend, e a
      // etapa fica fixada para que o próximo snapshot do roteiro não apague a
      // orientação que o operador acabou de receber.
      const operationKey = routeStepKey(selected);
      if (operationKey) setRouteSelection({ op: loadedOp, operationKey });
      setMessage(firstPiece?.message ?? "Aponte o Setup desta operação para conferir a primeira peça antes de finalizar.");
      return;
    }
    setDialog({ kind: "finish" });
  }

  /**
   * Setup do posto. Ele continua sendo o apontamento de estado do tempo de
   * preparação da máquina; quando a primeira peça ainda não foi aprovada, é
   * esse mesmo clique que abre o checklist para o operador conferi-la.
   */
  async function setupAppointment() {
    if (!gateRequired) {
      setDialog({ kind: "confirm", action: "Setup" });
      return;
    }
    await execute("Setup");
    openGate();
  }

  /**
   * Portão da primeira peça: checklist medido, liberação por crachá e a
   * declaração da peça produzida. A decisão é toda do backend.
   */
  async function executeFirstPiece(
    action: "produzida" | "inspecionar" | "autorizar" | "checklist",
    extra: Record<string, unknown> = {},
  ) {
    if (!loadedOp || !selected) {
      setMessage("Carregue e selecione uma operação antes de registrar a primeira peça.");
      return;
    }
    setSubmitting(true);
    try {
      const response = await postOperator<{ message: string; data?: { liberado?: boolean } }>(
        "/api/v1/operator/first-piece",
        {
          action,
          resource,
          op: loadedOp,
          operation_id: selected.id ?? selected.catalogo_operacao_id,
          operation_number: selected.numero_operacao ?? selected.codigo,
          ...extra,
        },
      );
      setMessage(response.message);
      // A etapa que passou pelo portão é a escolha do operador: fixá-la evita
      // que o próximo snapshot do roteiro apague o retorno do lote liberado.
      const operationKey = routeStepKey(selected);
      if (operationKey) setRouteSelection({ op: loadedOp, operationKey });
      operations.reload();
      cards.reload();
      if (response.data?.liberado) {
        // Lote liberado: o popup fecha e a OP volta sozinha para a produção —
        // o operador não precisa clicar em Iniciar de novo. A transição é a
        // mesma do posto (`Retornar` do Setup), registrada como sempre.
        closeGate();
        await execute(startAction);
        return;
      }
      gate.reload();
    } catch (reason) {
      setMessage(operatorErrorMessage(reason));
    } finally {
      setSubmitting(false);
    }
  }

  /** Cadastro das cotas do produto pelo editor que já existe na Qualidade. */
  async function saveChecklistTemplate(produto: string, cotas: DraftDimension[]) {
    setSubmitting(true);
    try {
      await postOperator("/api/v1/quality/templates", {
        produto,
        cotas: cotas.map((item, index) => ({
          sequencia: index + 1,
          descricao: item.descricao.trim() || null,
          padrao: item.padrao.trim(),
          unidade: "mm",
        })),
      });
      setMessage("Cotas padrão salvas para este produto.");
      gate.reload();
    } catch (reason) {
      setMessage(operatorErrorMessage(reason));
    } finally {
      setSubmitting(false);
    }
  }

  async function execute(action: string, extra: Record<string, unknown> = {}) {
    const appointmentForStop = action === "Parada" ? activeCard : undefined;
    const stopWithoutOp = action === "Parada" && !appointmentForStop;
    if (!stopWithoutOp && (!loadedOp || !selected)) {
      if (!appointmentForStop) {
        setMessage("Carregue e selecione uma operação antes de apontar.");
        return;
      }
    }
    setSubmitting(true);
    try {
      const response = await postOperator<{ message: string; data?: Record<string, unknown> }>("/api/v1/operator/actions", {
        action,
        resource,
        op: stopWithoutOp ? null : String(appointmentForStop?.op ?? loadedOp),
        operation_id: stopWithoutOp ? null : appointmentForStop?.catalogo_operacao_id ?? selected?.id ?? selected?.catalogo_operacao_id,
        operation_number: stopWithoutOp ? null : appointmentForStop?.numero_operacao ?? appointmentForStop?.operation ?? selected?.numero_operacao ?? selected?.codigo,
        ...extra,
      });
      setMessage(response.message);
      setDialog(null);
      cards.reload();
      historyQuery.reload();
      operations.reload();
      if (action === "Finalizado" && !response.data?.finalizacao_parcial) {
        setOp("");
        setLoadedOp("");
        setRouteSelection(null);
      }
    } catch (reason) {
      if (reason instanceof ApiError && ["confirmacao_recurso_obrigatoria", "confirmacao_etapa_anterior_obrigatoria"].includes(reason.code)) {
        setDialog({ kind: "authorization", action, code: reason.code, details: reason.details as Record<string, unknown> | undefined });
      } else if (reason instanceof ApiError && GATE_CODES.includes(reason.code)) {
        // O backend é a autoridade do portão. A recusa da finalização já é a
        // orientação ao operador — quem abre o checklist é o botão Setup.
        setMessage(reason.message);
      } else {
        setMessage(operatorErrorMessage(reason));
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="operator-workbench">
      <div className="operator-workbench__top">
        <div className="operator-workbench__main">
      <form className="operator-op-form" onSubmit={loadOperations}>
        <label>Código da OP<input value={op} onChange={(event) => setOp(event.target.value)} placeholder="Digite ou escaneie a OP" autoFocus /></label>
        <button type="submit">Carregar roteiro</button>
      </form>
      {(operations.data?.items?.length ?? 0) > 0 ? (
        <ol className="operator-route" aria-label="Roteiro completo da OP">
          {(operations.data?.items ?? []).map((item, index) => {
            const selectable = isSelectable(item);
            const chosen = index === operationIndex;
            return (
              <li
                key={`route-${item.id ?? item.numero_operacao}-${index}`}
                className={`operator-route__item operator-route__item--${item.visual_status ?? "pending"}${chosen ? " operator-route__item--selected" : ""}`}
                aria-current={item.visual_current ? "step" : undefined}
              >
                <button
                  type="button"
                  aria-pressed={chosen}
                  aria-label={`${operationLabel(item)} — ${routeStateLabel(item)}`}
                  disabled={!selectable}
                  title={`${operationLabel(item)} — ${routeStateLabel(item)}`}
                  onClick={() => selectRouteStep(index)}
                >
                  <strong>{operationLabel(item)}</strong>
                  <span>{routeStateLabel(item)}</span>
                </button>
              </li>
            );
          })}
        </ol>
      ) : null}
      {operations.loading && loadedOp ? <LoadingState label="Carregando roteiro…" /> : null}
      {remoteSearch === "searching" ? <LoadingState label="Buscando OP no TOTVS..." /> : null}
      {operations.error ? <ErrorState error={operations.error} onRetry={operations.reload} /> : null}
      {/* Wave 6B — a primeira peça deixou de ser card e virou o popup do
          Iniciar. O Setup continua sendo botão: ele aponta o tempo de
          preparação da máquina, que é quando a primeira peça é fabricada. */}
      <div className="operator-actions" aria-label="Ações operacionais">
        <button type="button" className="operator-action operator-action--start" disabled={submitting || !canStart} onClick={() => void execute(startAction)}><img src={assets.operator.actions.start} alt="" /><span>{startLabel}</span></button>
        <button type="button" className="operator-action operator-action--stop" disabled={submitting || activeCard?.status === "Parada"} onClick={() => setDialog({ kind: "stop" })}><img src={assets.operator.actions.stop} alt="" /><span>Parada</span></button>
        <button type="button" className="operator-action operator-action--finish" disabled={submitting || !canFinish} title={canFinish ? undefined : firstPiece?.message} onClick={finishAppointment}><img src={assets.operator.actions.finish} alt="" /><span>Finalizar</span></button>
        {showSetup ? <button type="button" className="operator-action operator-action--setup" disabled={submitting || !canPoint} onClick={() => void setupAppointment()}><img src={assets.operator.actions.setup} alt="" /><span>Setup</span></button> : null}
        <button type="button" className="operator-action operator-action--rework" disabled={submitting || !canPoint} onClick={() => setDialog({ kind: "confirm", action: "Retrabalho" })}><img src={assets.operator.actions.rework} alt="" /><span>Retrabalho</span></button>
      </div>
      {canPoint && gateRequired ? (
        <p className="operator-help">
          {firstPiece?.bloqueio_ativo
            ? firstPiece.message
            : "Aponte o Setup para conferir a primeira peça: o lote só é liberado — e a operação só pode ser finalizada — depois que ela for aprovada."}
        </p>
      ) : null}
        </div>
        <aside className="operator-workbench__aside" aria-label="Contexto da peça">
          <DrawingCard
            op={loadedOp}
            loading={drawing.loading}
            data={drawing.data}
            onOpen={() => setDialog({ kind: "drawing" })}
          />
        </aside>
      </div>
      <p className="operator-notice" role="status">{message}</p>
      {cards.loading && !cards.data ? <LoadingState label="Atualizando produção e fila…" /> : cards.error ? <ErrorState error={cards.error} onRetry={cards.reload} /> : (
        <div className="operator-card-columns">
          <CardSection title="Produção" items={cards.data?.production ?? []} emptyTitle="Nenhuma OP em produção" selectedKey={selectedKey} onSelect={selectCard} onMore={() => setDialog({ kind: "list", source: "production" })} />
          <CardSection title="Fila de Ordem" items={cards.data?.queue ?? []} emptyTitle="Fila vazia" selectedKey={selectedKey} onSelect={selectCard} onMore={() => setDialog({ kind: "list", source: "queue" })} />
          <CardSection className="operator-card-section--history" title="Histórico" items={historyQuery.data?.items ?? []} emptyTitle={historyQuery.loading ? "Carregando histórico" : "Sem apontamentos recentes"} selectedKey={selectedKey} onSelect={selectCard} onMore={() => setDialog({ kind: "list", source: "history" })} />
        </div>
      )}

      {dialog?.kind === "route" ? (
        <RouteStepDialog
          op={loadedOp}
          current={(operations.data?.items ?? []).find((item) => item.visual_current)}
          target={(operations.data?.items ?? []).find((item) => routeStepKey(item) === dialog.operationKey)}
          onCancel={() => setDialog(null)}
          onConfirm={() => { applyRouteStep(dialog.operationKey); setDialog(null); }}
        />
      ) : null}
      {dialog?.kind === "stop" ? <StopDialog context={stopContext} reasons={reasons.data?.items ?? []} onCancel={() => setDialog(null)} onConfirm={(code, comment) => void execute("Parada", { stop_reason_code: code, comment })} /> : null}
      {dialog?.kind === "finish" ? <FinishDialog context={context} operators={operators.data?.items ?? []} onCancel={() => setDialog(null)} onConfirm={(good, scrap, badges, scrapBadge) => void execute("Finalizado", { good, scrap, badges, scrap_authorization_badge: scrapBadge || null })} /> : null}
      {dialog?.kind === "confirm" ? <OperatorDialog title={`Confirmar ${dialog.action}`} context={<ContextLine {...context} />} onCancel={() => setDialog(null)}><p>Confirme o registro de {dialog.action.toLowerCase()} para a operação selecionada.</p><div className="operator-dialog__actions"><button type="button" onClick={() => setDialog(null)}>Cancelar</button><button type="button" className="button button--primary" onClick={() => void execute(dialog.action)}>Confirmar</button></div></OperatorDialog> : null}
      {dialog?.kind === "authorization" ? <AuthorizationDialog context={context} details={dialog.details} onCancel={() => setDialog(null)} onConfirm={(badge) => void execute(dialog.action, { badges: [badge], confirm_resource_divergence: dialog.code === "confirmacao_recurso_obrigatoria" || Boolean(dialog.details?.confirmar_recurso_divergente), confirm_previous_step: dialog.code === "confirmacao_etapa_anterior_obrigatoria" })} /> : null}
      {dialog?.kind === "list" ? <CardListDialog title={{ production: "Produção", queue: "Fila de Ordem", history: "Histórico" }[dialog.source]} items={dialog.source === "history" ? historyQuery.data?.items ?? [] : cards.data?.[dialog.source] ?? []} hasMore={dialog.source === "history" && Boolean(historyQuery.data?.has_more)} onCancel={() => setDialog(null)} onSelect={(item) => { selectCard(item); setDialog(null); }} /> : null}
      {dialog?.kind === "gate" ? (
        <SetupQualityDialog
          context={context}
          state={gate.data}
          loading={gate.loading && !gate.data}
          busy={submitting}
          onCancel={closeGate}
          onSubmit={(payload) => void executeFirstPiece("checklist", payload)}
          onRelease={(badge, note) => void executeFirstPiece("autorizar", { badge, note })}
          onSaveTemplate={(produto, cotas) => void saveChecklistTemplate(produto, cotas)}
        />
      ) : null}
      {dialog?.kind === "drawing" ? <DrawingDialog op={loadedOp} data={drawing.data} onCancel={() => setDialog(null)} /> : null}
    </section>
  );
}

/**
 * Popup Setup/Qualidade — a entrada do botão Iniciar na Caldeiraria (Wave 6B).
 *
 * O popup tem três apresentações possíveis, escolhidas pelo estado que o
 * backend enviou:
 *
 * 1. **bloqueio ativo** — a primeira peça entrou em retrabalho e só o crachá do
 *    responsável designado libera o fluxo;
 * 2. **produto sem cotas** — o cadastro usa o mesmo editor da Qualidade;
 * 3. **checklist** — Setup confirmado e a medida de cada cota.
 *
 * Nenhuma regra é decidida aqui: os limites chegam calculados e o status
 * gravado é sempre o que o backend calcula na submissão. Fechar o popup não
 * envia nada e, por isso, nunca libera a OP.
 */
function SetupQualityDialog({
  context,
  state,
  loading,
  busy,
  onCancel,
  onSubmit,
  onRelease,
  onSaveTemplate,
}: {
  context: OperationContext;
  state?: FirstPieceState | null;
  loading: boolean;
  busy: boolean;
  onCancel: () => void;
  onSubmit: (payload: Record<string, unknown>) => void;
  onRelease: (badge: string, note: string) => void;
  onSaveTemplate: (produto: string, cotas: DraftDimension[]) => void;
}) {
  const [measures, setMeasures] = useState<Record<number, { medida: string; status: string }>>({});
  const [destination, setDestination] = useState("RETRABALHO");
  const [note, setNote] = useState("");
  const [badge, setBadge] = useState("");
  const [drafts, setDrafts] = useState<DraftDimension[]>([
    { sequencia: 1, descricao: "", padrao: "" },
  ]);

  const cotas: QualityDimension[] = state?.checklist?.template?.cotas ?? [];
  const setupPendente = Boolean(state?.setup_obrigatorio && !state?.setup_registrado);
  const statusDaCota = (cota: QualityDimension) => {
    const atual = measures[cota.sequencia];
    if (!atual?.medida.trim()) return "";
    return cota.conformidade_automatica ? previewStatus(cota, atual.medida) : atual.status;
  };
  const preenchidas = cotas.length > 0 && cotas.every((cota) => Boolean(statusDaCota(cota)));
  const reprovada = cotas.some((cota) => statusDaCota(cota) === "NAO_CONFORME");

  function submit() {
    onSubmit({
      note: note.trim() || null,
      destination: reprovada ? destination : null,
      badge: reprovada && destination === "REFUGO" ? badge.trim() : null,
      measures: cotas.map((cota) => ({
        sequencia: cota.sequencia,
        medida: measures[cota.sequencia]?.medida.trim() ?? "",
        status: cota.conformidade_automatica
          ? null
          : measures[cota.sequencia]?.status || null,
      })),
    });
  }

  return (
    <OperatorDialog title="Setup e Qualidade" size="wide" context={<ContextLine {...context} />} onCancel={onCancel}>
      {loading ? <LoadingState label="Carregando o Setup/Qualidade…" /> : null}
      {!loading && state?.bloqueio_ativo ? (
        <>
          <p className="operator-help">{state.message}</p>
          <p className="operator-help">O responsável precisa estar no posto e informar o próprio crachá. Não existe login para ele: a autorização fica registrada com OP, recurso, operador, horário e decisão.</p>
          <label>Crachá do responsável<input value={badge} onChange={(event) => setBadge(event.target.value)} autoFocus /></label>
          <label>Observação<textarea value={note} onChange={(event) => setNote(event.target.value)} rows={2} placeholder="O que foi decidido no posto" /></label>
          <div className="operator-dialog__actions">
            <button type="button" onClick={onCancel}>Cancelar</button>
            <button type="button" className="button button--primary" disabled={busy || !badge.trim()} onClick={() => onRelease(badge.trim(), note)}>Autorizar e liberar</button>
          </div>
        </>
      ) : null}
      {!loading && !state?.bloqueio_ativo && state?.checklist?.configuravel ? (
        <>
          <TemplateEditor
            drafts={drafts}
            saving={busy}
            onChange={setDrafts}
            onSave={() => onSaveTemplate(String(state.checklist?.produto ?? context.product), drafts)}
          />
          <div className="operator-dialog__actions">
            <button type="button" onClick={onCancel}>Cancelar</button>
          </div>
        </>
      ) : null}
      {!loading && !state?.bloqueio_ativo && !state?.checklist?.configuravel && cotas.length ? (
        <>
          <p className="operator-help">O lote só é liberado depois que a primeira peça for aprovada. Informe a medida de cada cota: o sistema compara com a faixa do padrão cadastrado e decide a conformidade.</p>
          {setupPendente ? (
            <p className="operator-gate-setup" role="status">
              Aponte o Setup desta operação pelo botão <strong>Setup</strong> do posto: é ele que registra a preparação da máquina em que a primeira peça é fabricada.
            </p>
          ) : null}
          <div className="operator-gate-checklist">
            {cotas.map((cota) => {
              const atual = measures[cota.sequencia] ?? { medida: "", status: "" };
              const faixa = rangeLabel(cota);
              return (
                <fieldset key={cota.sequencia}>
                  <legend>Cota {cota.sequencia}{cota.descricao ? ` — ${cota.descricao}` : ""}</legend>
                  <div className="operator-gate-checklist__standard">
                    <span><small>Padrão</small><strong>{cota.padrao}</strong></span>
                    {faixa ? <span><small>Faixa aceita</small><strong>{faixa}</strong></span> : null}
                  </div>
                  <label>
                    Medida ({cota.unidade ?? "mm"})
                    <input
                      inputMode="decimal"
                      aria-label={`Medida da cota ${cota.sequencia}`}
                      value={atual.medida}
                      onChange={(event) => setMeasures((current) => ({
                        ...current,
                        [cota.sequencia]: { ...atual, medida: event.target.value },
                      }))}
                    />
                  </label>
                  {cota.conformidade_automatica ? null : (
                    <label>
                      Situação
                      <select
                        aria-label={`Situação da cota ${cota.sequencia}`}
                        value={atual.status}
                        onChange={(event) => setMeasures((current) => ({
                          ...current,
                          [cota.sequencia]: { ...atual, status: event.target.value },
                        }))}
                      >
                        <option value="">Selecione</option>
                        <option value="CONFORME">Conforme</option>
                        <option value="NAO_CONFORME">Não conforme</option>
                      </select>
                    </label>
                  )}
                </fieldset>
              );
            })}
          </div>
          {reprovada ? (
            <label>
              Destino da peça reprovada
              <select value={destination} onChange={(event) => setDestination(event.target.value)}>
                <option value="RETRABALHO">Retrabalho — bloqueia a OP até o responsável</option>
                <option value="REFUGO">Refugo — consome o saldo e exige outra peça</option>
              </select>
            </label>
          ) : null}
          {reprovada && destination === "REFUGO" ? (
            <label>
              Crachá do responsável que autoriza o refugo
              <input value={badge} onChange={(event) => setBadge(event.target.value)} />
            </label>
          ) : null}
          <label>Observação<textarea value={note} onChange={(event) => setNote(event.target.value)} rows={2} placeholder="O que foi verificado no posto" /></label>
          <div className="operator-dialog__actions">
            <button type="button" onClick={onCancel}>Cancelar</button>
            <button
              type="button"
              className="button button--primary"
              disabled={
                busy
                || !preenchidas
                || setupPendente
                || (reprovada && destination === "REFUGO" && !badge.trim())
              }
              onClick={submit}
            >
              Liberar lote
            </button>
          </div>
        </>
      ) : null}
      {!loading && !state?.bloqueio_ativo && !state?.checklist ? (
        <>
          <p className="operator-help">Esta operação não possui o Setup/Qualidade estruturado.</p>
          <div className="operator-dialog__actions"><button type="button" onClick={onCancel}>Fechar</button></div>
        </>
      ) : null}
    </OperatorDialog>
  );
}

/** Card discreto do desenho. Sem PDF, o estado vazio não expõe erro técnico. */
function DrawingCard({ op, loading, data, onOpen }: { op: string; loading: boolean; data?: OperatorDrawing | null; onOpen: () => void }) {
  const disponivel = Boolean(data?.available);
  return (
    <section className="operator-side-card operator-drawing-card" aria-label="Desenho da peça">
      <header><h2>PDF</h2></header>
      {!op ? (
        <p>Informe a OP para ver o desenho.</p>
      ) : loading && !data ? (
        <p>Procurando o desenho…</p>
      ) : disponivel ? (
        <>
          <strong>Desenho disponível</strong>
          <small>{data?.filename}</small>
          {data?.modified_at ? <small>Atualizado em {formatDateTime(data.modified_at)}</small> : null}
          {(data?.candidate_count ?? 0) > 1 ? <small>{data?.candidate_count} arquivos da peça; exibindo o mais recente.</small> : null}
          <div className="operator-side-card__actions">
            <button type="button" className="button button--primary" onClick={onOpen}>Abrir visualização</button>
          </div>
        </>
      ) : (
        <p>{data?.message ?? "Nenhum desenho disponível para esta peça."}</p>
      )}
    </section>
  );
}

function DrawingDialog({ op, data, onCancel }: { op: string; data?: OperatorDrawing | null; onCancel: () => void }) {
  return (
    <OperatorDialog title={`Desenho — ${data?.produto || op || "peça"}`} size="wide" onCancel={onCancel}>
      <div className="operator-drawing-viewer">
        {/* O visualizador é o do próprio navegador: zoom, navegação e busca
            já vêm dele, sem instalar leitor e sem baixar arquivo. */}
        <object data={`/api/v1/operator/drawings/file?op=${encodeURIComponent(op)}#zoom=page-fit`} type="application/pdf" aria-label={`Desenho da peça ${data?.produto ?? ""}`}>
          <p>Não foi possível exibir o desenho nesta tela.</p>
        </object>
      </div>
      <div className="operator-dialog__actions"><button type="button" onClick={onCancel}>Fechar</button></div>
    </OperatorDialog>
  );
}

function RouteStepDialog({ op, current, target, onCancel, onConfirm }: { op: string; current?: OperatorOperation; target?: OperatorOperation; onCancel: () => void; onConfirm: () => void }) {
  const currentName = current ? operationLabel(current) : "não identificada";
  const targetName = target ? operationLabel(target) : "não identificada";
  return (
    <OperatorDialog title="Confirmar operação" size="compact" onCancel={onCancel}>
      <div className="operator-route-confirm">
        <div><small>OP</small><strong>{op || "—"}</strong></div>
        <div><small>Etapa atual da OP</small><strong>{currentName}</strong></div>
        <div><small>Você selecionou</small><strong>{targetName}</strong></div>
      </div>
      <p>Deseja realmente apontar esta operação?</p>
      <div className="operator-dialog__actions">
        <button type="button" onClick={onCancel}>Cancelar</button>
        <button type="button" className="button button--primary" onClick={onConfirm}>Sim, apontar esta operação</button>
      </div>
    </OperatorDialog>
  );
}

function ContextLine({ op, operation, resource }: Pick<OperationContext, "op" | "operation" | "resource">) {
  return <div className="operator-context-line"><span><small>OP</small><strong>{op || "—"}</strong></span><span><small>Operação</small><strong>{operation || "—"}</strong></span><span><small>Recurso</small><strong>{resource}</strong></span></div>;
}

function StopDialog({ context, reasons, onCancel, onConfirm }: { context: OperationContext; reasons: StopReason[]; onCancel: () => void; onConfirm: (code: string, comment: string) => void }) {
  const [code, setCode] = useState("");
  const [comment, setComment] = useState("");
  const selected = reasons.find((item) => item.codigo === code);
  return <OperatorDialog title="Registrar parada" size="wide" context={<ContextLine {...context} />} onCancel={onCancel}><StopReasonFields reasons={reasons} code={code} comment={comment} onCodeChange={setCode} onCommentChange={setComment} /><div className="operator-dialog__actions"><button type="button" onClick={onCancel}>Cancelar</button><button type="button" className="button operator-danger" disabled={!code || Boolean(selected?.requer_comentario && !comment.trim())} onClick={() => onConfirm(code, comment)}>Confirmar parada</button></div></OperatorDialog>;
}

function CardListDialog({ title, items, hasMore, onCancel, onSelect }: { title: string; items: OperatorCard[]; hasMore: boolean; onCancel: () => void; onSelect: (item: OperatorCard) => void }) {
  return <OperatorDialog title={title} size="wide" onCancel={onCancel}>{items.length ? <div className="operator-dialog-card-list">{items.map((item, index) => <OperatorCardView key={`${item.id ?? item.op}-${index}`} item={item} onSelect={onSelect} />)}</div> : <EmptyState title={`Nenhum item em ${title.toLocaleLowerCase("pt-BR")}`} />}{hasMore ? <p className="operator-help">Exibindo os 100 registros mais recentes. Use os filtros dos relatórios para consultas históricas maiores.</p> : null}</OperatorDialog>;
}

function FinishDialog({ context, operators, onCancel, onConfirm }: { context: OperationContext; operators: OperatorBadge[]; onCancel: () => void; onConfirm: (good: number, scrap: number, badges: string[], scrapBadge: string) => void }) {
  const [good, setGood] = useState("");
  const [scrap, setScrap] = useState("0");
  const [badge, setBadge] = useState("");
  const [badges, setBadges] = useState<string[]>([]);
  const [badgeError, setBadgeError] = useState("");
  // Refugo é decisão de responsável: o crachá dele autoriza o descarte, com a
  // mesma regra do retrabalho da primeira peça. Quem valida é o backend.
  const [scrapBadge, setScrapBadge] = useState("");
  const scrapRequiresApproval = Number(scrap || 0) > 0;
  function addBadge() {
    const normalized = badge.trim();
    if (!normalized) return;
    const registered = operators.find((item) => item.cracha === normalized && item.ativo !== false);
    if (!registered) {
      setBadgeError("Crachá não cadastrado ou inativo.");
      return;
    }
    setBadges((current) => current.includes(normalized) ? current : [...current, normalized]);
    setBadge("");
    setBadgeError("");
  }
  return <OperatorDialog title="Finalizar produção" size="wide" context={<ContextLine {...context} />} onCancel={onCancel}>
    <div className="operator-finish-summary">
      <div><small>Produto</small><strong>{context.product || "—"}</strong></div>
      <div><small>Descrição</small><strong>{context.description || "—"}</strong></div>
      <div><small>QTD planejada</small><strong>{context.planned}</strong></div>
      <div><small>Boas já registradas</small><strong>{context.registeredGood}</strong></div>
      <div><small>Refugo já registrado</small><strong>{context.registeredScrap}</strong></div>
      <div><small>Quantidade atendida</small><strong>{context.attended}</strong></div>
      <div><small>Saldo</small><strong>{context.balance}</strong></div>
    </div>
    <div className="operator-quantity-grid"><label>Peças boas<input type="number" min="0" value={good} onChange={(event) => setGood(event.target.value)} /></label><label>Refugo<input type="number" min="0" value={scrap} onChange={(event) => setScrap(event.target.value)} /></label></div>
    <p className="operator-help">O saldo é reduzido por peças boas + refugo. Retrabalho permanece pendente e não atende o planejado.</p>
    {scrapRequiresApproval ? <label>Crachá do responsável que autoriza o refugo<input value={scrapBadge} onChange={(event) => setScrapBadge(event.target.value)} /></label> : null}
    <label>Crachá do operador<div className="operator-badge-entry"><input value={badge} onChange={(event) => setBadge(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); addBadge(); } }} /><button type="button" aria-label="Adicionar operador" onClick={addBadge}>+</button></div></label>
    {badgeError ? <p className="form-error">{badgeError}</p> : null}
    <div className="operator-badge-list" aria-label="Operadores adicionados">
      {badges.length ? badges.map((item) => {
        const operator = operators.find((candidate) => candidate.cracha === item);
        return <div key={item}><span><strong>{operator?.nome ?? item}</strong><small>Crachá {item}</small></span><button type="button" aria-label={`Remover ${operator?.nome ?? item}`} onClick={() => setBadges((current) => current.filter((value) => value !== item))}>×</button></div>;
      }) : <p>Nenhum operador adicionado.</p>}
    </div>
    <div className="operator-dialog__actions"><button type="button" onClick={onCancel}>Cancelar</button><button type="button" className="button button--primary" disabled={!badges.length || Number(good || 0) + Number(scrap || 0) <= 0 || (scrapRequiresApproval && !scrapBadge.trim())} onClick={() => onConfirm(Number(good || 0), Number(scrap || 0), badges, scrapBadge.trim())}>Confirmar finalização</button></div>
  </OperatorDialog>;
}

function AuthorizationDialog({ context, details, onCancel, onConfirm }: { context: OperationContext; details?: Record<string, unknown>; onCancel: () => void; onConfirm: (badge: string) => void }) {
  const [badge, setBadge] = useState("");
  return <OperatorDialog title="Autorizar exceção operacional" context={<ContextLine {...context} />} onCancel={onCancel}>{details?.etapa_atual ? <p className="operator-help">Etapa atual da OP: {String(details.etapa_atual)}.</p> : null}<p>{String(details?.etapa_pendente_operacao ? `Etapa anterior pendente: ${details.etapa_pendente_operacao}.` : details?.recurso_roteiro_codigo ? `Recurso do roteiro: ${details.recurso_roteiro_codigo} (${details.recurso_roteiro_nome ?? "sem nome"}).` : "A execução diverge do roteiro e exige confirmação.")}</p><label>Crachá autorizado<input value={badge} onChange={(event) => setBadge(event.target.value)} autoFocus /></label><div className="operator-dialog__actions"><button type="button" onClick={onCancel}>Cancelar</button><button type="button" className="button button--primary" disabled={!badge.trim()} onClick={() => onConfirm(badge.trim())}>Autorizar e continuar</button></div></OperatorDialog>;
}
