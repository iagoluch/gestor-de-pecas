import { EmptyState } from "../../components/DataState";
import { PageFrame } from "../../components/PageFrame";
import { SectionCard } from "../../components/SectionCard";

/**
 * Tela inicial — Metas (placeholder).
 *
 * Ainda sem regra de negócio definida: o usuário vai detalhar depois como a
 * meta é cadastrada e comparada à entrega da fábrica. Por ora só reserva o
 * lugar na navegação com o card final já no formato que vai receber dado real
 * (meta × entrega atual), sem inventar número nenhum enquanto isso.
 */
export function ManagementGoalsPage() {
  return (
    <PageFrame
      sectionId="panels"
      title="Painéis Operacionais — Metas"
      subtitle="Meta da fábrica comparada com o que está sendo entregue agora."
      filters={false}
    >
      <SectionCard title="Meta × Entrega atual">
        <EmptyState
          title="Metas ainda não configuradas"
          detail="Esta tela vai comparar a meta definida com a entrega real da fábrica assim que a regra de meta for definida."
        />
      </SectionCard>
    </PageFrame>
  );
}
