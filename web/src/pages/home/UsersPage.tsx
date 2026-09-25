import { useMemo, useState } from "react";
import { api, ApiError } from "../../api/client";
import { DataTable } from "../../components/DataTable";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { MetricCard } from "../../components/MetricCard";
import { OperatorDialog } from "../../components/OperatorDialog";
import { Obrigatorio, ValidatedForm } from "../../components/ValidatedForm";
import { PageFrame } from "../../components/PageFrame";
import { RecordToolbar } from "../../components/RecordToolbar";
import { SectionCard } from "../../components/SectionCard";
import { StatusBadge } from "../../components/StatusBadge";
import { useApiQuery } from "../../hooks/useApiQuery";
import { usePersistentFilters } from "../../hooks/usePersistentFilters";
import { humanize } from "../../utils/format";
import { Notice } from "../../components/Notice";
import { useConfirm } from "../../components/ConfirmDialog";
import { useDraft } from "../../hooks/useDraft";
import { useAuth } from "../../auth/AuthContext";

interface UserAccount {
  id: number;
  nome: string;
  nivel: string;
  ativo: boolean;
  data_criacao?: string | null;
}

interface UsersResponse {
  items: UserAccount[];
  count: number;
  active: number;
  levels: string[];
}

interface EditState {
  id: number | null;
  nome: string;
  nivel: string;
  ativo: boolean;
  senha: string;
}

const FILTROS_INICIAIS = { situacao: "", nivel: "", busca: "" };
// Mesma regra do backend (user_self_lockout): o admin não tira o próprio acesso.
const PROPRIA_CONTA = "Sua própria conta: peça a outro administrador para desativar ou rebaixar.";

/**
 * Cadastro de usuários — exclusivo da conta admin (decisão do usuário,
 * 14/09/2026). É aqui, na tela normal de login que os funcionários usam, e
 * não no Dev Observatory, que é somente leitura de propósito.
 */
export function ManagementUsersPage() {
  const query = useApiQuery<UsersResponse>("/api/v1/management/users");
  const [mensagem, setMensagem] = useState("");
  const [erro, setErro] = useState("");
  const [salvando, setSalvando] = useState(false);
  const filtros = usePersistentFilters("gestor.filtros.usuarios", FILTROS_INICIAIS);
  const { user } = useAuth();
  const [confirm, confirmDialog] = useConfirm();
  const [editando, setEditando, abrirEdicao, fecharEdicao] = useDraft<EditState>(confirm);

  const items = useMemo(() => query.data?.items ?? [], [query.data]);
  const niveis = query.data?.levels ?? [];
  const title = "IagoDev — Cadastro";
  const subtitle = "Login de quem acessa o sistema — a mesma tela que os funcionários usam para entrar.";

  const filtrados = useMemo(() => {
    const busca = filtros.values.busca.trim().toLocaleLowerCase("pt-BR");
    return items
      .filter((item) => !filtros.values.situacao || (filtros.values.situacao === "ativo" ? item.ativo : !item.ativo))
      .filter((item) => !filtros.values.nivel || item.nivel === filtros.values.nivel)
      .filter((item) => !busca || item.nome.toLocaleLowerCase("pt-BR").includes(busca))
      .sort((left, right) => left.nome.localeCompare(right.nome, "pt-BR"));
  }, [items, filtros.values]);

  async function alternarSituacao(row: UserAccount) {
    const desativar = row.ativo;
    const confirmado = await confirm({
      title: desativar ? "Desativar usuário" : "Ativar usuário",
      message: desativar
        ? `${row.nome} deixa de conseguir entrar no sistema até ser ativado de novo.`
        : `${row.nome} volta a conseguir entrar no sistema.`,
      confirmLabel: desativar ? "Desativar usuário" : "Ativar usuário",
      tone: desativar ? "danger" : "primary",
    });
    if (confirmado) await salvar({ id: row.id, nome: row.nome, nivel: row.nivel, ativo: !row.ativo, senha: "" });
  }

  async function salvar(estado: EditState) {
    setSalvando(true);
    setErro("");
    setMensagem("");
    try {
      await api.post("/api/v1/management/users", {
        id: estado.id,
        nome: estado.nome,
        nivel: estado.nivel,
        ativo: estado.ativo,
        senha: estado.senha.trim() || null,
      });
      setMensagem(estado.id ? "Usuário atualizado." : "Usuário criado.");
      setEditando(null);
      query.reload();
    } catch (reason) {
      setErro(reason instanceof ApiError ? reason.message : "Não foi possível salvar o usuário.");
    } finally {
      setSalvando(false);
    }
  }

  if (query.loading && !query.data) {
    return (
      <PageFrame sectionId="dev" title={title} subtitle={subtitle} filters={false}>
        <LoadingState />
      </PageFrame>
    );
  }
  if (query.error && !query.data) {
    return (
      <PageFrame sectionId="dev" title={title} subtitle={subtitle} filters={false}>
        <ErrorState error={query.error} onRetry={query.reload} />
      </PageFrame>
    );
  }

  const ativos = query.data?.active ?? 0;
  const admins = items.filter((item) => item.nivel === "admin").length;

  return (
    <PageFrame staleError={query.error}
      sectionId="dev"
      title={title}
      subtitle={subtitle}
      filters={false}
      actions={
        <button
          type="button"
          className="button button--primary"
          onClick={() => abrirEdicao({ id: null, nome: "", nivel: "operador_destaque", ativo: true, senha: "" })}
        >
          Novo usuário
        </button>
      }
    >
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Usuários ativos" value={String(ativos)} detail={`${items.length} cadastrados`} accent="primary" />
        <MetricCard label="Contas admin" value={String(admins)} detail="Acesso total, incluindo Cadastro" accent="teal" />
        <MetricCard label="Inativos" value={String(items.length - ativos)} accent="warning" />
        <MetricCard label="Sem conta admin" value={admins > 0 ? "Não" : "Sim"} detail="Sem conta admin, ninguém gerencia usuários nem contatos de chamada" accent={admins > 0 ? "teal" : "danger"} />
      </div>

      {mensagem ? <Notice>{mensagem}</Notice> : null}
      {erro ? <Notice tone="error">{erro}</Notice> : null}

      <RecordToolbar
        ariaLabel="Filtros dos usuários"
        selects={[
          {
            id: "usuarios-situacao",
            label: "Situação",
            allLabel: "Todas as situações",
            value: filtros.values.situacao,
            options: [
              { value: "ativo", label: "Ativo", count: ativos },
              { value: "inativo", label: "Inativo", count: items.length - ativos },
            ],
            onChange: (value) => filtros.set("situacao", value),
          },
          {
            id: "usuarios-nivel",
            label: "Nível",
            allLabel: "Todos os níveis",
            value: filtros.values.nivel,
            options: niveis.map((nivel) => ({
              value: nivel,
              label: humanize(nivel),
              count: items.filter((item) => item.nivel === nivel).length,
            })),
            onChange: (value) => filtros.set("nivel", value),
          },
        ]}
        search={{
          value: filtros.values.busca,
          onChange: (value) => filtros.set("busca", value),
          placeholder: "Buscar por nome",
        }}
        summary={filtros.active ? `${filtrados.length} de ${items.length} usuários no recorte atual` : `${items.length} usuários cadastrados`}
        onReset={filtros.reset}
        resetDisabled={!filtros.active}
      />

      <SectionCard
        title="Usuários cadastrados"
        className="content-section section-card--table"
        action={<span className="section-count">{filtrados.length} usuário(s)</span>}
      >
        {filtrados.length ? (
          <DataTable
            rows={filtrados}
            rowKey={(row) => row.id}
            columns={[
              { key: "nome", label: "Nome", render: (row) => row.nome },
              { key: "nivel", label: "Nível", render: (row) => humanize(row.nivel) },
              { key: "situacao", label: "Situação", render: (row) => <StatusBadge value={row.ativo ? "Ativo" : "Inativo"} /> },
              {
                key: "acoes",
                label: "Ações",
                render: (row) => (
                  <span className="pause-actions">
                    <button
                      type="button"
                      disabled={salvando}
                      onClick={() => abrirEdicao({ id: row.id, nome: row.nome, nivel: row.nivel, ativo: row.ativo, senha: "" })}
                    >
                      Editar
                    </button>
                    <button
                      type="button"
                      disabled={salvando || (row.id === user?.id && row.ativo)}
                      title={row.id === user?.id && row.ativo ? PROPRIA_CONTA : undefined}
                      onClick={() => void alternarSituacao(row)}
                    >
                      {row.ativo ? "Desativar" : "Ativar"}
                    </button>
                  </span>
                ),
              },
            ]}
          />
        ) : items.length ? (
          <EmptyState title="Nenhum usuário no filtro atual" detail="Ajuste a situação, o nível ou a busca para ver os usuários cadastrados." />
        ) : (
          <EmptyState title="Nenhum usuário cadastrado" detail="Crie o primeiro usuário para liberar o acesso ao sistema." />
        )}
      </SectionCard>

      {editando ? (
        <OperatorDialog
          title={editando.id ? "Editar usuário" : "Novo usuário"}
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
              Nível de acesso
              <select value={editando.nivel} disabled={editando.id === user?.id} onChange={(event) => setEditando({ ...editando, nivel: event.target.value })}>
                {niveis.map((nivel) => (
                  <option key={nivel} value={nivel}>{humanize(nivel)}</option>
                ))}
              </select>
            </label>
            <label>
              {editando.id ? "Nova senha (deixe em branco para manter a atual)" : "Senha"}
              {editando.id ? null : <Obrigatorio />}
              <input
                type="password"
                value={editando.senha}
                onChange={(event) => setEditando({ ...editando, senha: event.target.value })}
                placeholder={editando.id ? "Deixe em branco para manter" : "Mínimo de 6 caracteres"}
                required={!editando.id}
                minLength={6}
              />
            </label>
            <label className="pause-form__check">
              <input
                type="checkbox"
                checked={editando.ativo}
                disabled={editando.id === user?.id}
                onChange={(event) => setEditando({ ...editando, ativo: event.target.checked })}
              />
              Ativo
            </label>
            {editando.id === user?.id ? <Notice>{PROPRIA_CONTA}</Notice> : null}
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
