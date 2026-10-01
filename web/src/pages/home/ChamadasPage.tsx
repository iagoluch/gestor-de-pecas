import { DataTable } from "../../components/DataTable";
import { ErrorState, LoadingState } from "../../components/DataState";
import { MetricCard } from "../../components/MetricCard";
import { PageFrame } from "../../components/PageFrame";
import { SectionCard } from "../../components/SectionCard";
import { useApiQuery } from "../../hooks/useApiQuery";
import { displayName } from "../../utils/format";

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
  /** Ausente em chamadas antigas: aí vale `telegram_enviado`. */
  telegram_status?: "enviado" | "falhou" | "pendente";
  /** Motivo da falha, em texto simples (sem token). */
  telegram_erro?: string | null;
  criado_em: string;
}

type AvisoEstado = "enviado" | "falhou" | "enviando" | "sem_confirmacao";

/** Pendente além disso desde a criação deixa de ser "em andamento" e vira suspeita. */
const PENDENTE_SUSPEITO_MS = 5 * 60 * 1000;

const AVISO_ROTULO: Record<AvisoEstado, { texto: string; tom: "success" | "danger" | "warning" | "info" }> = {
  enviado: { texto: "Enviado", tom: "success" },
  falhou: { texto: "Falhou", tom: "danger" },
  enviando: { texto: "Enviando…", tom: "info" },
  sem_confirmacao: { texto: "Sem confirmação", tom: "warning" },
};

function estadoDoAviso(item: Chamada, agora: number): AvisoEstado {
  const status = item.telegram_status ?? (item.telegram_enviado ? "enviado" : "falhou");
  if (status !== "pendente") return status;
  const criado = Date.parse(item.criado_em);
  return Number.isFinite(criado) && agora - criado > PENDENTE_SUSPEITO_MS ? "sem_confirmacao" : "enviando";
}

/**
 * Histórico das chamadas do operador e da gestão — aba "Chamadas da Gestão",
 * destino do sininho. Só leitura e aberta a qualquer conta de gestão; o
 * cadastro de contatos é outra tela, exclusiva do admin (IagoDev).
 */
export function ManagementChamadasPage() {
  const historicoQuery = useApiQuery<{ items: Chamada[] }>("/api/v1/chamadas/admin/historico");
  const historico = historicoQuery.data?.items ?? [];
  const title = "Tela inicial — Chamadas da Gestão";
  const subtitle = "Histórico de chamadas do operador e da gestão.";

  if (historicoQuery.loading && !historicoQuery.data) {
    return (
      <PageFrame sectionId="home" title={title} subtitle={subtitle} filters={false}>
        <LoadingState />
      </PageFrame>
    );
  }
  if (historicoQuery.error && !historicoQuery.data) {
    return (
      <PageFrame sectionId="home" title={title} subtitle={subtitle} filters={false}>
        <ErrorState error={historicoQuery.error} onRetry={historicoQuery.reload} />
      </PageFrame>
    );
  }

  const agora = Date.now();
  const semTelegram = historico.filter((item) => {
    const estado = estadoDoAviso(item, agora);
    return estado === "falhou" || estado === "sem_confirmacao";
  }).length;

  return (
    <PageFrame sectionId="home" title={title} subtitle={subtitle} filters={false} staleError={historicoQuery.error}>
      <div className="metric-grid metric-grid--four">
        <MetricCard label="Chamadas registradas" value={String(historico.length)} detail="Últimas 200" accent="teal" />
        <MetricCard
          label="Sem aviso no Telegram"
          value={String(semTelegram)}
          detail="Falha no envio ou sem confirmação"
          accent={semTelegram ? "warning" : "success"}
        />
      </div>

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
            { key: "motivo", label: "Motivo", render: (row) => displayName(row.motivo) },
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
              render: (row) => {
                const { texto, tom } = AVISO_ROTULO[estadoDoAviso(row, agora)];
                const motivo = row.telegram_erro?.trim();
                return (
                  <span className={`status-badge status-badge--${tom}`} title={motivo || undefined}>
                    {texto}
                  </span>
                );
              },
            },
          ]}
        />
      </SectionCard>
    </PageFrame>
  );
}
