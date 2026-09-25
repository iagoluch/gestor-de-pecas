import { useMemo, useState } from "react";
import { api } from "../../api/client";
import { DataTable } from "../../components/DataTable";
import { RowActions } from "../../components/RowActions";
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

interface OperatorBadge {
  id: number;
  cracha: string;
  nome: string;
  ativo: boolean;
  fonte?: string | null;
  autorizador_retrabalho?: boolean;
  criado_em?: string | null;
}

interface BadgesResponse {
  items: OperatorBadge[];
  count: number;
  active: number;
  authorizers: OperatorBadge[];
  authorizer_count: number;
}

const NOVO: OperatorBadge = {
  id: 0,
  cracha: "",
  nome: "",
  ativo: true,
  autorizador_retrabalho: false,
};

const FILTROS_INICIAIS = { situacao: "", perfil: "", origem: "", busca: "" };

/**
 * Perfil é leitura da designação que já existe no cadastro: quem pode liberar o
 * retrabalho da primeira peça e quem apenas aponta. Nenhum perfil novo é criado
 * e a autorização continua sendo feita pelo crachá.
 */
const PERFIS = [
  { value: "responsavel", label: "Responsável por retrabalho" },
  { value: "operador", label: "Operador sem designação" },
];

const SITUACOES = [
  { value: "ativo", label: "Ativo" },
  { value: "inativo", label: "Inativo" },
];

function perfilDoCracha(badge: OperatorBadge) {
  return badge.autorizador_retrabalho ? "responsavel" : "operador";
}

function origemDoCracha(badge: OperatorBadge) {
  return String(badge.fonte ?? "cadastro").trim() || "cadastro";
}

/**
 * Cadastro dos crachás do chão de fábrica e designação de quem pode atender o
 * chamado de retrabalho da primeira peça.
 *
 * O responsável **não** possui login: ele é identificado apenas pelo crachá,
 * dentro do cadastro de operadores que já existia. Esta tela é a única fonte
 * dessa designação.
 */
export function ManagementBadgesPage() {
  const query = useApiQuery<BadgesResponse>("/api/v1/management/badges");
  const [mensagem, setMensagem] = useState("");
  const [salvando, setSalvando] = useState(false);
  const [confirm, confirmDialog] = useConfirm();
  const [editando, setEditando, abrirEdicao, fecharEdicao] = useDraft<OperatorBadge>(confirm);
  const filtros = usePersistentFilters("gestor.filtros.crachas", FILTROS_INICIAIS);

  const items = useMemo(() => query.data?.items ?? [], [query.data]);
  const title = "IagoDev — Crachás e responsáveis";
  const subtitle =
    "Crachás do chão de fábrica e quem está autorizado a liberar o retrabalho da primeira peça.";

  const origens = useMemo(() => {
    const agrupadas = new Map<string, number>();
    items.forEach((item) => {
      const origem = origemDoCracha(item);
      agrupadas.set(origem, (agrupadas.get(origem) ?? 0) + 1);
    });
    return [...agrupadas.entries()]
      .map(([value, count]) => ({ value, label: humanize(value), count }))
      .sort((left, right) => left.label.localeCompare(right.label, "pt-BR"));
  }, [items]);

  const filtrados = useMemo(() => {
    const busca = filtros.values.busca.trim().toLocaleLowerCase("pt-BR");
    return items
      .filter((item) => !filtros.values.situacao || (filtros.values.situacao === "ativo" ? item.ativo : !item.ativo))
      .filter((item) => !filtros.values.perfil || perfilDoCracha(item) === filtros.values.perfil)
      .filter((item) => !filtros.values.origem || origemDoCracha(item) === filtros.values.origem)
      .filter((item) => !busca || `${item.cracha} ${item.nome}`.toLocaleLowerCase("pt-BR").includes(busca))
      .sort((left, right) => left.nome.localeCompare(right.nome, "pt-BR")
        || left.cracha.localeCompare(right.cracha, "pt-BR"));
  }, [filtros.values, items]);

  async function salvar(badge: Partial<OperatorBadge>) {
    setSalvando(true);
    setMensagem("");
    try {
      await api.post("/api/v1/management/badges", {
        cracha: badge.cracha,
        nome: badge.nome,
        ativo: badge.ativo ?? true,
        autorizador_retrabalho: badge.autorizador_retrabalho ?? false,
      });
      setMensagem("Crachá salvo. A designação já vale para o próximo chamado.");
      setEditando(null);
      query.reload();
    } catch {
      setMensagem("Não foi possível salvar o crachá. Confira o código e o nome.");
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

  const resumo = filtros.active
    ? `${filtrados.length} de ${items.length} crachás no recorte atual`
    : `${items.length} crachás cadastrados`;
  return (
    <PageFrame staleError={query.error}
      sectionId="dev"
      title={title}
      subtitle={subtitle}
      filters={false}
      actions={
        <button type="button" className="button button--primary" onClick={() => abrirEdicao({ ...NOVO })}>
          Novo crachá
        </button>
      }
    >
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Crachás ativos" value={String(query.data?.active ?? 0)} detail={`${query.data?.count ?? 0} cadastrados`} accent="primary" />
        <MetricCard label="Responsáveis autorizados" value={String(query.data?.authorizer_count ?? 0)} detail="Retrabalho da primeira peça" accent="success" />
        <MetricCard label="Inativos" value={String((query.data?.count ?? 0) - (query.data?.active ?? 0))} accent="warning" />
        <MetricCard label="Sem responsável" value={(query.data?.authorizer_count ?? 0) > 0 ? "Não" : "Sim"} detail="Sem responsável designado, a OP bloqueada não é liberada." accent={(query.data?.authorizer_count ?? 0) > 0 ? "teal" : "danger"} />
      </div>

      {mensagem ? <Notice>{mensagem}</Notice> : null}

      <RecordToolbar
        ariaLabel="Filtros dos crachás"
        selects={[
          {
            id: "crachas-situacao",
            label: "Situação",
            allLabel: "Todas as situações",
            value: filtros.values.situacao,
            options: SITUACOES.map((situacao) => ({
              ...situacao,
              count: items.filter((item) => (situacao.value === "ativo" ? item.ativo : !item.ativo)).length,
            })),
            onChange: (value) => filtros.set("situacao", value),
          },
          {
            id: "crachas-perfil",
            label: "Perfil",
            allLabel: "Todos os perfis",
            value: filtros.values.perfil,
            options: PERFIS.map((perfil) => ({
              ...perfil,
              count: items.filter((item) => perfilDoCracha(item) === perfil.value).length,
            })),
            onChange: (value) => filtros.set("perfil", value),
          },
          {
            id: "crachas-origem",
            label: "Origem do cadastro",
            allLabel: "Todas as origens",
            value: filtros.values.origem,
            options: origens,
            onChange: (value) => filtros.set("origem", value),
          },
        ]}
        search={{
          value: filtros.values.busca,
          onChange: (value) => filtros.set("busca", value),
          placeholder: "Buscar por crachá ou nome",
        }}
        summary={resumo}
        onReset={filtros.reset}
        resetDisabled={!filtros.active}
      />

      <SectionCard
        title="Crachás cadastrados"
        className="content-section section-card--table"
        action={<span className="section-count">{filtrados.length} crachá(s)</span>}
      >
        {filtrados.length ? (
          <DataTable
            rows={filtrados}
            rowKey={(row) => row.cracha}
            columns={[
              { key: "cracha", label: "Crachá", render: (row) => row.cracha },
              { key: "nome", label: "Nome", render: (row) => row.nome },
              { key: "situacao", label: "Situação", render: (row) => <StatusBadge value={row.ativo ? "Ativo" : "Inativo"} /> },
              {
                key: "perfil",
                label: "Perfil",
                render: (row) => (row.autorizador_retrabalho ? "Responsável por retrabalho" : "Operador"),
              },
              { key: "fonte", label: "Origem", render: (row) => humanize(origemDoCracha(row)) },
              {
                key: "acoes",
                label: "Ações",
                render: (row) => (
                  <RowActions
                    label={`${row.cracha} — ${row.nome}`}
                    disabled={salvando}
                    primary={{ label: "Editar", onClick: () => abrirEdicao(row) }}
                    actions={[
                      { label: row.autorizador_retrabalho ? "Remover responsável" : "Tornar responsável", onClick: async () => { if (!row.autorizador_retrabalho || await confirm({ title: "Remover responsável por retrabalho", message: `${row.nome} deixa de poder autorizar retrabalho no terminal.`, confirmLabel: "Remover responsável", tone: "danger" })) void salvar({ ...row, autorizador_retrabalho: !row.autorizador_retrabalho }); } },
                      { label: row.ativo ? "Desativar" : "Ativar", danger: row.ativo, onClick: async () => { if (!row.ativo || await confirm({ title: "Desativar crachá", message: `O crachá ${row.cracha} (${row.nome}) deixa de ser aceito nos terminais até ser ativado de novo.`, confirmLabel: "Desativar crachá", tone: "danger" })) void salvar({ ...row, ativo: !row.ativo }); } },
                    ]}
                  />
                ),
              },
            ]}
          />
        ) : items.length ? (
          <EmptyState
            title="Nenhum crachá no filtro atual"
            detail="Ajuste a situação, o perfil, a origem ou a busca para ver os crachás cadastrados."
          />
        ) : (
          <EmptyState
            title="Nenhum crachá cadastrado"
            detail="Sem crachá cadastrado, nenhuma exceção operacional pode ser autorizada."
          />
        )}
      </SectionCard>

      {editando ? (
        <OperatorDialog
          title={editando.id ? "Editar crachá" : "Novo crachá"}
          onCancel={() => (salvando ? undefined : void fecharEdicao())}
        >
          <ValidatedForm className="pause-form pause-form--dialog" onValidSubmit={() => void salvar(editando)}>
            <label>
              Crachá
              <Obrigatorio />
              <input
                value={editando.cracha}
                onChange={(event) => setEditando({ ...editando, cracha: event.target.value })}
                disabled={Boolean(editando.id)}
                required
              />
            </label>
            <label>
              Nome
              <Obrigatorio />
              <input
                value={editando.nome}
                onChange={(event) => setEditando({ ...editando, nome: event.target.value })}
                required
              />
            </label>
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
                checked={Boolean(editando.autorizador_retrabalho)}
                onChange={(event) => setEditando({ ...editando, autorizador_retrabalho: event.target.checked })}
              />
              Autorizado a liberar retrabalho da primeira peça
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
