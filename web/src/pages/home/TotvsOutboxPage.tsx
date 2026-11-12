import { useState } from "react";
import { api, apiErrorMessage } from "../../api/client";
import { DataTable } from "../../components/DataTable";
import type { TableColumn } from "../../components/DataTable";
import { LoadingState } from "../../components/DataState";
import { Notice } from "../../components/Notice";
import { PageFrame } from "../../components/PageFrame";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import { useApiQuery } from "../../hooks/useApiQuery";
import { formatDateTime, formatNumber } from "../../utils/format";

const API = "/api/v1/admin/totvs-outbox";

export type OutboxItem = {
  id: number;
  event_type: string;
  production_order: string | null;
  operation_code: string | null;
  status: string;
  attempts: number | null;
  created_at: string | null;
  updated_at: string | null;
  last_error_message: string | null;
  discarded_at: string | null;
  discarded_by: string | null;
  discard_reason: string | null;
};

const STATUS: Record<string, string> = {
  ERROR: "Com erro",
  PENDING: "Na fila",
  RETRY: "Vai tentar de novo",
  SENDING: "Enviando",
  SENT: "Enviado",
  DISCARDED: "Descartado",
};

const EVENTS: Record<string, string> = {
  production_appointment_zero: "Início (quantidade zero)",
  production_appointment: "Apontamento",
  production_appointment_terminal: "Encerramento da OP",
};

/** Envios ao Protheus que travaram (A58). Só admin; o backend exige o mesmo. */
export function TotvsOutboxPage() {
  const [status, setStatus] = useState("ERROR");
  const [busy, setBusy] = useState<number | null>(null);
  const [message, setMessage] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const query = useApiQuery<{ items: OutboxItem[] }>(`${API}?status=${status}`, { ignoreLiveTick: true });
  const items = query.data?.items;

  async function act(item: OutboxItem, kind: "reprocess" | "discard") {
    let body: { motivo: string } | undefined;
    if (kind === "reprocess" && !window.confirm(`Reenviar o envio ${item.id} (OP ${item.production_order ?? "?"}) ao Protheus agora?`)) return;
    if (kind === "discard") {
      const motivo = window.prompt(`Por que descartar o envio ${item.id} (OP ${item.production_order ?? "?"})? Ele não será mais enviado ao Protheus.`);
      if (motivo === null) return;
      if (motivo.trim().length < 3) {
        setMessage({ tone: "error", text: "Escreva o motivo do descarte (pelo menos 3 letras)." });
        return;
      }
      body = { motivo: motivo.trim() };
    }
    setBusy(item.id);
    setMessage(null);
    try {
      await api.post(`${API}/${item.id}/${kind}`, body);
      setMessage({ tone: "success", text: kind === "discard" ? `Envio ${item.id} descartado.` : `Envio ${item.id} voltou para a fila.` });
      query.reload();
    } catch (reason) {
      setMessage({ tone: "error", text: apiErrorMessage(reason) });
    } finally {
      setBusy(null);
    }
  }

  const columns: TableColumn<OutboxItem>[] = [
    { key: "id", label: "Envio", render: (row) => row.id, sortValue: (row) => row.id, sticky: true },
    { key: "op", label: "OP", render: (row) => row.production_order ?? "—", sortValue: (row) => row.production_order },
    { key: "tipo", label: "Tipo", render: (row) => `${EVENTS[row.event_type] ?? row.event_type}${row.operation_code ? ` · op ${row.operation_code}` : ""}` },
    { key: "status", label: "Situação", render: (row) => <StatusBadge value={STATUS[row.status] ?? row.status} />, sortValue: (row) => row.status },
    { key: "quando", label: "Última mudança", render: (row) => (row.updated_at ? formatDateTime(row.updated_at) : "—"), sortValue: (row) => row.updated_at },
    {
      key: "erro",
      label: "O que o Protheus respondeu",
      render: (row) =>
        row.status === "DISCARDED"
          ? `Descartado por ${row.discarded_by ?? "?"}: ${row.discard_reason ?? ""}`
          : row.last_error_message ?? "—",
    },
    {
      key: "acoes",
      label: "Ações",
      render: (row) =>
        row.status === "ERROR" ? (
          <span style={{ display: "inline-flex", gap: 8 }}>
            <button type="button" className="button" disabled={busy !== null} onClick={() => act(row, "reprocess")}>Reenviar</button>
            <button type="button" className="button operator-danger" disabled={busy !== null} onClick={() => act(row, "discard")}>Descartar</button>
          </span>
        ) : null,
    },
  ];

  return (
    <PageFrame
      sectionId="dev"
      title="Envios ao Protheus"
      subtitle="Envios que o Protheus recusou. Reenviar tenta de novo o mesmo envio; descartar para de enviar e libera os próximos da mesma OP. Nada muda na produção apontada."
      filters={false}
      staleError={items ? query.error : null}
    >
      <div className="filter-bar">
        <div className="filter-bar__row">
          <label>
            Situação
            <select value={status} onChange={(event) => setStatus(event.target.value)}>
              <option value="ERROR">Com erro</option>
              <option value="DISCARDED">Descartados</option>
              <option value="">Todos</option>
            </select>
          </label>
        </div>
      </div>

      {message ? <Notice tone={message.tone}>{message.text}</Notice> : null}
      {query.loading && !items ? <LoadingState /> : null}
      {query.error && !items ? (
        <div className="state-box state-box--error" role="alert">
          <strong>Não foi possível carregar os envios</strong>
          <span>{query.error.status === 403 ? "Esta tela é exclusiva da administração." : "Tente novamente."}</span>
          {query.error.status === 403 ? null : <button type="button" onClick={query.reload}>Tentar novamente</button>}
        </div>
      ) : null}

      {items ? (
        <SectionCard title="Mais recentes primeiro" className="content-section" action={<span className="section-count">{`${formatNumber(items.length)} envio(s)`}</span>}>
          <DataTable columns={columns} rows={items} rowKey={(row) => row.id} emptyTitle="Nenhum envio nesta situação." />
        </SectionCard>
      ) : null}
    </PageFrame>
  );
}
