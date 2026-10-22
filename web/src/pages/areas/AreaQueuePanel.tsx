import { useState, type FormEvent } from "react";
import { api, ApiError } from "../../api/client";
import { DataTable } from "../../components/DataTable";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { SectionCard } from "../../components/SectionCard";
import { useApiQuery } from "../../hooks/useApiQuery";
import { formatNumber, formatResourceName } from "../../utils/format";

interface QueueResource {
  resource: string;
  nome: string;
  setor: string;
}

interface QueueItem {
  entry_id: number | null;
  operation_id: number;
  op: string;
  operation: string;
  product: string;
  description: string;
  qty: number;
  fixada: boolean;
  origem_recurso: string | null;
  posicao: number | null;
}

interface QueueResponse {
  resource: string;
  items: QueueItem[];
}

const FALLBACK_ERROR = "Não foi possível concluir a operação. Tente de novo.";

/**
 * Fila do dia por recurso: o líder fixa OPs num recurso e ajusta a ordem.
 * Regra e ordenação são do servidor; aqui só se envia o comando e se mostra
 * a lista devolvida por ele.
 */
export function AreaQueuePanel({ areaId }: { areaId: string }) {
  const base = `/api/v1/areas/${encodeURIComponent(areaId)}/queue`;
  const resources = useApiQuery<{ items: QueueResource[] }>(`${base}/resources`);
  const [chosen, setChosen] = useState("");
  const [op, setOp] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const options = resources.data?.items ?? [];
  const resource = chosen || options[0]?.resource || "";
  const queue = useApiQuery<QueueResponse>(resource ? `${base}?resource=${encodeURIComponent(resource)}` : null);
  const items = queue.data?.items ?? [];

  async function run(action: () => Promise<QueueResponse | void>, after?: () => void) {
    setBusy(true);
    setMessage("");
    try {
      const next = await action();
      if (next) queue.replaceData(next);
      after?.();
    } catch (reason) {
      setMessage(reason instanceof ApiError && reason.message ? reason.message : FALLBACK_ERROR);
      // A fila pode ter mudado no servidor: não deixa a tela velha depois do erro.
      queue.reload();
    } finally {
      setBusy(false);
    }
  }

  function add(event: FormEvent) {
    event.preventDefault();
    const code = op.trim();
    if (!code || !resource) return;
    void run(() => api.post<QueueResponse>(base, { resource, op: code }), () => setOp(""));
  }

  function move(index: number, step: -1 | 1) {
    const order = items.map((item) => item.operation_id);
    [order[index], order[index + step]] = [order[index + step], order[index]];
    void run(() => api.put<QueueResponse>(base, { resource, operation_ids: order }));
  }

  function remove(item: QueueItem) {
    void run(() => api.delete<QueueResponse>(`${base}/${item.entry_id}?resource=${encodeURIComponent(resource)}`));
  }

  return (
    <SectionCard title="Fila de prioridades" className="content-section section-card--table">
      <p className="operator-help">A ordem desta fila vale até a OP sair dela (concluída ou removida). Ela não zera no dia seguinte.</p>
      {resources.loading && !resources.data ? <LoadingState /> : null}
      {resources.error && !resources.data ? <ErrorState error={resources.error} onRetry={resources.reload} /> : null}
      {resources.data && !options.length ? <EmptyState title="Nenhum recurso disponível para a fila desta área" /> : null}
      {options.length ? (
        <form className="pause-form area-queue__form" onSubmit={add}>
          <label>
            Recurso
            <select value={resource} disabled={busy} onChange={(event) => { setChosen(event.target.value); setMessage(""); }}>
              {options.map((item) => <option key={item.resource} value={item.resource}>{formatResourceName(item.nome || item.resource)}</option>)}
            </select>
          </label>
          <label>
            OP
            <input value={op} disabled={busy} onChange={(event) => setOp(event.target.value)} placeholder="Número da OP" autoComplete="off" />
          </label>
          <button type="submit" className="button button--primary" disabled={busy || !op.trim()}>Adicionar à fila</button>
        </form>
      ) : null}
      {message ? <p className="field-error" role="alert">{message}</p> : null}
      {resource && queue.loading && !queue.data ? <LoadingState /> : null}
      {resource && queue.error && !queue.data ? <ErrorState error={queue.error} onRetry={queue.reload} /> : null}
      {resource && queue.data ? (
        <DataTable
          rows={items}
          rowKey={(item) => item.operation_id}
          emptyTitle="Nenhuma OP na fila deste recurso"
          columns={[
            { key: "pos", label: "Posição", render: (item) => formatNumber(items.indexOf(item) + 1) },
            { key: "op", label: "OP", render: (item) => <strong>{item.op}</strong> },
            { key: "operation", label: "Operação", render: (item) => item.operation },
            { key: "product", label: "Produto", render: (item) => item.product },
            { key: "qty", label: "Quantidade", render: (item) => formatNumber(item.qty) },
            {
              key: "tags",
              label: "Origem",
              render: (item) => (
                <span className="area-queue__tags">
                  {item.fixada ? <span className="status-badge status-badge--info">Fixada pelo líder</span> : null}
                  {item.origem_recurso && item.origem_recurso !== resource
                    ? <span className="status-badge status-badge--warning">Veio de {formatResourceName(item.origem_recurso)}</span>
                    : null}
                </span>
              ),
            },
            {
              key: "actions",
              label: "Ações",
              render: (item) => {
                const index = items.indexOf(item);
                return (
                  <span className="area-queue__actions">
                    <button type="button" className="button" aria-label={`Subir OP ${item.op}`} disabled={busy || index === 0} onClick={() => move(index, -1)}>Subir</button>
                    <button type="button" className="button" aria-label={`Descer OP ${item.op}`} disabled={busy || index === items.length - 1} onClick={() => move(index, 1)}>Descer</button>
                    <button type="button" className="button" aria-label={`Remover OP ${item.op} da fila`} disabled={busy || item.entry_id == null} onClick={() => remove(item)}>Remover</button>
                  </span>
                );
              },
            },
          ]}
        />
      ) : null}
    </SectionCard>
  );
}
