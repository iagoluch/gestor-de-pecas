import { useMemo, useState } from "react";
import { api } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { DataTable } from "../../components/DataTable";
import { ErrorState, LoadingState } from "../../components/DataState";
import { MetricCard } from "../../components/MetricCard";
import { OperatorDialog } from "../../components/OperatorDialog";
import { PageFrame } from "../../components/PageFrame";
import { RecordToolbar } from "../../components/RecordToolbar";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import { useApiQuery } from "../../hooks/useApiQuery";
import { usePersistentFilters } from "../../hooks/usePersistentFilters";
import { Notice } from "../../components/Notice";
import { useConfirm } from "../../components/ConfirmDialog";

interface ChamadaContato {
  id: number;
  nome: string;
  funcao: string;
  ativo: boolean;
  padrao_gestao: boolean;
  telegram_chat_id?: string | null;
  setores?: string[];
}

interface Chamada {
  id: number;
  contato_nome: string;
  contato_funcao: string;
  motivo: string;
  comentario: string;
  solicitante_nome: string;
  solicitante_nivel: string;
  solicitante_cracha: string | null;
  solicitante_email: string | null;
  telegram_enviado: boolean;
  criado_em: string;
}

const NOVO: ChamadaContato = { id: 0, nome: "", funcao: "", ativo: true, padrao_gestao: false, telegram_chat_id: "", setores: [] };

const FILTROS_INICIAIS = { situacao: "", busca: "" };

/**
 * Contatos de quem pode ser chamado pelo botão de chamada (operador e
 * gestão) e o histórico do que já foi chamado. A lista fica aqui — nunca no
 * Dev Observatory, que é somente leitura de propósito.
 */
export function ManagementChamadasPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  // Gestão comum nem tenta buscar os contatos: o endpoint é exclusivo do
  // admin (decisão do usuário, 14/09/2026) e passar ``null`` evita uma
  // chamada que só voltaria 403.
  const contatosQuery = useApiQuery<{ items: ChamadaContato[] }>(
    isAdmin ? "/api/v1/chamadas/admin/contatos" : null,
  );
  const historicoQuery = useApiQuery<{ items: Chamada[] }>("/api/v1/chamadas/admin/historico");
  const setoresQuery = useApiQuery<{ items: string[] }>(isAdmin ? "/api/v1/chamadas/setores" : null);
  const setoresDisponiveis = setoresQuery.data?.items ?? [];
  const [editando, setEditando] = useState<ChamadaContato | null>(null);
  const [mensagem, setMensagem] = useState("");
  const [salvando, setSalvando] = useState(false);
  const [confirm, confirmDialog] = useConfirm();
  const filtros = usePersistentFilters("gestor.filtros.chamada-contatos", FILTROS_INICIAIS);

  const contatos = useMemo(() => contatosQuery.data?.items ?? [], [contatosQuery.data]);
  const historico = historicoQuery.data?.items ?? [];
  const title = "Chamadas";
  const subtitle = isAdmin
    ? "Contatos de quem pode ser chamado e o histórico de chamadas."
    : "Histórico de chamadas do operador e da gestão.";

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

  const carregando = historicoQuery.loading && !historicoQuery.data
    || (isAdmin && contatosQuery.loading && !contatosQuery.data);
  if (carregando) {
    return (
      <PageFrame sectionId="dev" title={title} subtitle={subtitle} filters={false}>
        <LoadingState />
      </PageFrame>
    );
  }
  const erroAtualizacao = historicoQuery.error ?? (isAdmin ? contatosQuery.error : null);
  const semDados = !historicoQuery.data || (isAdmin && !contatosQuery.data);
  const erroCarregamento = semDados ? erroAtualizacao : null;
  if (erroCarregamento) {
    return (
      <PageFrame sectionId="dev" title={title} subtitle={subtitle} filters={false}>
        <ErrorState error={erroCarregamento} onRetry={() => { historicoQuery.reload(); contatosQuery.reload(); }} />
      </PageFrame>
    );
  }

  const ativos = contatos.filter((item) => item.ativo).length;
  const semTelegram = historico.filter((item) => !item.telegram_enviado).length;

  return (
    <PageFrame
      sectionId="dev"
      title={title}
      subtitle={subtitle}
      filters={false}
      staleError={erroAtualizacao}
      actions={
        isAdmin ? (
          <button type="button" className="button button--primary" onClick={() => setEditando({ ...NOVO })}>
            Novo contato
          </button>
        ) : undefined
      }
    >
      <div className="metric-grid metric-grid--four">
        {isAdmin ? (
          <MetricCard label="Contatos ativos" value={String(ativos)} detail={`${contatos.length} cadastrados`} accent="primary" />
        ) : null}
        <MetricCard label="Chamadas registradas" value={String(historico.length)} detail="Últimas 200" accent="teal" />
        <MetricCard
          label="Sem aviso no Telegram"
          value={String(semTelegram)}
          detail="Não configurado ou falha no envio"
          accent={semTelegram ? "warning" : "success"}
        />
        {isAdmin ? (
          <MetricCard label="Sem contato cadastrado" value={contatos.length ? "Não" : "Sim"} detail="Sem contato, o botão de chamada fica vazio" accent={contatos.length ? "teal" : "danger"} />
        ) : null}
      </div>

      {mensagem ? <Notice>{mensagem}</Notice> : null}

      {isAdmin ? (
        <>
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
                    <span className="pause-actions">
                      <button type="button" disabled={salvando} onClick={() => setEditando(row)}>Editar</button>
                      <button type="button" disabled={salvando} onClick={async () => { if (!row.ativo || await confirm({ title: "Desativar contato", message: `${row.nome} deixa de receber as chamadas até ser ativado de novo.`, confirmLabel: "Desativar contato", tone: "danger" })) void salvar({ ...row, ativo: !row.ativo }); }}>
                        {row.ativo ? "Desativar" : "Ativar"}
                      </button>
                      {row.padrao_gestao ? null : (
                        <button type="button" disabled={salvando} onClick={() => void salvar({ ...row, padrao_gestao: true })}>
                          Tornar padrão da gestão
                        </button>
                      )}
                      <button type="button" disabled={salvando} onClick={async () => { if (await confirm({ title: "Remover contato", message: `${row.nome} será removido dos contatos de chamada. Esta ação não pode ser desfeita.`, confirmLabel: "Remover contato", tone: "danger" })) void remover(row.id); }}>Remover</button>
                    </span>
                  ),
                },
              ]}
            />
          </SectionCard>
        </>
      ) : null}

      <SectionCard
        title="Últimas chamadas"
        className="content-section section-card--table"
        action={<span className="section-count">{historico.length} chamada(s)</span>}
      >
        <DataTable
          rows={historico}
          rowKey={(row) => row.id}
          emptyTitle="Nenhuma chamada registrada ainda"
          columns={[
            { key: "quando", label: "Quando", render: (row) => new Date(row.criado_em).toLocaleString("pt-BR") },
            { key: "para", label: "Para", render: (row) => `${row.contato_nome} (${row.contato_funcao})` },
            { key: "motivo", label: "Motivo", render: (row) => row.motivo },
            { key: "comentario", label: "Comentário", render: (row) => row.comentario },
            {
              key: "quem",
              label: "Solicitado por",
              render: (row) => (
                <span>
                  {row.solicitante_nome}
                  {row.solicitante_cracha ? <small> · crachá {row.solicitante_cracha}</small> : null}
                  {row.solicitante_email ? <small> · {row.solicitante_email}</small> : null}
                </span>
              ),
            },
            {
              key: "aviso",
              label: "Aviso",
              render: (row) => <StatusBadge value={row.telegram_enviado ? "Enviado" : "Não enviado"} />,
            },
          ]}
        />
      </SectionCard>

      {isAdmin && editando ? (
        <OperatorDialog
          title={editando.id ? "Editar contato" : "Novo contato"}
          onCancel={() => (salvando ? undefined : setEditando(null))}
        >
          <form
            className="pause-form pause-form--dialog"
            onSubmit={(event) => {
              event.preventDefault();
              void salvar(editando);
            }}
          >
            <label>
              Nome
              <input
                value={editando.nome}
                onChange={(event) => setEditando({ ...editando, nome: event.target.value })}
                required
              />
            </label>
            <label>
              Função
              <input
                value={editando.funcao}
                onChange={(event) => setEditando({ ...editando, funcao: event.target.value })}
                placeholder="Ex.: Líder, Supervisor, Manutenção…"
                required
              />
            </label>
            <label>
              Telegram do contato (opcional)
              <input
                value={editando.telegram_chat_id ?? ""}
                onChange={(event) => setEditando({ ...editando, telegram_chat_id: event.target.value })}
                placeholder="Ex.: 123456789 — deixe em branco para usar o chat geral"
                inputMode="numeric"
              />
            </label>
            <p className="operator-help">
              <strong>Como conseguir o ID:</strong> é um número, não o @usuário do Telegram.
              A pessoa abre o Telegram, procura <strong>@userinfobot</strong>, manda qualquer
              mensagem pra ele, e ele responde com o "Id" numérico dela — é esse número que
              vai aqui. Sem preencher, a chamada desse contato continua indo pro chat geral
              já configurado no ambiente.
            </p>
            <fieldset className="chamada-setores">
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
              <button type="button" onClick={() => setEditando(null)}>Cancelar</button>
              <button
                type="submit"
                className="button button--primary"
                disabled={salvando || !editando.nome.trim() || !editando.funcao.trim()}
              >
                Salvar
              </button>
            </div>
          </form>
        </OperatorDialog>
      ) : null}
      {confirmDialog}
    </PageFrame>
  );
}
