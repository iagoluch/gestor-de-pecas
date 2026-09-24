import { useMemo, useState } from "react";
import { DataTable } from "../../components/DataTable";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { MetricCard } from "../../components/MetricCard";
import { OperatorDialog } from "../../components/OperatorDialog";
import { PageFrame } from "../../components/PageFrame";
import { RecordToolbar } from "../../components/RecordToolbar";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import { api } from "../../api/client";
import { useApiQuery } from "../../hooks/useApiQuery";
import { usePersistentFilters } from "../../hooks/usePersistentFilters";

interface AutomaticPause {
  id: number;
  tipo_setor: string;
  nome: string;
  hora_inicio: string;
  hora_fim: string;
  ativo: boolean;
  ordem: number;
  atualizado_por?: string | null;
  atualizado_em?: string | null;
}

interface PausesResponse {
  items: AutomaticPause[];
  sectors: string[];
  count: number;
  active: number;
}

const SETORES = [
  "Corte", "Dobra", "Usinagem", "Serra", "Caldeiraria",
  "Solda Aço", "Solda Alumínio", "Solda Robô", "Proj. Ferramentaria", "Protótipo",
  "Pintura", "Montagem", "Destaque",
];

const FILTROS_INICIAIS = { setor: "", tipo: "", busca: "" };

/**
 * Tipos de pausa reconhecidos pela tela. É classificação de apresentação sobre
 * a descrição já cadastrada — o cadastro continua livre e a regra de parada
 * (planejada/não planejada) permanece no backend, intocada.
 */
const TIPOS_CONHECIDOS: { key: string; label: string; matches: RegExp }[] = [
  { key: "almoco", label: "Almoço", matches: /almo[çc]/i },
  { key: "cafe", label: "Café", matches: /caf[ée]/i },
  { key: "ginastica", label: "Ginástica laboral", matches: /gin[áa]stica|labor/i },
  { key: "reuniao", label: "Reunião", matches: /reuni/i },
  { key: "limpeza", label: "Limpeza", matches: /limpeza|organiza/i },
  { key: "treinamento", label: "Treinamento", matches: /treinam|integra/i },
];

function tipoDaPausa(nome: string) {
  const descricao = String(nome ?? "").trim();
  const conhecido = TIPOS_CONHECIDOS.find((tipo) => tipo.matches.test(descricao));
  if (conhecido) return { key: conhecido.key, label: conhecido.label };
  if (!descricao) return { key: "outros", label: "Outras pausas" };
  return { key: `descricao:${descricao.toLocaleLowerCase("pt-BR")}`, label: descricao };
}

/** "12:10:00" e "12:10" chegam do backend conforme o driver; a tela mostra HH:mm. */
function hora(valor: string) {
  return String(valor ?? "").slice(0, 5);
}

function minutos(inicio: string, fim: string) {
  const [hi, mi] = hora(inicio).split(":").map(Number);
  const [hf, mf] = hora(fim).split(":").map(Number);
  if ([hi, mi, hf, mf].some((item) => Number.isNaN(item))) return null;
  const total = (hf * 60 + mf) - (hi * 60 + mi);
  return total > 0 ? total : total + 24 * 60;
}

export function ManagementPausesPage() {
  const query = useApiQuery<PausesResponse>("/api/v1/management/pauses");
  const [editando, setEditando] = useState<AutomaticPause | null>(null);
  const [mensagem, setMensagem] = useState("");
  const [salvando, setSalvando] = useState(false);
  const filtros = usePersistentFilters("gestor.filtros.pausas", FILTROS_INICIAIS);

  const items = useMemo(() => query.data?.items ?? [], [query.data]);
  const title = "Painéis Operacionais — Pausas automáticas";
  const subtitle = "Horários em que o sistema interrompe o apontamento por setor.";

  const setores = useMemo(() => {
    const encontrados = query.data?.sectors?.length
      ? query.data.sectors
      : [...new Set(items.map((item) => item.tipo_setor).filter(Boolean))];
    return encontrados
      .map((setor) => ({
        value: setor,
        label: setor,
        count: items.filter((item) => item.tipo_setor === setor).length,
      }))
      .sort((left, right) => left.label.localeCompare(right.label, "pt-BR"));
  }, [items, query.data]);

  const tipos = useMemo(() => {
    const agrupados = new Map<string, { value: string; label: string; count: number }>();
    items.forEach((item) => {
      const tipo = tipoDaPausa(item.nome);
      const atual = agrupados.get(tipo.key);
      if (atual) atual.count += 1;
      else agrupados.set(tipo.key, { value: tipo.key, label: tipo.label, count: 1 });
    });
    return [...agrupados.values()].sort((left, right) => left.label.localeCompare(right.label, "pt-BR"));
  }, [items]);

  const filtradas = useMemo(() => {
    const busca = filtros.values.busca.trim().toLocaleLowerCase("pt-BR");
    return items
      .filter((item) => !filtros.values.setor || item.tipo_setor === filtros.values.setor)
      .filter((item) => !filtros.values.tipo || tipoDaPausa(item.nome).key === filtros.values.tipo)
      .filter((item) => !busca || `${item.tipo_setor} ${item.nome} ${hora(item.hora_inicio)}`
        .toLocaleLowerCase("pt-BR").includes(busca))
      .sort((left, right) => left.tipo_setor.localeCompare(right.tipo_setor, "pt-BR")
        || hora(left.hora_inicio).localeCompare(hora(right.hora_inicio))
        || left.ordem - right.ordem);
  }, [filtros.values, items]);

  async function salvar(pausa: Partial<AutomaticPause>) {
    setSalvando(true);
    setMensagem("");
    try {
      await api.post("/api/v1/management/pauses", pausa);
      setMensagem("Pausa salva. O próximo ciclo já usa o novo horário.");
      setEditando(null);
      query.reload();
    } catch {
      setMensagem("Não foi possível salvar a pausa. Confira o horário informado.");
    } finally {
      setSalvando(false);
    }
  }

  async function remover(pausa: AutomaticPause) {
    setSalvando(true);
    try {
      await api.delete(`/api/v1/management/pauses/${pausa.id}`);
      setMensagem("Pausa removida.");
      query.reload();
    } catch {
      setMensagem("Não foi possível remover a pausa.");
    } finally {
      setSalvando(false);
    }
  }

  if (query.loading && !query.data) {
    return <PageFrame sectionId="panels" title={title} subtitle={subtitle} filters={false}><LoadingState /></PageFrame>;
  }
  if (query.error && !query.data) {
    return <PageFrame sectionId="panels" title={title} subtitle={subtitle} filters={false}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  }

  const setoresConfigurados = new Set(items.filter((item) => item.ativo).map((item) => item.tipo_setor));
  const resumo = filtros.active
    ? `${filtradas.length} de ${items.length} pausas no recorte atual`
    : `${items.length} pausas configuradas`;
  // A coluna de tipo só aparece quando acrescenta informação: com a descrição
  // igual ao tipo ("Almoço"/"Almoço") ela seria ruído na leitura.
  const mostrarTipo = filtradas.some((item) =>
    tipoDaPausa(item.nome).label.toLocaleLowerCase("pt-BR") !== item.nome.trim().toLocaleLowerCase("pt-BR"));
  return (
    <PageFrame staleError={query.error}
      sectionId="panels"
      title={title}
      subtitle={subtitle}
      filters={false}
      actions={<button type="button" className="button button--primary" onClick={() => setEditando({ id: 0, tipo_setor: SETORES[0], nome: "", hora_inicio: "12:10", hora_fim: "12:52", ativo: true, ordem: 1 })}>Nova pausa</button>}
    >
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Pausas ativas" value={String(query.data?.active ?? 0)} detail={`${query.data?.count ?? 0} configuradas`} accent="primary" />
        <MetricCard label="Setores cobertos" value={String(setoresConfigurados.size)} detail={`de ${SETORES.length} setores`} accent="success" />
        <MetricCard label="Almoço" value={`${items.filter((item) => item.ativo && /almo/i.test(item.nome)).length} setor(es)`} accent="warning" />
        <MetricCard label="Café" value={`${items.filter((item) => item.ativo && /caf/i.test(item.nome)).length} setor(es)`} accent="teal" />
      </div>

      {mensagem ? <p className="operator-notice" role="status">{mensagem}</p> : null}

      <RecordToolbar
        ariaLabel="Filtros das pausas automáticas"
        selects={[
          {
            id: "pausas-setor",
            label: "Setor",
            allLabel: "Todos os setores",
            value: filtros.values.setor,
            options: setores,
            onChange: (value) => filtros.set("setor", value),
          },
          {
            id: "pausas-tipo",
            label: "Tipo de pausa",
            allLabel: "Todos os tipos",
            value: filtros.values.tipo,
            options: tipos,
            onChange: (value) => filtros.set("tipo", value),
          },
        ]}
        search={{
          value: filtros.values.busca,
          onChange: (value) => filtros.set("busca", value),
          placeholder: "Buscar por setor, pausa ou horário",
        }}
        summary={resumo}
        onReset={filtros.reset}
        resetDisabled={!filtros.active}
      />

      <SectionCard
        title="Pausas por setor"
        className="content-section section-card--table"
        action={<span className="section-count">{filtradas.length} pausa(s)</span>}
      >
        {filtradas.length ? (
          <DataTable
            rows={filtradas}
            rowKey={(row) => row.id}
            columns={[
              { key: "setor", label: "Setor", render: (row) => row.tipo_setor },
              { key: "nome", label: "Pausa", render: (row) => row.nome },
              ...(mostrarTipo ? [{ key: "tipo", label: "Tipo", render: (row: AutomaticPause) => tipoDaPausa(row.nome).label }] : []),
              { key: "inicio", label: "Início", render: (row) => hora(row.hora_inicio) },
              { key: "fim", label: "Fim", render: (row) => hora(row.hora_fim) },
              { key: "duracao", label: "Duração", render: (row) => { const total = minutos(row.hora_inicio, row.hora_fim); return total === null ? "Horário a confirmar" : `${total} min`; } },
              { key: "estado", label: "Situação", render: (row) => <StatusBadge value={row.ativo ? "Ativa" : "Inativa"} /> },
              {
                key: "acoes",
                label: "Ações",
                render: (row) => (
                  <span className="pause-actions">
                    <button type="button" disabled={salvando} onClick={() => setEditando(row)}>Editar</button>
                    <button type="button" disabled={salvando} onClick={() => { if (window.confirm(row.ativo ? `Desativar a pausa "${row.nome}"? Ela deixa de valer para os próximos ciclos.` : `Ativar a pausa "${row.nome}"?`)) void salvar({ ...row, ativo: !row.ativo }); }}>{row.ativo ? "Desativar" : "Ativar"}</button>
                    <button type="button" disabled={salvando} onClick={() => { if (window.confirm(`Remover a pausa "${row.nome}"? Esta ação não pode ser desfeita.`)) void remover(row); }}>Remover</button>
                  </span>
                ),
              },
            ]}
          />
        ) : items.length ? (
          <EmptyState
            title="Nenhuma pausa no filtro atual"
            detail="Ajuste o setor, o tipo de pausa ou a busca para ver as pausas cadastradas."
          />
        ) : (
          <EmptyState title="Nenhuma pausa configurada" detail="Sem configuração, o sistema não interrompe automaticamente o apontamento." />
        )}
      </SectionCard>

      {editando ? (
        <OperatorDialog
          title={editando.id ? "Editar pausa" : "Nova pausa"}
          onCancel={() => (salvando ? undefined : setEditando(null))}
        >
          <form
            className="pause-form pause-form--dialog"
            onSubmit={(event) => {
              event.preventDefault();
              void salvar({ ...editando, id: editando.id || undefined });
            }}
          >
            <label>Setor
              <select value={editando.tipo_setor} onChange={(event) => setEditando({ ...editando, tipo_setor: event.target.value })}>
                {SETORES.map((setor) => <option key={setor} value={setor}>{setor}</option>)}
              </select>
            </label>
            <label>Descrição<input value={editando.nome} onChange={(event) => setEditando({ ...editando, nome: event.target.value })} placeholder="Almoço, Café, Ginástica…" required /></label>
            <label>Início<input type="time" value={hora(editando.hora_inicio)} onChange={(event) => setEditando({ ...editando, hora_inicio: event.target.value })} required /></label>
            <label>Fim<input type="time" value={hora(editando.hora_fim)} onChange={(event) => setEditando({ ...editando, hora_fim: event.target.value })} required /></label>
            <label className="pause-form__check"><input type="checkbox" checked={editando.ativo} onChange={(event) => setEditando({ ...editando, ativo: event.target.checked })} />Ativa</label>
            <div className="pause-form__actions">
              <button type="button" onClick={() => setEditando(null)}>Cancelar</button>
              <button type="submit" className="button button--primary" disabled={salvando || !editando.nome.trim()}>Salvar</button>
            </div>
          </form>
        </OperatorDialog>
      ) : null}
    </PageFrame>
  );
}
