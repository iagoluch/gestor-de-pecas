import { useState } from "react";
import { ApiError, apiErrorMessage, directorPaths, putOperatorRate, putResourceRate } from "../../api/client";
import { AsyncButton } from "../../components/AsyncButton";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { SectionCard } from "../../components/SectionCard";
import { useApiQuery } from "../../hooks/useApiQuery";
import type { DirectorCosts as DirectorCostsData } from "../../types/director";
import { formatRate, parseRate } from "./directorFormat";

const INVALID_RATE = "Valor inválido. Digite o valor da hora em reais, maior que zero, por exemplo 12,50.";

function rateErrorMessage(reason: unknown) {
  // 422 de formato (corpo recusado antes da regra) chega com texto genérico; a regra do valor já vem em português.
  if (reason instanceof ApiError && reason.status === 422 && reason.code === "validation_error") return INVALID_RATE;
  return apiErrorMessage(reason);
}

export function DirectorCosts() {
  // Sem atualização ao vivo: a lista não muda enquanto a diretoria digita.
  const query = useApiQuery<DirectorCostsData>(directorPaths.costs, { ignoreLiveTick: true });
  const data = query.data;
  if (!data) {
    if (query.error) return <ErrorState error={query.error} onRetry={query.reload} />;
    return <LoadingState />;
  }
  return (
    <>
      <p className="director-note director-note--lead">
        Valor da hora em R$. Ele entra no custo das horas trabalhadas e das paradas fora do planejado. Quem fica sem valor aparece como “sem custo cadastrado”.
      </p>
      <div className="director-costs">
        <SectionCard title="Recursos (máquinas e postos)">
          {data.recursos.length ? (
            <ul className="director-rates">
              {data.recursos.map((item) => (
                <RateRow key={item.recurso} label={item.recurso} detail={item.setor} initial={item.valor_hora} onSave={(value) => putResourceRate(item.recurso, value)} />
              ))}
            </ul>
          ) : <EmptyState title="Nenhum recurso cadastrado" />}
        </SectionCard>
        <SectionCard title="Pessoas (operadores)">
          {data.pessoas.length ? (
            <ul className="director-rates">
              {data.pessoas.map((person) => (
                <RateRow
                  key={person.operador_id}
                  label={person.nome || (person.cracha ? `Crachá ${person.cracha}` : `Operador ${person.operador_id}`)}
                  detail={person.nome && person.cracha ? `Crachá ${person.cracha}` : null}
                  initial={person.valor_hora}
                  onSave={(value) => putOperatorRate(person.operador_id, value)}
                />
              ))}
            </ul>
          ) : <EmptyState title="Nenhum operador cadastrado" />}
        </SectionCard>
      </div>
    </>
  );
}

function RateRow({ label, detail, initial, onSave }: {
  label: string;
  detail: string | null;
  initial: number | null;
  onSave: (value: number) => Promise<unknown>;
}) {
  const [draft, setDraft] = useState(formatRate(initial));
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);

  async function save() {
    const value = parseRate(draft);
    // Zero ou negativo nem sai daqui (o servidor também recusa).
    if (value === null || value <= 0) {
      setStatus({ ok: false, text: INVALID_RATE });
      return;
    }
    try {
      await onSave(value);
      setDraft(formatRate(value));
      setStatus({ ok: true, text: "Salvo." });
    } catch (reason) {
      setStatus({ ok: false, text: rateErrorMessage(reason) });
    }
  }

  return (
    <li className="director-rate">
      <span className="director-rate__name">
        <strong>{label}</strong>
        {detail ? <small>{detail}</small> : null}
      </span>
      <span className="director-rate__field">
        <span aria-hidden="true">R$</span>
        <input
          aria-label={`Valor da hora de ${label}`}
          inputMode="decimal"
          autoComplete="off"
          placeholder="0,00"
          value={draft}
          onChange={(event) => { setDraft(event.target.value); setStatus(null); }}
        />
        <span aria-hidden="true">/h</span>
      </span>
      <AsyncButton className="button button--primary" aria-label={`Salvar valor de ${label}`} pendingLabel="Salvando…" onClick={save}>
        Salvar
      </AsyncButton>
      {status ? (
        <span className={status.ok ? "director-rate__ok" : "field-error"} role={status.ok ? "status" : "alert"}>{status.text}</span>
      ) : null}
    </li>
  );
}
