import { useMemo, useState } from "react";
import { api, ApiError } from "../../api/client";
import { DataTable } from "../../components/DataTable";
import { RowActions } from "../../components/RowActions";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { MetricCard } from "../../components/MetricCard";
import { OperatorDialog } from "../../components/OperatorDialog";
import { Obrigatorio, ValidatedForm } from "../../components/ValidatedForm";
import { PageFrame } from "../../components/PageFrame";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import { useApiQuery } from "../../hooks/useApiQuery";
import { Notice } from "../../components/Notice";
import { useConfirm } from "../../components/ConfirmDialog";
import { useDraft } from "../../hooks/useDraft";

interface ShiftParameter {
  id: number;
  nome: string;
  tipo: "expediente" | "hora_extra" | "fora_turno";
  hora_inicio: string;
  hora_fim: string;
  ativo: boolean;
  ordem: number;
  /** Hora extra e fora de turno pertencem a um turno oficial (expediente). */
  turno_id?: number | null;
}

interface ShiftParametersResponse {
  items: ShiftParameter[];
  count: number;
}

const TIPOS = [
  { value: "expediente", label: "Expediente (janela oficial)" },
  { value: "hora_extra", label: "Hora extra" },
  { value: "fora_turno", label: "Fora de turno" },
] as const;

/** "17:30:00" e "17:30" chegam do backend conforme o driver; a tela mostra HH:mm. */
// O servidor aceita fim antes do início (turno que cruza a meia-noite); a UI
// só deixa isso explícito (GE-06), sem inventar regra de turno.
const viraODia = (turno: Pick<ShiftParameter, "hora_inicio" | "hora_fim">) =>
  Boolean(turno.hora_inicio && turno.hora_fim) && hora(turno.hora_fim) < hora(turno.hora_inicio);

/** Faixas do card "Novo turno": cada uma vira uma linha de `parametros_turno`. */
const FAIXAS = [
  { chave: "H1", tipo: "hora_extra", rotulo: "H1", inicio: "06:00", fim: "08:00" },
  { chave: "Oficial", tipo: "expediente", rotulo: "Oficial", inicio: "08:00", fim: "17:30" },
  { chave: "H2", tipo: "hora_extra", rotulo: "H2", inicio: "17:30", fim: "21:30" },
  { chave: "Fora de turno", tipo: "fora_turno", rotulo: "Fora de turno", inicio: "21:30", fim: "06:00" },
] as const;

type NovoTurno = { nome: string; faixas: Record<string, { inicio: string; fim: string; usar: boolean }> };

/** Só o expediente é obrigatório: nem todo turno tem H1, H2 ou fora de turno. */
const NOVO_TURNO = (letra: string): NovoTurno => ({
  nome: `Turno ${letra}`,
  faixas: Object.fromEntries(FAIXAS.map((faixa) => [faixa.chave, { inicio: faixa.inicio, fim: faixa.fim, usar: true }])),
});

function hora(valor: string) {
  return String(valor ?? "").slice(0, 5);
}

/**
 * Turnos automáticos (H1/expediente/H2 e futuros): quando o sistema força o
 * apontamento "fora de turno" no fim do expediente/hora extra e quando volta
 * com "recurso sem demanda" na abertura do expediente. Antes desta tela os
 * horários eram uma constante fixa em código; agora `ShiftBoundaryService`
 * lê esta configuração a cada ciclo (decisão do usuário, 15/09/2026).
 */
export function ManagementShiftsPage() {
  const query = useApiQuery<ShiftParametersResponse>("/api/v1/management/shift-parameters");
  const [mensagem, setMensagem] = useState("");
  const [confirm, confirmDialog] = useConfirm();
  const [editando, setEditando, abrirEdicao, fecharEdicao] = useDraft<ShiftParameter>(confirm);
  const [salvando, setSalvando] = useState(false);
  const [novoTurno, setNovoTurno] = useState<NovoTurno | null>(null);

  const items = useMemo(
    () => [...(query.data?.items ?? [])].sort((left, right) => left.ordem - right.ordem || hora(left.hora_inicio).localeCompare(hora(right.hora_inicio))),
    [query.data],
  );
  const title = "IagoDev — Turnos";
  const subtitle = "Horários em que o sistema fecha e reabre o apontamento automaticamente.";
  const expediente = items.find((item) => item.tipo === "expediente" && item.ativo);
  const horasExtras = items.filter((item) => item.tipo === "hora_extra" && item.ativo);
  const foraTurno = items.filter((item) => item.tipo === "fora_turno" && item.ativo);
  const turnosOficiais = items.filter((item) => item.tipo === "expediente");

  async function salvar(turno: Partial<ShiftParameter>) {
    setSalvando(true);
    setMensagem("");
    try {
      // Só o comando: a linha lida pode trazer campos que o contrato recusa.
      const { id, nome, tipo, hora_inicio, hora_fim, ativo, ordem } = turno;
      const turno_id = tipo === "expediente" ? null : turno.turno_id ?? null;
      await api.post("/api/v1/management/shift-parameters", { id, nome, tipo, hora_inicio, hora_fim, ativo, ordem, turno_id });
      setMensagem("Turno salvo. O próximo ciclo já usa o novo horário.");
      setEditando(null);
      query.reload();
    } catch (reason) {
      setMensagem(reason instanceof ApiError && reason.status === 400 ? reason.message : "Não foi possível salvar o turno. Confira o nome, o tipo e o horário informados.");
    } finally {
      setSalvando(false);
    }
  }

  // Só um expediente ativo por vez (a regra global lê um só): se já existe, o turno novo entra desativado.
  async function salvarNovoTurno(turno: NovoTurno) {
    setSalvando(true);
    setMensagem("");
    try {
      const ordemBase = items.reduce((maior, item) => Math.max(maior, item.ordem), 0);
      // O expediente sai primeiro: as outras faixas se ligam ao id que ele recebe.
      let turnoId: number | null = null;
      const ordenadas = [...FAIXAS.entries()].sort(([, a], [, b]) => Number(b.tipo === "expediente") - Number(a.tipo === "expediente"));
      for (const [indice, faixa] of ordenadas) {
        const { inicio, fim, usar } = turno.faixas[faixa.chave];
        if (faixa.tipo !== "expediente" && !usar) continue;
        const resposta: { item?: { id: number } } = await api.post("/api/v1/management/shift-parameters", {
          nome: `${turno.nome.trim()} ${faixa.rotulo}`,
          tipo: faixa.tipo,
          hora_inicio: inicio,
          hora_fim: fim,
          ativo: !expediente,
          ordem: ordemBase + indice + 1,
          turno_id: faixa.tipo === "expediente" ? null : turnoId,
        });
        if (faixa.tipo === "expediente") turnoId = resposta.item?.id ?? null;
      }
      setMensagem(expediente ? "Turno salvo desativado, porque já existe um expediente ativo." : "Turno salvo. O próximo ciclo já usa o novo horário.");
      setNovoTurno(null);
    } catch (reason) {
      setMensagem(reason instanceof ApiError && reason.status === 400 ? reason.message : "Não foi possível salvar o turno. Confira o nome e os horários informados.");
    } finally {
      setSalvando(false);
      query.reload();
    }
  }

  async function remover(turno: ShiftParameter) {
    setSalvando(true);
    try {
      await api.delete(`/api/v1/management/shift-parameters/${turno.id}`);
      setMensagem("Turno removido.");
      query.reload();
    } catch {
      setMensagem("Não foi possível remover o turno.");
    } finally {
      setSalvando(false);
    }
  }

  if (query.loading && !query.data) {
    return <PageFrame sectionId="dev" title={title} subtitle={subtitle} filters={false}><LoadingState /></PageFrame>;
  }
  if (query.error && !query.data) {
    return <PageFrame sectionId="dev" title={title} subtitle={subtitle} filters={false}><ErrorState error={query.error} onRetry={query.reload} /></PageFrame>;
  }

  return (
    <PageFrame staleError={query.error}
      sectionId="dev"
      title={title}
      subtitle={subtitle}
      filters={false}
      actions={<button type="button" className="button button--primary" onClick={() => setNovoTurno(NOVO_TURNO(String.fromCharCode(65 + new Set(items.map((item) => item.nome.replace(/ (H1|Oficial|H2|Fora de turno)$/, ""))).size % 26)))}>Novo turno</button>}
    >
      <div className="metric-grid metric-grid--four">
        <MetricCard
          label="Expediente"
          value={expediente ? `${hora(expediente.hora_inicio)}–${hora(expediente.hora_fim)}` : "Não configurado"}
          detail="Janela oficial"
          accent="primary"
        />
        <MetricCard label="Horas extras ativas" value={String(horasExtras.length)} detail={`de ${items.filter((item) => item.tipo === "hora_extra").length} cadastradas`} accent="warning" />
        <MetricCard label="Faixas fora de turno" value={String(foraTurno.length)} detail="Horários sem apontamento" accent="purple" />
        <MetricCard label="Turnos cadastrados" value={String(query.data?.count ?? 0)} accent="teal" />
      </div>

      <p className="operator-help">
        A hora extra que começa quando o expediente termina (ex.: H2, 17:30–21:30) fecha o
        apontamento sozinha nesse horário. A que termina quando o expediente começa (ex.: H1,
        06:00–08:00) não tem corte próprio: quem já estiver trabalhando ali continua visível e
        não vira "Sem demanda" quando o expediente abrir. A faixa "Fora de turno" (ex.: 21:30–06:00)
        informa o período em que ninguém trabalha: nele o recurso parado não conta como "Sem demanda".
      </p>

      {mensagem ? <Notice>{mensagem}</Notice> : null}

      <SectionCard
        title="Turnos configurados"
        className="content-section section-card--table"
        action={<span className="section-count">{items.length} turno(s)</span>}
      >
        {items.length ? (
          <DataTable
            rows={items}
            rowKey={(row) => row.id}
            columns={[
              { key: "ordem", label: "Ordem", render: (row) => row.ordem },
              { key: "nome", label: "Nome", render: (row) => row.nome },
              { key: "tipo", label: "Tipo", render: (row) => TIPOS.find((tipo) => tipo.value === row.tipo)?.label ?? row.tipo },
              { key: "inicio", label: "Início", render: (row) => hora(row.hora_inicio) },
              { key: "fim", label: "Fim", render: (row) => (viraODia(row) ? `${hora(row.hora_fim)} (dia seguinte)` : hora(row.hora_fim)) },
              { key: "estado", label: "Situação", render: (row) => <StatusBadge value={row.ativo ? "Ativo" : "Inativo"} /> },
              {
                key: "acoes",
                label: "Ações",
                render: (row) => (
                  <RowActions
                    label={row.nome}
                    disabled={salvando}
                    primary={{ label: "Editar", onClick: () => abrirEdicao(row) }}
                    actions={[
                      { label: row.ativo ? "Desativar" : "Ativar", danger: row.ativo, onClick: async () => { if (!row.ativo || await confirm({ title: "Desativar turno", message: `O turno "${row.nome}" deixa de abrir e fechar o apontamento a partir do próximo ciclo.`, confirmLabel: "Desativar turno", tone: "danger" })) void salvar({ ...row, ativo: !row.ativo }); } },
                      { label: "Remover", danger: true, onClick: async () => { if (await confirm({ title: "Remover turno", message: `O turno "${row.nome}" será removido. Esta ação não pode ser desfeita.`, confirmLabel: "Remover turno", tone: "danger" })) void remover(row); } },
                    ]}
                  />
                ),
              },
            ]}
          />
        ) : (
          <EmptyState title="Nenhum turno configurado" detail="Sem configuração, o sistema usa a janela oficial homologada (08:00–17:30, com H1 e H2)." />
        )}
      </SectionCard>

      {confirmDialog}
      {novoTurno ? (
        <OperatorDialog title="Novo turno" onCancel={() => (salvando ? undefined : setNovoTurno(null))}>
          <ValidatedForm className="pause-form pause-form--dialog" onValidSubmit={() => void salvarNovoTurno(novoTurno)}>
            <label>Nome do turno<Obrigatorio /><input value={novoTurno.nome} onChange={(event) => setNovoTurno({ ...novoTurno, nome: event.target.value })} required /></label>
            {FAIXAS.map((faixa) => {
              const valor = novoTurno.faixas[faixa.chave];
              const mudar = (campo: "inicio" | "fim", texto: string) =>
                setNovoTurno({ ...novoTurno, faixas: { ...novoTurno.faixas, [faixa.chave]: { ...valor, [campo]: texto } } });
              const opcional = faixa.tipo !== "expediente";
              const ligada = !opcional || valor.usar;
              return (
                <fieldset key={faixa.chave} className="pause-form__group">
                  <legend>{faixa.rotulo}</legend>
                  {opcional ? (
                    <label className="pause-form__check"><input type="checkbox" checked={valor.usar} onChange={(event) => setNovoTurno({ ...novoTurno, faixas: { ...novoTurno.faixas, [faixa.chave]: { ...valor, usar: event.target.checked } } })} />Este turno tem {faixa.rotulo}</label>
                  ) : null}
                  {ligada ? (
                    <>
                      <label>Início<Obrigatorio /><input type="time" value={valor.inicio} onChange={(event) => mudar("inicio", event.target.value)} required /></label>
                      <label>Fim<Obrigatorio /><input type="time" value={valor.fim} onChange={(event) => mudar("fim", event.target.value)} required /></label>
                      {viraODia({ hora_inicio: valor.inicio, hora_fim: valor.fim }) ? <p className="pause-form__hint" role="status">Termina no dia seguinte.</p> : null}
                    </>
                  ) : null}
                </fieldset>
              );
            })}
            {expediente ? <p className="pause-form__hint" role="status">Já existe um expediente ativo ({hora(expediente.hora_inicio)}–{hora(expediente.hora_fim)}). Este turno será salvo desativado.</p> : null}
            <div className="pause-form__actions">
              <button type="button" onClick={() => setNovoTurno(null)} disabled={salvando}>Cancelar</button>
              <button type="submit" className="button button--primary" disabled={salvando}>Salvar</button>
            </div>
          </ValidatedForm>
        </OperatorDialog>
      ) : null}
      {editando ? (
        <OperatorDialog
          title={editando.id ? "Editar turno" : "Novo turno"}
          onCancel={() => (salvando ? undefined : void fecharEdicao())}
        >
          <ValidatedForm className="pause-form pause-form--dialog" onValidSubmit={() => void salvar({ ...editando, id: editando.id || undefined })}>
            <label>Nome<Obrigatorio /><input value={editando.nome} onChange={(event) => setEditando({ ...editando, nome: event.target.value })} placeholder="H1, Oficial, H2, H3…" required /></label>
            <label>Tipo
              <select value={editando.tipo} onChange={(event) => setEditando({ ...editando, tipo: event.target.value as ShiftParameter["tipo"] })}>
                {TIPOS.map((tipo) => <option key={tipo.value} value={tipo.value}>{tipo.label}</option>)}
              </select>
            </label>
            {editando.tipo !== "expediente" ? (
              <label>Turno oficial<Obrigatorio />
                <select value={editando.turno_id ?? ""} onChange={(event) => setEditando({ ...editando, turno_id: event.target.value ? Number(event.target.value) : null })} required>
                  <option value="">Escolha o turno…</option>
                  {turnosOficiais.map((oficial) => <option key={oficial.id} value={oficial.id}>{oficial.nome} ({hora(oficial.hora_inicio)}–{hora(oficial.hora_fim)})</option>)}
                </select>
              </label>
            ) : null}
            <label>Início<Obrigatorio /><input type="time" value={hora(editando.hora_inicio)} onChange={(event) => setEditando({ ...editando, hora_inicio: event.target.value })} required /></label>
            <label>Fim<Obrigatorio /><input type="time" value={hora(editando.hora_fim)} onChange={(event) => setEditando({ ...editando, hora_fim: event.target.value })} required /></label>
            {viraODia(editando) ? <p className="pause-form__hint" role="status">Termina no dia seguinte: {hora(editando.hora_inicio)} de um dia até {hora(editando.hora_fim)} do outro.</p> : null}
            <label>Ordem<input type="number" min={1} max={99} value={editando.ordem} onChange={(event) => setEditando({ ...editando, ordem: Number(event.target.value) || 1 })} /></label>
            <label className="pause-form__check"><input type="checkbox" checked={editando.ativo} onChange={(event) => setEditando({ ...editando, ativo: event.target.checked })} />Ativo</label>
            <div className="pause-form__actions">
              <button type="button" onClick={() => void fecharEdicao()}>Cancelar</button>
              <button type="submit" className="button button--primary" disabled={salvando}>Salvar</button>
            </div>
          </ValidatedForm>
        </OperatorDialog>
      ) : null}
    </PageFrame>
  );
}
