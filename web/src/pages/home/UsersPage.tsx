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
  /** Nível gravado na conta (o personalizado, se houver); `nivel` é o efetivo. */
  nivel_atribuido?: string;
  nivel_rotulo?: string | null;
  unidade?: string | null;
  /** Tela onde a pessoa entra: gestão, apontamento ou outra (Andon/Almoxarifado). */
  tela?: "gestao" | "apontamento" | "outro";
  ativo: boolean;
  data_criacao?: string | null;
}

interface CustomLevel {
  nome: string;
  rotulo: string;
  nivel_base: string;
}

interface UsersResponse {
  items: UserAccount[];
  count: number;
  active: number;
  levels: string[];
  custom_levels?: CustomLevel[];
  unassignable_levels?: string[];
}

interface EditState {
  id: number | null;
  nome: string;
  nivel: string;
  unidade: string;
  ativo: boolean;
  senha: string;
}

const FILTROS_INICIAIS = { situacao: "", nivel: "", unidade: "", tela: "", busca: "" };
// Mesma regra do backend (user_self_lockout): o admin não tira o próprio acesso.
const TELAS = [
  { value: "gestao", label: "Gestão" },
  { value: "apontamento", label: "Apontamento" },
  { value: "outro", label: "Outras (Andon/Almoxarifado)" },
];
const SEM_UNIDADE = "__sem";
const PROPRIA_CONTA = "Sua própria conta: peça a outro administrador para desativar ou rebaixar.";
const PROPRIA_CONTA_EXCLUIR = "Sua própria conta: peça a outro administrador para excluir.";

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
  const personalizados = query.data?.custom_levels ?? [];
  const niveisBase = niveis.filter((nivel) => nivel !== "admin" && !personalizados.some((item) => item.nome === nivel));
  const rotuloNivel = (nivel: string) => personalizados.find((item) => item.nome === nivel)?.rotulo ?? humanize(nivel);
  const [novoNivel, setNovoNivel] = useState<{ rotulo: string; nivel_base: string } | null>(null);
  const unidades = useMemo(
    () => [...new Set(items.map((item) => item.unidade).filter((unidade): unidade is string => Boolean(unidade)))]
      .sort((left, right) => left.localeCompare(right, "pt-BR", { numeric: true })),
    [items],
  );
  const title = "IagoDev — Cadastro";
  const subtitle = "Login de quem acessa o sistema — a mesma tela que os funcionários usam para entrar.";

  const filtrados = useMemo(() => {
    const busca = filtros.values.busca.trim().toLocaleLowerCase("pt-BR");
    return items
      .filter((item) => !filtros.values.situacao || (filtros.values.situacao === "ativo" ? item.ativo : !item.ativo))
      .filter((item) => !filtros.values.nivel || (item.nivel_atribuido ?? item.nivel) === filtros.values.nivel)
      .filter((item) => !filtros.values.unidade || (filtros.values.unidade === SEM_UNIDADE ? !item.unidade : item.unidade === filtros.values.unidade))
      .filter((item) => !filtros.values.tela || item.tela === filtros.values.tela)
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
    if (confirmado) await salvar({ id: row.id, nome: row.nome, nivel: row.nivel_atribuido ?? row.nivel, unidade: row.unidade ?? "", ativo: !row.ativo, senha: "" });
  }

  async function excluir(row: UserAccount) {
    const confirmado = await confirm({
      title: "Excluir usuário",
      message: `${row.nome} será apagado de vez e não consegue mais entrar. As conversas com a IA, os relatórios e os agendamentos dessa conta também são apagados. Não dá para desfazer. Se só quer bloquear o acesso, use Desativar.`,
      confirmLabel: "Excluir usuário",
      tone: "danger",
    });
    if (!confirmado) return;
    setSalvando(true);
    setErro("");
    setMensagem("");
    try {
      await api.delete(`/api/v1/management/users/${row.id}`);
      setMensagem("Usuário excluído.");
      query.reload();
    } catch (reason) {
      setErro(reason instanceof ApiError ? reason.message : "Não foi possível excluir o usuário.");
    } finally {
      setSalvando(false);
    }
  }

  async function criarNivel(estado: { rotulo: string; nivel_base: string }) {
    setSalvando(true);
    setErro("");
    setMensagem("");
    try {
      await api.post("/api/v1/management/levels", estado);
      setMensagem("Nível criado.");
      setNovoNivel(null);
      query.reload();
    } catch (reason) {
      setErro(reason instanceof ApiError ? reason.message : "Não foi possível criar o nível.");
    } finally {
      setSalvando(false);
    }
  }

  async function excluirNivel(nivel: CustomLevel) {
    const confirmado = await confirm({
      title: "Excluir nível",
      message: `O nível ${nivel.rotulo} deixa de existir. Só dá para excluir se nenhuma conta estiver usando.`,
      confirmLabel: "Excluir nível",
      tone: "danger",
    });
    if (!confirmado) return;
    setSalvando(true);
    setErro("");
    setMensagem("");
    try {
      await api.delete(`/api/v1/management/levels/${nivel.nome}`);
      setMensagem("Nível excluído.");
      query.reload();
    } catch (reason) {
      setErro(reason instanceof ApiError ? reason.message : "Não foi possível excluir o nível.");
    } finally {
      setSalvando(false);
    }
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
        unidade: estado.unidade.trim() || null,
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
        <>
          <button type="button" onClick={() => { setErro(""); setNovoNivel({ rotulo: "", nivel_base: "gestor" }); }}>
            Novo nível
          </button>
          <button
            type="button"
            className="button button--primary"
            onClick={() => abrirEdicao({ id: null, nome: "", nivel: "operador_destaque", unidade: "", ativo: true, senha: "" })}
          >
            Novo usuário
          </button>
        </>
      }
    >
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Usuários ativos" value={String(ativos)} detail={`${items.length} cadastrados`} accent="primary" />
        <MetricCard label="Contas admin" value={String(admins)} detail="Acesso total, incluindo Cadastro" accent="teal" />
        <MetricCard label="Inativos" value={String(items.length - ativos)} accent="warning" />
        <MetricCard label="Sem conta admin" value={admins > 0 ? "Não" : "Sim"} detail="Sem conta admin, ninguém gerencia usuários nem contatos de chamada" accent={admins > 0 ? "teal" : "danger"} />
      </div>

      {mensagem ? <Notice>{mensagem}</Notice> : null}
      {erro && !novoNivel ? <Notice tone="error">{erro}</Notice> : null}

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
              label: rotuloNivel(nivel),
              count: items.filter((item) => (item.nivel_atribuido ?? item.nivel) === nivel).length,
            })),
            onChange: (value) => filtros.set("nivel", value),
          },
          {
            id: "usuarios-unidade",
            label: "Unidade",
            allLabel: "Todas as unidades",
            value: filtros.values.unidade,
            options: [
              ...unidades.map((unidade) => ({
                value: unidade,
                label: `Unidade ${unidade}`,
                count: items.filter((item) => item.unidade === unidade).length,
              })),
              { value: SEM_UNIDADE, label: "Sem unidade", count: items.filter((item) => !item.unidade).length },
            ],
            onChange: (value) => filtros.set("unidade", value),
          },
          {
            id: "usuarios-tela",
            label: "Tela",
            allLabel: "Todas as telas",
            value: filtros.values.tela,
            options: TELAS.map(({ value, label }) => ({
              value,
              label,
              count: items.filter((item) => item.tela === value).length,
            })),
            onChange: (value) => filtros.set("tela", value),
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
              { key: "nivel", label: "Nível", render: (row) => row.nivel_rotulo ?? humanize(row.nivel) },
              { key: "unidade", label: "Unidade", render: (row) => row.unidade ?? "—" },
              { key: "situacao", label: "Situação", render: (row) => <StatusBadge value={row.ativo ? "Ativo" : "Inativo"} /> },
              {
                key: "acoes",
                label: "Ações",
                render: (row) => (
                  <span className="pause-actions">
                    <button
                      type="button"
                      disabled={salvando}
                      onClick={() => abrirEdicao({ id: row.id, nome: row.nome, nivel: row.nivel_atribuido ?? row.nivel, unidade: row.unidade ?? "", ativo: row.ativo, senha: "" })}
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
                    <button
                      type="button"
                      disabled={salvando || row.id === user?.id}
                      title={row.id === user?.id ? PROPRIA_CONTA_EXCLUIR : undefined}
                      onClick={() => void excluir(row)}
                    >
                      Excluir
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

      {personalizados.length ? (
        <SectionCard title="Níveis personalizados">
          <DataTable
            rows={personalizados}
            rowKey={(row) => row.nome}
            columns={[
              { key: "rotulo", label: "Nível", render: (row) => row.rotulo },
              { key: "base", label: "Permissões de", render: (row) => humanize(row.nivel_base) },
              {
                key: "acoes",
                label: "Ações",
                render: (row) => (
                  <span className="pause-actions">
                    <button type="button" disabled={salvando} onClick={() => void excluirNivel(row)}>Excluir</button>
                  </span>
                ),
              },
            ]}
          />
        </SectionCard>
      ) : null}

      {novoNivel ? (
        <OperatorDialog title="Novo nível de acesso" onCancel={() => (salvando ? undefined : setNovoNivel(null))}>
          <ValidatedForm className="pause-form pause-form--dialog" onValidSubmit={() => void criarNivel(novoNivel)}>
            <label>
              Nome do nível
              <Obrigatorio />
              <input
                value={novoNivel.rotulo}
                onChange={(event) => setNovoNivel({ ...novoNivel, rotulo: event.target.value })}
                required
                maxLength={60}
              />
            </label>
            <label>
              Copiar as permissões de
              <select value={novoNivel.nivel_base} onChange={(event) => setNovoNivel({ ...novoNivel, nivel_base: event.target.value })}>
                {niveisBase.map((nivel) => (
                  <option key={nivel} value={nivel}>{humanize(nivel)}</option>
                ))}
              </select>
            </label>
            {erro && !novoNivel ? <Notice tone="error">{erro}</Notice> : null}
            <div className="pause-form__actions">
              <button type="button" onClick={() => setNovoNivel(null)}>Cancelar</button>
              <button type="submit" className="button button--primary" disabled={salvando}>Criar nível</button>
            </div>
          </ValidatedForm>
        </OperatorDialog>
      ) : null}

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
                {niveis.filter((nivel) => nivel === editando.nivel || !(query.data?.unassignable_levels ?? []).includes(nivel)).map((nivel) => (
                  <option key={nivel} value={nivel}>{rotuloNivel(nivel)}</option>
                ))}
              </select>
            </label>
            <label>
              Unidade
              <input
                list="usuarios-unidades"
                value={editando.unidade}
                onChange={(event) => setEditando({ ...editando, unidade: event.target.value })}
                maxLength={40}
                placeholder="Ex.: 4"
              />
              <datalist id="usuarios-unidades">
                {unidades.map((unidade) => <option key={unidade} value={unidade} />)}
              </datalist>
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
