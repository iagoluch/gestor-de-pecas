import { useId, useMemo, useState } from "react";
import { api } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { DataTable } from "../../components/DataTable";
import { RowActions } from "../../components/RowActions";
import { ErrorState, LoadingState } from "../../components/DataState";
import { MetricCard } from "../../components/MetricCard";
import { OperatorDialog } from "../../components/OperatorDialog";
import { Obrigatorio, ValidatedForm } from "../../components/ValidatedForm";
import { PageFrame } from "../../components/PageFrame";
import { RecordToolbar } from "../../components/RecordToolbar";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import { useApiQuery } from "../../hooks/useApiQuery";
import { usePersistentFilters } from "../../hooks/usePersistentFilters";
import { Notice } from "../../components/Notice";
import { useConfirm } from "../../components/ConfirmDialog";
import { useDraft } from "../../hooks/useDraft";

interface ChamadaContato {
  id: number;
  nome: string;
  funcao: string;
  ativo: boolean;
  padrao_gestao: boolean;
  telegram_chat_id?: string | null;
  setores?: string[];
}

const NOVO: ChamadaContato = { id: 0, nome: "", funcao: "", ativo: true, padrao_gestao: false, telegram_chat_id: "", setores: [] };

const FILTROS_INICIAIS = { situacao: "", busca: "" };

/**
 * Cadastro de quem pode ser chamado pelo botão de chamada (operador e
 * gestão). É exclusivo da conta admin (IagoDev); o histórico do que já foi
 * chamado vive na aba "Chamadas da Gestão" (ChamadasPage). A lista fica aqui —
 * nunca no Dev Observatory, que é somente leitura de propósito.
 */
export function DevChamadasContatosPage() {
  const contatosQuery = useApiQuery<{ items: ChamadaContato[] }>("/api/v1/chamadas/admin/contatos");
  const setoresQuery = useApiQuery<{ items: string[] }>("/api/v1/chamadas/setores");
  const setoresDisponiveis = setoresQuery.data?.items ?? [];
  const [mensagem, setMensagem] = useState("");
  const [salvando, setSalvando] = useState(false);
  const [confirm, confirmDialog] = useConfirm();
  const [editando, setEditando, abrirEdicao, fecharEdicao] = useDraft<ChamadaContato>(confirm);
  const telegramHintId = useId();
  const filtros = usePersistentFilters("gestor.filtros.chamada-contatos", FILTROS_INICIAIS);

  const contatos = useMemo(() => contatosQuery.data?.items ?? [], [contatosQuery.data]);
  const title = "IagoDev — Chamadas do IagoDev";
  const subtitle = "Contatos de quem pode ser chamado pelo botão de chamada.";

  const filtrados = useMemo(() => {
    const busca = filtros.values.busca.trim().toLocaleLowerCase("pt-BR");
    return contatos
      .filter((item) => !filtros.values.situacao || (filtros.values.situacao === "ativo" ? item.ativo : !item.ativo))
      .filter((item) => !busca || `${item.nome} ${item.funcao}`.toLocaleLowerCase("pt-BR").includes(busca))
      .sort((left, right) => left.nome.localeCompare(right.nome, "pt-BR"));
  }, [contatos, filtros.values]);

  async function salvar(contato: Partial<ChamadaContato>) {
    setSalvando(true);
    setMensagem("");
    try {
      await api.post("/api/v1/chamadas/admin/contatos", {
        id: contato.id || null,
        nome: contato.nome,
        funcao: contato.funcao,
        ativo: contato.ativo ?? true,
        padrao_gestao: contato.padrao_gestao ?? false,
        telegram_chat_id: contato.telegram_chat_id?.trim() || null,
        setores: contato.setores ?? [],
      });
      setMensagem("Contato salvo.");
      setEditando(null);
      contatosQuery.reload();
    } catch {
      setMensagem("Não foi possível salvar o contato. Confira o nome e a função.");
    } finally {
      setSalvando(false);
    }
  }

  async function remover(id: number) {
    setSalvando(true);
    try {
      await api.delete(`/api/v1/chamadas/admin/contatos/${id}`);
      contatosQuery.reload();
    } catch {
      setMensagem("Não foi possível remover o contato.");
    } finally {
      setSalvando(false);
    }
  }

  if (contatosQuery.loading && !contatosQuery.data) {
    return (
      <PageFrame sectionId="dev" title={title} subtitle={subtitle} filters={false}>
        <LoadingState />
      </PageFrame>
    );
  }
  const erroAtualizacao = contatosQuery.error;
  if (erroAtualizacao && !contatosQuery.data) {
    return (
      <PageFrame sectionId="dev" title={title} subtitle={subtitle} filters={false}>
        <ErrorState error={erroAtualizacao} onRetry={contatosQuery.reload} />
      </PageFrame>
    );
  }

  const ativos = contatos.filter((item) => item.ativo).length;

  return (
    <PageFrame
      sectionId="dev"
      title={title}
      subtitle={subtitle}
      filters={false}
      staleError={erroAtualizacao}
      actions={
        <button type="button" className="button button--primary" onClick={() => abrirEdicao({ ...NOVO })}>
          Novo contato
        </button>
      }
    >
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Contatos ativos" value={String(ativos)} detail={`${contatos.length} cadastrados`} accent="primary" />
        <MetricCard label="Sem contato cadastrado" value={contatos.length ? "Não" : "Sim"} detail="Sem contato, o botão de chamada fica vazio" accent={contatos.length ? "teal" : "danger"} />
      </div>

      {mensagem ? <Notice>{mensagem}</Notice> : null}

      <RecordToolbar
        ariaLabel="Filtros dos contatos de chamada"
        selects={[
          {
            id: "chamada-contatos-situacao",
            label: "Situação",
            allLabel: "Todas as situações",
            value: filtros.values.situacao,
            options: [
              { value: "ativo", label: "Ativo", count: ativos },
              { value: "inativo", label: "Inativo", count: contatos.length - ativos },
            ],
            onChange: (value) => filtros.set("situacao", value),
          },
        ]}
        search={{
          value: filtros.values.busca,
          onChange: (value) => filtros.set("busca", value),
          placeholder: "Buscar por nome ou função",
        }}
        summary={filtros.active ? `${filtrados.length} de ${contatos.length} contatos no recorte atual` : `${contatos.length} contatos cadastrados`}
        onReset={filtros.reset}
        resetDisabled={!filtros.active}
      />

      <SectionCard
        title="Contatos cadastrados"
        className="content-section section-card--table"
        action={<span className="section-count">{filtrados.length} contato(s)</span>}
      >
        <DataTable
          rows={filtrados}
          rowKey={(row) => row.id}
          emptyTitle="Nenhum contato cadastrado ainda"
          columns={[
            { key: "nome", label: "Nome", render: (row) => row.nome },
            { key: "funcao", label: "Função", render: (row) => row.funcao },
            { key: "situacao", label: "Situação", render: (row) => <StatusBadge value={row.ativo ? "Ativo" : "Inativo"} /> },
            {
              key: "padrao",
              label: "Padrão da gestão",
              render: (row) => (row.padrao_gestao ? <StatusBadge value="Padrão" /> : "—"),
            },
            {
              key: "telegram",
              label: "Telegram",
              render: (row) => (
                row.telegram_chat_id
                  ? <StatusBadge value="Configurado" />
                  : <span className="section-count">Usa o chat geral</span>
              ),
            },
            {
              key: "setores",
              label: "Setores",
              render: (row) => (
                row.setores?.length ? row.setores.join(", ") : <span className="section-count">Todos os setores</span>
              ),
            },
            {
              key: "acoes",
              label: "Ações",
              render: (row) => (
                <RowActions
                  label={row.nome}
                  disabled={salvando}
                  primary={{ label: "Editar", onClick: () => abrirEdicao(row) }}
                  actions={[
                    ...(row.padrao_gestao ? [] : [{ label: "Tornar padrão da gestão", onClick: () => void salvar({ ...row, padrao_gestao: true }) }]),
                    { label: row.ativo ? "Desativar" : "Ativar", danger: row.ativo, onClick: async () => { if (!row.ativo || await confirm({ title: "Desativar contato", message: `${row.nome} deixa de receber as chamadas até ser ativado de novo.`, confirmLabel: "Desativar contato", tone: "danger" })) void salvar({ ...row, ativo: !row.ativo }); } },
                    { label: "Remover", danger: true, onClick: async () => { if (await confirm({ title: "Remover contato", message: `${row.nome} será removido dos contatos de chamada. Esta ação não pode ser desfeita.`, confirmLabel: "Remover contato", tone: "danger" })) void remover(row.id); } },
                  ]}
                />
              ),
            },
          ]}
        />
      </SectionCard>

      {editando ? (
        <OperatorDialog
          title={editando.id ? "Editar contato" : "Novo contato"}
          onCancel={() => (salvando ? undefined : void fecharEdicao())}
        >
          <ValidatedForm className="pause-form pause-form--dialog" onValidSubmit={() => void salvar(editando)}>
            <label>
              Nome
              <Obrigatorio />
              <input
                value={editando.nome}
                onChange={(event) => setEditando({ ...editando, nome: event.target.value })}
                required
              />
            </label>
            <label>
              Função
              <Obrigatorio />
              <input
                value={editando.funcao}
                onChange={(event) => setEditando({ ...editando, funcao: event.target.value })}
                placeholder="Ex.: Líder, Supervisor, Manutenção…"
                required
              />
            </label>
            <label className="pause-form__wide">
              ID do Telegram (opcional)
              <input
                value={editando.telegram_chat_id ?? ""}
                onChange={(event) => setEditando({ ...editando, telegram_chat_id: event.target.value })}
                placeholder="Ex.: 123456789"
                inputMode="numeric"
                aria-describedby={telegramHintId}
              />
            </label>
            <p id={telegramHintId} className="pause-form__hint pause-form__wide">
              É um número, não o @usuário: a pessoa manda qualquer mensagem para <strong>@userinfobot</strong> no
              Telegram e ele responde com o “Id”. Em branco, a chamada vai para o chat geral do ambiente.
            </p>
            <fieldset className="chamada-setores pause-form__wide">
              <legend>Setores em que aparece</legend>
              <p className="operator-help">Nenhum setor marcado = aparece para todos os setores.</p>
              <div className="chamada-setores__grid">
                {setoresDisponiveis.map((nomeSetor) => {
                  const marcado = (editando.setores ?? []).includes(nomeSetor);
                  return (
                    <label key={nomeSetor} className="pause-form__check">
                      <input
                        type="checkbox"
                        checked={marcado}
                        onChange={(event) => {
                          const atuais = editando.setores ?? [];
                          const proximos = event.target.checked
                            ? [...atuais, nomeSetor]
                            : atuais.filter((item) => item !== nomeSetor);
                          setEditando({ ...editando, setores: proximos });
                        }}
                      />
                      {nomeSetor}
                    </label>
                  );
                })}
              </div>
            </fieldset>
            <label className="pause-form__check">
              <input
                type="checkbox"
                checked={editando.ativo}
                onChange={(event) => setEditando({ ...editando, ativo: event.target.checked })}
              />
              Ativo
            </label>
            <label className="pause-form__check">
              <input
                type="checkbox"
                checked={editando.padrao_gestao}
                onChange={(event) => setEditando({ ...editando, padrao_gestao: event.target.checked })}
              />
              Padrão da tela de gestão (pré-selecionado no botão de chamada)
            </label>
            <div className="pause-form__actions">
              <button type="button" onClick={() => void fecharEdicao()}>Cancelar</button>
              <button
                type="submit"
                className="button button--primary"
                disabled={salvando}
              >
                Salvar
              </button>
            </div>
          </ValidatedForm>
        </OperatorDialog>
      ) : null}
      {confirmDialog}
    </PageFrame>
  );
}
