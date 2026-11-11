import { useState } from "react";
import type { FormEvent } from "react";
import { api, ApiError } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { useConfirm } from "../../components/ConfirmDialog";
import { DataTable } from "../../components/DataTable";
import type { TableColumn } from "../../components/DataTable";
import { LoadingState } from "../../components/DataState";
import { Notice } from "../../components/Notice";
import { PageFrame } from "../../components/PageFrame";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import { useApiQuery } from "../../hooks/useApiQuery";
import { decisionLabel } from "../production/QualityRncDecisionPage";
import type { ChangeAction, ChangeAuditEntry, ChangeAuditResponse } from "../../types/changeAudit";
import { formatDateTime, formatNumber } from "../../utils/format";

const API = "/api/v1/management/audit";
const LIMIT = 200;

/** Só o que o log guarda (valores em R$ ficam na aba Diretoria e nunca chegam aqui). */
const ENTITIES: Record<string, string> = {
  usuario: "Usuário",
  nivel: "Nível de acesso",
  turno: "Turno",
  pausa: "Pausa",
  rnc_decisao: "Decisão de RNC",
  manutencao_sugestao: "Sugestão de manutenção",
  roteiro_etapa: "Etapa do roteiro",
  calendario: "Calendário produtivo",
  calendario_turno: "Turno do calendário",
  calendario_recurso: "Calendário do recurso",
  cracha: "Crachá",
  solda_produto: "Produto da Solda",
  solda_subconjunto: "Subconjunto da Solda",
  solda_vinculo: "Código de item da Solda",
};

const ACTIONS: Record<ChangeAction, string> = { criar: "Criou", alterar: "Alterou", excluir: "Excluiu" };

const FIELDS: Record<string, string> = {
  nome: "Nome",
  nivel_atribuido: "Nível",
  unidade: "Unidade",
  ativo: "Ativo",
  rotulo: "Rótulo",
  nivel_base: "Nível base",
  tipo: "Tipo",
  hora_inicio: "Início",
  hora_fim: "Fim",
  ordem: "Ordem",
  tipo_setor: "Setor",
  rnc_id: "RNC (id)",
  rnc_codigo: "RNC",
  decisao: "Decisão",
  justificativa: "Justificativa",
  sugestao_id: "Sugestão (id)",
  recurso: "Recurso",
  parada_inicio: "Início da parada",
  status: "Situação",
  nota: "Nota",
};

/** Só o desenvolvedor desfaz, e só o que guarda o "antes" (espelha `undo_audit` do backend). */
const UNDOABLE = ["usuario", "turno", "pausa"];

export function canUndo(entry: Pick<ChangeAuditEntry, "entidade" | "acao" | "antes">) {
  return UNDOABLE.includes(entry.entidade) && entry.acao === "alterar" && !!entry.antes;
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}T/;

export function entityLabel(entity: string) {
  return ENTITIES[entity] ?? entity;
}

const STATUS_LABELS: Record<string, string> = { sugerida: "Sugerida", aceita: "Aceita", descartada: "Descartada" };

export function fieldValue(value: unknown, key?: string) {
  if (value === null || value === undefined || value === "") return "vazio";
  if (typeof value === "boolean") return value ? "Sim" : "Não";
  if (typeof value === "string" && ISO_DATE.test(value)) return formatDateTime(value);
  if (typeof value === "string" && key === "decisao") return decisionLabel(value);
  if (typeof value === "string" && key === "status") return STATUS_LABELS[value] ?? value;
  return String(value);
}

/** Linhas curtas "Campo: antes → depois" (alterar) ou "Campo: valor" (criar/excluir). */
export function changeLines(entry: Pick<ChangeAuditEntry, "acao" | "antes" | "depois">) {
  const antes = entry.antes ?? {};
  const depois = entry.depois ?? {};
  const keys = Array.from(new Set([...Object.keys(antes), ...Object.keys(depois)]));
  const label = (key: string) => FIELDS[key] ?? key;
  if (entry.acao === "alterar") {
    return keys
      .filter((key) => fieldValue(antes[key], key) !== fieldValue(depois[key], key))
      .map((key) => `${label(key)}: ${fieldValue(antes[key], key)} → ${fieldValue(depois[key], key)}`);
  }
  const base = entry.acao === "criar" ? depois : antes;
  return keys.filter((key) => key in base).map((key) => `${label(key)}: ${fieldValue(base[key], key)}`);
}

function toQuery(filters: { entidade: string; usuario: string; desde: string; ate: string }) {
  const params = new URLSearchParams({ limite: String(LIMIT) });
  for (const [key, value] of Object.entries(filters)) if (value.trim()) params.set(key, value.trim());
  return params.toString();
}

const EMPTY = { entidade: "", usuario: "", desde: "", ate: "" };

/** Quem mudou o quê (migration 66). Só admin; a rota e o backend exigem o mesmo. */
export function ChangeAuditPage() {
  const [draft, setDraft] = useState(EMPTY);
  const [applied, setApplied] = useState(EMPTY);
  const query = useApiQuery<ChangeAuditResponse>(`${API}?${toQuery(applied)}`, { ignoreLiveTick: true });
  const data = query.data;
  const { user } = useAuth();
  const [confirm, confirmDialog] = useConfirm();
  const [feedback, setFeedback] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const isDeveloper = user?.role === "desenvolvedor";

  async function undo(row: ChangeAuditEntry) {
    const ok = await confirm({
      title: "Desfazer alteração",
      message: `${entityLabel(row.entidade)} · ${row.chave} volta ao valor de antes. A reversão também fica registrada no log.`,
      confirmLabel: "Desfazer",
      tone: "danger",
    });
    if (!ok) return;
    try {
      await api.post(`${API}/${row.id}/undo`, {});
      setFeedback({ tone: "success", text: "Alteração desfeita." });
      query.reload();
    } catch (reason) {
      setFeedback({ tone: "error", text: reason instanceof ApiError ? reason.message : "Não foi possível desfazer." });
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    setApplied(draft);
  }

  function clear() {
    setDraft(EMPTY);
    setApplied(EMPTY);
  }

  const columns: TableColumn<ChangeAuditEntry>[] = [
    { key: "quando", label: "Quando", render: (row) => formatDateTime(row.quando), sortValue: (row) => row.quando, sticky: true },
    { key: "usuario", label: "Quem", render: (row) => row.usuario_nome ?? "Não informado", sortValue: (row) => row.usuario_nome },
    { key: "entidade", label: "O quê", render: (row) => `${entityLabel(row.entidade)} · ${row.chave}`, sortValue: (row) => entityLabel(row.entidade) },
    { key: "acao", label: "Ação", render: (row) => <StatusBadge value={ACTIONS[row.acao]} />, sortValue: (row) => row.acao },
    {
      key: "mudanca",
      label: "Mudança",
      render: (row) => {
        const lines = changeLines(row);
        return lines.length ? <ul className="change-audit__lines">{lines.map((line) => <li key={line}>{line}</li>)}</ul> : "Sem diferença nos campos registrados";
      },
    },
    ...(isDeveloper
      ? [{
          key: "desfazer",
          label: "",
          render: (row: ChangeAuditEntry) =>
            canUndo(row) ? <button type="button" className="button" onClick={() => void undo(row)}>Desfazer</button> : null,
        }]
      : []),
  ];

  return (
    <PageFrame
      sectionId="dev"
      title="Alterações"
      subtitle="Quem mudou usuários, níveis, turnos, pausas, decisões de RNC e sugestões de manutenção. Só leitura."
      filters={false}
      staleError={data ? query.error : null}
    >
      <form className="filter-bar" onSubmit={submit} aria-label="Filtros das alterações">
        <div className="filter-bar__row">
          <label>
            O quê
            <select value={draft.entidade} onChange={(event) => setDraft({ ...draft, entidade: event.target.value })}>
              <option value="">Tudo</option>
              {Object.entries(ENTITIES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label>
            Quem
            <input type="text" placeholder="Nome ou id" maxLength={80} value={draft.usuario} onChange={(event) => setDraft({ ...draft, usuario: event.target.value })} />
          </label>
          <label>
            De
            <input type="date" value={draft.desde} onChange={(event) => setDraft({ ...draft, desde: event.target.value })} />
          </label>
          <label>
            Até
            <input type="date" value={draft.ate} onChange={(event) => setDraft({ ...draft, ate: event.target.value })} />
          </label>
          <button type="submit" className="button button--primary">Filtrar</button>
          <button type="button" className="button" onClick={clear}>Limpar</button>
        </div>
      </form>

      {feedback ? <Notice tone={feedback.tone === "error" ? "error" : "success"}>{feedback.text}</Notice> : null}
      {query.loading && !data ? <LoadingState /> : null}
      {query.error && !data ? (
        <div className="state-box state-box--error" role="alert">
          <strong>Não foi possível carregar as alterações</strong>
          <span>{query.error.status === 403 ? "Esta tela é exclusiva da conta de administração." : "Tente novamente."}</span>
          {query.error.status === 403 ? null : <button type="button" onClick={query.reload}>Tentar novamente</button>}
        </div>
      ) : null}

      {data ? (
        <SectionCard title="Mais recentes primeiro" className="content-section" action={<span className="section-count">{`${formatNumber(data.count)} alteração(ões)`}</span>}>
          {data.count >= LIMIT ? <Notice tone="info">{`Mostrando as ${formatNumber(LIMIT)} mais recentes. Use os filtros para ver as anteriores.`}</Notice> : null}
          <DataTable columns={columns} rows={data.items} rowKey={(row) => row.id} emptyTitle="Nenhuma alteração registrada para este filtro." />
        </SectionCard>
      ) : null}
      {confirmDialog}
    </PageFrame>
  );
}
