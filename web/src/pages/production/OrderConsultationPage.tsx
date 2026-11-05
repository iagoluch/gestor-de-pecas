import { useMemo, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { api, ApiError } from "../../api/client";
import { AsyncButton } from "../../components/AsyncButton";
import { useConfirm } from "../../components/ConfirmDialog";
import { DataTable } from "../../components/DataTable";
import type { TableColumn } from "../../components/DataTable";
import { EmptyState, LoadingState } from "../../components/DataState";
import { Notice } from "../../components/Notice";
import type { NoticeTone } from "../../components/Notice";
import { OperatorDialog } from "../../components/OperatorDialog";
import { PageFrame } from "../../components/PageFrame";
import { SectionCard } from "../../components/SectionCard";
import { useApiQuery } from "../../hooks/useApiQuery";
import { useDebouncedValue } from "../../hooks/useDebouncedValue";
import type { ChangeAuditEntry } from "../../types/changeAudit";
import { displayName, formatDateTime, formatNumber } from "../../utils/format";
import "../../styles/order-consultation.css";

const API = "/api/v1/order-consultation";
const MIN_SEARCH = 2;
const MIN_TEXT = 3;

/** Contrato de `backend/api/routers/order_consultation.py` / `mes/services/order_route.py`. */
interface OrderSearchItem {
  codigo_op: string;
  produto_codigo: string | null;
  produto_descricao: string | null;
  quantidade: number | null;
  status_pcp: string | null;
}

interface OrderHeader extends OrderSearchItem {
  unidade: string | null;
  filial: string | null;
  data_emissao: string | null;
  data_liberacao: string | null;
  inicio_planejado: string | null;
  fim_planejado: string | null;
  prioridade: string | number | null;
}

interface RouteStep {
  id: number;
  numero_operacao: string | number | null;
  descricao: string | null;
  setor: string | null;
  recurso_codigo: string | null;
  recurso_nome: string | null;
  tempo_padrao: { segundos: number | null; disponivel: boolean; nota: string | null };
  situacao: string;
  origem: "gestor" | "protheus";
  ativo: boolean;
  marco_terminal: boolean;
  inspecao_qualidade: boolean;
}

interface AddOptions {
  after_operations: { id: number; numero_operacao: string | number | null; descricao: string | null }[];
  resources: { codigo: string; nome: string | null; setor: string | null }[];
}

/** Se a OP já passou pelo Gestor (`mes/services/order_route.py::_situacao_no_sistema`). */
interface SystemStatus {
  situacao: "ja_passou" | "no_sistema_sem_apontamento" | "so_protheus";
  apontamentos: number;
  iniciados: number;
  primeira_entrada: string | null;
  ultima_atividade: string | null;
  coletada_em: string | null;
}

interface ProtheusCheck {
  op: string;
  estava_no_gestor: boolean;
  protheus: { status: string; consultado: boolean; message: string };
  system: SystemStatus;
}

interface OrderConsultation {
  system: SystemStatus;
  order: OrderHeader;
  route: RouteStep[];
  history: ChangeAuditEntry[];
  permissions: { can_add_step: boolean };
  add_options: AddOptions | null;
}

const TITLE = "Produção — Consulta de OP";
const SUBTITLE = "Consulta de OPs";
const NA_TEXT = "Tempo padrão não cadastrado no Protheus. A engenharia de manufatura ajusta direto no ERP.";

/** Mensagem humana por `code`; nunca o código técnico. */
const ERROR_MESSAGES: Record<string, string> = {
  route_step_access_denied: "Só o PCP, a engenharia de manufatura e a administração alteram o roteiro de uma OP.",
  route_step_already_pointed: "Esta etapa já tem apontamento e não pode ser desativada.",
  route_step_not_found: "Só etapas adicionadas no Gestor e ainda ativas podem ser desativadas. Etapas do Protheus não são alteradas aqui.",
  route_step_invalid_text: `A descrição e o motivo precisam ter pelo menos ${MIN_TEXT} caracteres.`,
  route_step_resource_not_pointable: "Escolha um recurso em que algum operador aponta.",
  route_step_anchor_not_found: "A operação escolhida não faz parte do roteiro ativo desta OP. Atualize a tela e tente de novo.",
  order_not_found: "OP não encontrada.",
  order_consultation_rate_limited: "Muitas consultas ao Protheus em pouco tempo. Aguarde um minuto e tente de novo.",
  network_error: "Não foi possível acessar o servidor. Tente novamente.",
};

export function orderConsultationErrorMessage(reason: unknown) {
  if (reason instanceof ApiError) return ERROR_MESSAGES[reason.code] ?? "Não foi possível concluir a operação. Tente novamente.";
  return ERROR_MESSAGES.network_error;
}

interface Feedback {
  tone: NoticeTone;
  text: string;
}

const stepLabel = (step: RouteStep) => `${step.numero_operacao ?? "—"}${step.descricao ? ` · ${step.descricao}` : ""}`;

function SystemStatusCard({ system }: { system: SystemStatus }) {
  const when = (value: string | null) => (value ? formatDateTime(value) : "—");
  if (system.situacao === "ja_passou") {
    return (
      <Notice tone="success">
        <strong>Já passou pelo sistema.</strong>{" "}
        {`${system.iniciados} de ${system.apontamentos} apontamento(s) iniciados. Primeira entrada: ${when(system.primeira_entrada)}. Última atividade: ${when(system.ultima_atividade)}. Dados coletados do Protheus em ${when(system.coletada_em)}.`}
      </Notice>
    );
  }
  if (system.situacao === "no_sistema_sem_apontamento") {
    return (
      <Notice tone="stale">
        <strong>Já está no sistema, mas ainda não foi trabalhada.</strong>{" "}
        {`Dados coletados do Protheus em ${when(system.coletada_em)}; nenhum apontamento iniciado.`}
      </Notice>
    );
  }
  return <Notice tone="stale"><strong>Ainda não passou pelo sistema.</strong> Só existe no Protheus.</Notice>;
}

function protheusNotice(check: ProtheusCheck): { tone: NoticeTone; text: string } {
  const { status, message } = check.protheus;
  if (status === "nao_encontrada") return { tone: "stale", text: "OP não encontrada no Protheus e nunca passou pelo sistema." };
  if (status === "sem_roteiro") return { tone: "stale", text: "A OP existe no Protheus, mas sem roteiro utilizável. Ainda não entrou no sistema." };
  if (status === "indisponivel" || status === "timeout") return { tone: "error", text: `${message} Não dá para saber se a OP existe no Protheus.` };
  return {
    tone: "success",
    text: check.estava_no_gestor ? "OP já estava no sistema." : "OP encontrada no Protheus e carregada agora. Ainda não passou pelo sistema.",
  };
}

function StandardTimeCell({ step }: { step: RouteStep }) {
  const time = step.tempo_padrao;
  if (time.disponivel && time.segundos != null) return <>{`${formatNumber(time.segundos, 2)} s`}</>;
  return <span className="order-route__na" title={time.nota ?? NA_TEXT} aria-label={`n/a. ${time.nota ?? NA_TEXT}`}>n/a</span>;
}

function routeColumns(canChange: boolean, onDeactivate: (step: RouteStep) => unknown): TableColumn<RouteStep>[] {
  const muted = (step: RouteStep, content: ReactNode) => (step.ativo ? content : <span className="order-route__muted">{content}</span>);
  return [
    {
      key: "numero",
      label: "Operação",
      sticky: true,
      render: (step) => muted(step, (
        <span className="order-route__operation">
          <strong>{step.numero_operacao ?? "—"}</strong>
          {step.origem === "gestor" ? <span className="status-badge status-badge--warning">Adicionada no Gestor</span> : null}
        </span>
      )),
    },
    { key: "descricao", label: "Descrição", render: (step) => muted(step, step.descricao ?? "—") },
    { key: "setor", label: "Setor", render: (step) => muted(step, displayName(step.setor, "—")) },
    {
      key: "recurso",
      label: "Recurso",
      render: (step) => muted(step, step.recurso_codigo ? (step.recurso_nome ? `${step.recurso_codigo} · ${step.recurso_nome}` : step.recurso_codigo) : "—"),
    },
    { key: "tempo", label: "Tempo padrão", render: (step) => muted(step, <StandardTimeCell step={step} />) },
    { key: "situacao", label: "Situação", render: (step) => muted(step, step.situacao) },
    {
      key: "acoes",
      label: "",
      render: (step) => canChange && step.origem === "gestor" && step.ativo ? (
        <button type="button" className="button" aria-label={`Desativar etapa ${stepLabel(step)}`} onClick={() => void onDeactivate(step)}>Desativar</button>
      ) : null,
    },
  ];
}

function historyColumns(): TableColumn<ChangeAuditEntry>[] {
  const field = (entry: ChangeAuditEntry, key: string) => (entry.depois?.[key] ?? entry.antes?.[key]) as string | number | null | undefined;
  const action = (entry: ChangeAuditEntry) => {
    if (entry.acao === "criar") return "Adicionou etapa";
    if (entry.depois?.ativo === false) return "Desativou etapa";
    return "Alterou etapa";
  };
  return [
    { key: "quando", label: "Quando", render: (entry) => formatDateTime(entry.quando) },
    { key: "quem", label: "Quem", render: (entry) => entry.usuario_nome ?? "—" },
    { key: "acao", label: "Ação", render: action },
    {
      key: "etapa",
      label: "Etapa",
      render: (entry) => `${field(entry, "numero_operacao") ?? "—"}${field(entry, "descricao_operacao") ? ` · ${field(entry, "descricao_operacao")}` : ""}`,
    },
    { key: "motivo", label: "Motivo", render: (entry) => String(entry.depois?.motivo ?? "—") },
  ];
}

function OrderSummary({ order }: { order: OrderHeader }) {
  const item = (label: string, value: string) => (
    <div className="order-consult__field">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
  return (
    <dl className="order-consult__header">
      {item("OP", order.codigo_op)}
      {item("Produto", order.produto_codigo ?? "—")}
      {item("Descrição", order.produto_descricao ?? "—")}
      {item("Quantidade", `${formatNumber(order.quantidade)}${order.unidade ? ` ${order.unidade}` : ""}`)}
      {item("Status", displayName(order.status_pcp))}
      {item("Emissão", formatDateTime(order.data_emissao))}
      {item("Liberação", formatDateTime(order.data_liberacao))}
      {item("Início planejado", formatDateTime(order.inicio_planejado))}
      {item("Fim planejado", formatDateTime(order.fim_planejado))}
    </dl>
  );
}

function AddStepDialog({ codigoOp, options, onClose, onAdded }: { codigoOp: string; options: AddOptions; onClose: () => void; onAdded: () => void }) {
  const sectors = useMemo(() => Array.from(new Set(options.resources.map((resource) => resource.setor).filter((setor): setor is string => Boolean(setor)))).sort(), [options.resources]);
  const [after, setAfter] = useState(String(options.after_operations.at(-1)?.id ?? ""));
  const [sector, setSector] = useState("");
  const [resource, setResource] = useState("");
  const [description, setDescription] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const resources = options.resources.filter((item) => !sector || item.setor === sector);

  async function submit() {
    if (!resource) return setError("Escolha o recurso da etapa.");
    if (description.trim().length < MIN_TEXT || reason.trim().length < MIN_TEXT) return setError(ERROR_MESSAGES.route_step_invalid_text);
    setError(null);
    try {
      await api.post(`${API}/${encodeURIComponent(codigoOp)}/steps`, {
        after_operation_id: after ? Number(after) : null,
        description: description.trim(),
        resource_code: resource,
        reason: reason.trim(),
      });
    } catch (failure) {
      return setError(orderConsultationErrorMessage(failure));
    }
    onAdded();
  }

  return (
    <OperatorDialog title="Adicionar etapa ao roteiro" size="standard" onCancel={onClose}
      context="A etapa vale só no Gestor: o operador aponta nela como em qualquer operação, mas ela não vai ao Protheus.">
      <form className="order-consult__form" onSubmit={(event: FormEvent) => event.preventDefault()}>
        <label htmlFor="route-after">
          Depois da operação
          <select id="route-after" value={after} onChange={(event) => setAfter(event.target.value)}>
            {options.after_operations.map((operation) => (
              <option key={operation.id} value={operation.id}>{`${operation.numero_operacao ?? "—"}${operation.descricao ? ` · ${operation.descricao}` : ""}`}</option>
            ))}
          </select>
        </label>
        <label htmlFor="route-sector">
          Setor
          <select id="route-sector" value={sector} onChange={(event) => { setSector(event.target.value); setResource(""); }}>
            <option value="">Todos os setores</option>
            {sectors.map((name) => <option key={name} value={name}>{displayName(name)}</option>)}
          </select>
        </label>
        <label htmlFor="route-resource">
          Recurso
          <select id="route-resource" value={resource} onChange={(event) => setResource(event.target.value)}>
            <option value="">Escolha o recurso</option>
            {resources.map((item) => <option key={item.codigo} value={item.codigo}>{item.nome ? `${item.codigo} · ${item.nome}` : item.codigo}</option>)}
          </select>
        </label>
        <label htmlFor="route-description">
          Descrição da etapa
          <input id="route-description" value={description} maxLength={120} onChange={(event) => setDescription(event.target.value)} />
        </label>
        <label htmlFor="route-reason">
          Motivo
          <textarea id="route-reason" value={reason} maxLength={500} rows={3} onChange={(event) => setReason(event.target.value)} />
        </label>
        {error ? <p className="field-error" role="alert">{error}</p> : null}
        <div className="operator-dialog__actions">
          <button type="button" onClick={onClose}>Cancelar</button>
          <AsyncButton className="button button--primary" pendingLabel="Salvando…" onClick={() => submit()}>Adicionar etapa</AsyncButton>
        </div>
      </form>
    </OperatorDialog>
  );
}

export function OrderConsultationPage() {
  const [search, setSearch] = useState("");
  const [suggestionsOpen, setSuggestionsOpen] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [confirm, confirmDialog] = useConfirm();
  const term = useDebouncedValue(search.trim());
  const [checking, setChecking] = useState(false);

  const suggestionsPath = suggestionsOpen && term.length >= MIN_SEARCH ? `${API}/search?q=${encodeURIComponent(term)}` : null;
  const suggestions = useApiQuery<{ items: OrderSearchItem[]; count: number }>(suggestionsPath, { ignoreLiveTick: true });
  const detail = useApiQuery<OrderConsultation>(selected ? `${API}/${encodeURIComponent(selected)}` : null);

  const choose = (code: string) => {
    setSelected(code);
    setSearch(code);
    setSuggestionsOpen(false);
    setFeedback(null);
  };

  async function checkInProtheus() {
    const code = search.trim();
    setChecking(true);
    try {
      const check = await api.post<ProtheusCheck>(`${API}/${encodeURIComponent(code)}/protheus`, {});
      const found = check.protheus.status === "local" || check.protheus.status === "sincronizada";
      if (found) choose(check.op);
      setFeedback(protheusNotice(check));
      if (!found) setSuggestionsOpen(false);
    } catch (failure) {
      setFeedback({ tone: "error", text: orderConsultationErrorMessage(failure) });
    } finally {
      setChecking(false);
    }
  }

  async function deactivate(step: RouteStep) {
    let reason = "";
    let hint = "";
    for (;;) {
      const confirmed = await confirm({
        title: "Desativar etapa do roteiro",
        confirmLabel: "Desativar etapa",
        tone: "danger",
        message: (
          <>
            <p>{`A etapa ${stepLabel(step)} deixa de valer nesta OP. O registro fica no histórico; nada é apagado.`}</p>
            <label className="order-consult__reason">
              Motivo
              <textarea rows={3} maxLength={500} defaultValue={reason} onChange={(event) => { reason = event.target.value; }} />
            </label>
            {hint ? <p className="field-error" role="alert">{hint}</p> : null}
          </>
        ),
      });
      if (!confirmed) return;
      if (reason.trim().length >= MIN_TEXT) break;
      hint = `Informe o motivo (pelo menos ${MIN_TEXT} caracteres).`;
    }
    try {
      await api.post(`${API}/${encodeURIComponent(selected ?? "")}/steps/${step.id}/deactivate`, { reason: reason.trim() });
      setFeedback({ tone: "success", text: `Etapa ${stepLabel(step)} desativada.` });
      detail.reload();
    } catch (failure) {
      setFeedback({ tone: "error", text: orderConsultationErrorMessage(failure) });
    }
  }

  const data = detail.data;
  const canChange = Boolean(data?.permissions.can_add_step);
  const columns = routeColumns(canChange, deactivate);
  const hasNa = Boolean(data?.route.some((step) => !step.tempo_padrao.disponivel));
  const suggestionItems = suggestions.data?.items ?? [];

  return (
    <PageFrame sectionId="production" title={TITLE} subtitle={SUBTITLE} filters={false}>
      <div className="order-consult__search">
        <label htmlFor="order-search">
          Buscar OP
          <input
            id="order-search"
            type="search"
            autoComplete="off"
            value={search}
            placeholder="Código da OP, produto ou descrição"
            onChange={(event) => { setSearch(event.target.value); setSuggestionsOpen(true); }}
          />
        </label>
        {suggestionsPath ? (
          <div className="order-consult__suggestions" role="listbox" aria-label="OPs encontradas">
            {suggestions.loading && !suggestions.data ? <LoadingState label="Buscando…" /> : null}
            {suggestions.error ? <p className="field-error" role="alert">{orderConsultationErrorMessage(suggestions.error)}</p> : null}
            {suggestions.data && !suggestionItems.length ? (
              <p className="order-consult__empty">
                Nenhuma OP no sistema para essa busca.{" "}
                <button type="button" disabled={checking} onClick={checkInProtheus}>
                  {checking ? "Consultando o Protheus…" : `Consultar "${term}" no Protheus`}
                </button>
              </p>
            ) : null}
            {suggestionItems.map((item) => (
              <button key={item.codigo_op} type="button" role="option" aria-selected={item.codigo_op === selected} onClick={() => choose(item.codigo_op)}>
                <strong>{item.codigo_op}</strong>
                <span>{[item.produto_codigo, item.produto_descricao].filter(Boolean).join(" · ")}</span>
              </button>
            ))}
          </div>
        ) : null}
      </div>

      {feedback ? <Notice tone={feedback.tone}>{feedback.text}</Notice> : null}

      {!selected ? <EmptyState title="Nenhuma OP escolhida" detail={`Digite pelo menos ${MIN_SEARCH} caracteres do código, do produto ou da descrição e escolha uma OP da lista.`} /> : null}
      {selected && detail.loading && !data ? <LoadingState /> : null}
      {selected && detail.error && !data ? (
        <Notice tone="error">
          {orderConsultationErrorMessage(detail.error)}{" "}
          <button type="button" onClick={detail.reload}>Tentar novamente</button>
        </Notice>
      ) : null}

      {data ? (
        <>
          <SystemStatusCard system={data.system} />
          <SectionCard title={`OP ${data.order.codigo_op}`} className="content-section">
            <OrderSummary order={data.order} />
          </SectionCard>

          <SectionCard
            title="Roteiro"
            className="content-section section-card--table"
            action={canChange && data.add_options ? <button type="button" className="button button--primary" onClick={() => setAdding(true)}>Adicionar etapa</button> : null}
          >
            <DataTable rows={data.route} rowKey={(step) => step.id} columns={columns} emptyTitle="Esta OP não tem roteiro." />
            {hasNa ? <p className="order-route__legend"><strong>n/a:</strong> {NA_TEXT}</p> : null}
          </SectionCard>

          <SectionCard title="Histórico do roteiro" className="content-section section-card--table">
            {data.history.length
              ? <DataTable rows={data.history} rowKey={(entry) => entry.id} columns={historyColumns()} />
              : <EmptyState title="Nenhuma alteração no roteiro" detail="O roteiro está como veio do Protheus." />}
          </SectionCard>
        </>
      ) : null}

      {adding && data?.add_options && selected ? (
        <AddStepDialog
          codigoOp={selected}
          options={data.add_options}
          onClose={() => setAdding(false)}
          onAdded={() => {
            setAdding(false);
            setFeedback({ tone: "success", text: "Etapa adicionada ao roteiro. Ela vale só no Gestor e não vai ao Protheus." });
            detail.reload();
          }}
        />
      ) : null}
      {confirmDialog}
    </PageFrame>
  );
}
