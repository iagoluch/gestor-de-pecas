import { useState } from "react";
import { api, ApiError } from "../../api/client";
import { DataTable } from "../../components/DataTable";
import type { TableColumn } from "../../components/DataTable";
import { LoadingState } from "../../components/DataState";
import { Notice } from "../../components/Notice";
import { PageFrame } from "../../components/PageFrame";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import { useApiQuery } from "../../hooks/useApiQuery";
import { OperatorShell } from "../../layouts/OperatorShell";
import type {
  MaintenanceAlreadyDecidedDetails,
  MaintenanceDecisionResponse,
  MaintenanceSuggestion,
  MaintenanceSuggestionStatus,
  MaintenanceSuggestionsResponse,
} from "../../types/maintenance";
import { formatDateTime, formatNumber } from "../../utils/format";

const API = "/api/v1/maintenance/suggestions";
const TITLE = "Manutenção — Sugestões";
const SUBTITLE = "Sugestão automática a partir de paradas de manutenção não planejadas. Aceitar/descartar é só registro interno; nada é enviado ao TOTVS.";
const NOTE_MAX = 500;

const TABS: { status: MaintenanceSuggestionStatus; label: string; empty: string }[] = [
  { status: "sugerida", label: "Sugeridas", empty: "Nenhuma sugestão pendente." },
  { status: "aceita", label: "Aceitas", empty: "Nenhuma sugestão aceita." },
  { status: "descartada", label: "Descartadas", empty: "Nenhuma sugestão descartada." },
];

const ACCESS_DENIED = "Seu perfil não tem acesso às sugestões de manutenção. Só a Manutenção e a administração usam esta tela.";

/** Duração legível: "45 s", "25 min", "1 h 05 min". */
export function formatStopDuration(seconds: number | null | undefined) {
  if (seconds === null || seconds === undefined) return "Não disponível";
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total} s`;
  const minutes = Math.round(total / 60);
  if (minutes < 60) return `${minutes} min`;
  const rest = minutes % 60;
  return `${Math.floor(minutes / 60)} h${rest ? ` ${String(rest).padStart(2, "0")} min` : ""}`;
}

/** Mensagem humana da falha ao decidir; nunca o código técnico. O 409 diz quem decidiu antes. */
export function decisionErrorMessage(reason: unknown) {
  if (!(reason instanceof ApiError)) return "Não foi possível acessar o servidor. Tente novamente.";
  if (reason.status === 403) return ACCESS_DENIED;
  if (reason.status === 404) return "Esta sugestão não existe mais. A lista foi atualizada.";
  if (reason.status === 409) {
    const details = (reason.details ?? {}) as MaintenanceAlreadyDecidedDetails;
    const who = details.decidido_por_nome ? ` por ${details.decidido_por_nome}` : "";
    const when = details.decidido_em ? ` em ${formatDateTime(details.decidido_em)}` : "";
    return `Já decidida${who}${when}. A lista foi atualizada.`;
  }
  if (reason.status === 422) return `A nota é inválida (máximo de ${NOTE_MAX} caracteres).`;
  return "Não foi possível registrar a decisão. Tente novamente.";
}

/** Tela do perfil de Manutenção: o mesmo conteúdo no visual do terminal, sem a gestão. */
export function MaintenanceTerminalPage() {
  return <MaintenanceSuggestionsPage terminal />;
}

export function MaintenanceSuggestionsPage({ terminal = false }: { terminal?: boolean }) {
  const [status, setStatus] = useState<MaintenanceSuggestionStatus>("sugerida");
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [busyId, setBusyId] = useState<number | null>(null);
  const [feedback, setFeedback] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const query = useApiQuery<MaintenanceSuggestionsResponse>(`${API}?status=${status}`, { ignoreLiveTick: true });
  const data = query.data;
  const items = data?.items ?? [];
  const tab = TABS.find((item) => item.status === status)!;

  async function decide(item: MaintenanceSuggestion, action: "accept" | "discard") {
    if (busyId !== null) return;
    setBusyId(item.id);
    setFeedback(null);
    const nota = (notes[item.id] ?? "").trim();
    try {
      await api.post<MaintenanceDecisionResponse>(`${API}/${item.id}/${action}`, nota ? { nota } : undefined);
      setNotes((current) => {
        const { [item.id]: _removed, ...rest } = current;
        return rest;
      });
      setFeedback({ tone: "success", text: action === "accept" ? `Sugestão de ${item.recurso} aceita.` : `Sugestão de ${item.recurso} descartada.` });
    } catch (reason) {
      setFeedback({ tone: "error", text: decisionErrorMessage(reason) });
    } finally {
      setBusyId(null);
      query.reload();
    }
  }

  const base: TableColumn<MaintenanceSuggestion>[] = [
    { key: "recurso", label: "Recurso", render: (row) => row.recurso, sortValue: (row) => row.recurso, sticky: true },
    { key: "setor", label: "Setor", render: (row) => row.setor ?? "Não informado", sortValue: (row) => row.setor },
    { key: "inicio", label: "Início", render: (row) => formatDateTime(row.parada_inicio), sortValue: (row) => row.parada_inicio },
    { key: "duracao", label: "Duração", render: (row) => formatStopDuration(row.parada_segundos), sortValue: (row) => row.parada_segundos },
    { key: "motivo", label: "Motivo", render: (row) => row.motivo ?? "Não informado" },
    { key: "op", label: "OP", render: (row) => row.op ?? "Sem OP" },
  ];
  const decision: TableColumn<MaintenanceSuggestion>[] = status === "sugerida"
    ? [{
      key: "decisao",
      label: "Decisão",
      render: (row) => (
        <div className="maintenance-decision">
          <input
            type="text"
            className="maintenance-decision__note"
            aria-label={`Nota opcional para ${row.recurso}`}
            placeholder="Nota (opcional)"
            maxLength={NOTE_MAX}
            value={notes[row.id] ?? ""}
            disabled={busyId !== null}
            onChange={(event) => setNotes((current) => ({ ...current, [row.id]: event.target.value }))}
          />
          <button type="button" className="button button--primary" disabled={busyId !== null} onClick={() => decide(row, "accept")}>Aceitar</button>
          <button type="button" className="button" disabled={busyId !== null} onClick={() => decide(row, "discard")}>Descartar</button>
        </div>
      ),
    }]
    : [
      {
        key: "decidida",
        label: "Decidida por",
        render: (row) => (
          <div className="maintenance-decided">
            <StatusBadge value={row.status} />
            <span>{row.decidido_por_nome ?? "Não informado"}</span>
          </div>
        ),
      },
      { key: "quando", label: "Quando", render: (row) => formatDateTime(row.decidido_em), sortValue: (row) => row.decidido_em },
      { key: "nota", label: "Nota", render: (row) => row.nota || "Sem nota" },
    ];

  const body = (
    <>
      <div className="segment-toggle maintenance-tabs" role="tablist" aria-label="Situação da sugestão">
        {TABS.map((item) => (
          <button
            key={item.status}
            type="button"
            role="tab"
            aria-selected={item.status === status}
            className={`segment-toggle__btn${item.status === status ? " segment-toggle__btn--active" : ""}`}
            onClick={() => { setStatus(item.status); setFeedback(null); }}
          >
            {item.label}
          </button>
        ))}
      </div>

      {feedback ? <Notice tone={feedback.tone} className="maintenance-feedback">{feedback.text}</Notice> : null}

      {query.loading && !data ? <LoadingState /> : null}
      {query.error && !data ? (
        <div className="state-box state-box--error" role="alert">
          <strong>Não foi possível carregar as sugestões</strong>
          <span>{query.error.status === 403 ? ACCESS_DENIED : "Não foi possível carregar as sugestões. Tente novamente."}</span>
          {query.error.status === 403 ? null : <button type="button" onClick={query.reload}>Tentar novamente</button>}
        </div>
      ) : null}

      {data ? (
        <SectionCard title={tab.label} className="content-section" action={<span className="section-count">{`${formatNumber(data.count)} sugestão(ões)`}</span>}>
          {data.count >= data.limit ? <Notice tone="info">{`Mostrando as ${formatNumber(data.limit)} mais recentes. Decida estas para ver as anteriores.`}</Notice> : null}
          <DataTable columns={[...base, ...decision]} rows={items} rowKey={(row) => row.id} emptyTitle={tab.empty} />
        </SectionCard>
      ) : null}
    </>
  );

  if (terminal) {
    return (
      <OperatorShell sector="Manutenção" title="Manutenção · Sugestões" calls={false}>
        <div className="maintenance-terminal">
          <div className="operator-selection__heading"><h2>Sugestões de manutenção</h2><p>{SUBTITLE}</p></div>
          {data && query.error ? <Notice tone="error">Não foi possível atualizar a lista. Mostrando a última carregada.</Notice> : null}
          {body}
        </div>
      </OperatorShell>
    );
  }
  return (
    <PageFrame sectionId="maintenance" title={TITLE} subtitle={SUBTITLE} filters={false} staleError={data ? query.error : null}>
      {body}
    </PageFrame>
  );
}
