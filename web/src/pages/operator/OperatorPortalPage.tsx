import { useEffect, useState } from "react";
import { api, ApiError } from "../../api/client";
import { EmptyState, ErrorState, LoadingState } from "../../components/DataState";
import { assets } from "../../config/assets";
import { useApiQuery } from "../../hooks/useApiQuery";
import { OperatorShell } from "../../layouts/OperatorShell";
import type { OperatorContext } from "../../types/api";
import { CuttingPage } from "./CuttingPage";
import { HighlightPage } from "./HighlightPage";
import { WorkbenchPage } from "./WorkbenchPage";

function ResourceSelection({ context, onSelect }: { context: OperatorContext; onSelect: (resource: string) => void }) {
  if (context.sector === "Solda") {
    return (
      <section className="operator-selection operator-selection--welding">
        <EmptyState
          title="Perfil de Solda sem estação fixa"
          detail="Este login precisa ser vinculado pela liderança a um dos perfis Estação 1 a Estação 10. A estação não pode ser escolhida manualmente."
        />
      </section>
    );
  }
  return (
    <section className="operator-selection">
      <div className="operator-selection__heading"><h2>Selecione o recurso</h2><p>Acesse somente o posto em que a execução será registrada.</p></div>
      {context.resources.length === 0 ? <EmptyState title="Nenhum posto configurado para este setor" detail="Os recursos deste setor ainda não foram cadastrados. Procure a liderança antes de apontar." /> : (
        <div className="operator-resource-grid">
          {context.resources.map((resource) => {
            const resourceImage = assets.operator.resources[resource as keyof typeof assets.operator.resources]
              ?? assets.operator.sectors[context.sector as keyof typeof assets.operator.sectors]
              ?? assets.operator.navigation[context.sector as keyof typeof assets.operator.navigation];
            return (
              <button
                type="button"
                key={resource}
                className="operator-resource-card operator-resource-card--livre"
                onClick={() => onSelect(resource)}
              >
                {resourceImage ? <img src={resourceImage} alt="" /> : null}
                <strong>{resource}</strong>
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}

export function OperatorPortalPage() {
  const context = useApiQuery<OperatorContext>("/api/v1/operator/context");
  const [resource, setResource] = useState<string | null>(null);
  useEffect(() => {
    if (context.data?.resources.length === 1) setResource(context.data.resources[0]);
  }, [context.data]);
  if (context.loading) return <div className="app-loading"><LoadingState label="Preparando o posto…" /></div>;
  if (context.error) return <div className="app-loading"><ErrorState error={context.error} onRetry={context.reload} /></div>;
  if (!context.data) return null;

  const sector = context.data.sector;
  const selectedResource = resource ?? (
    context.data.resources.length === 1 ? context.data.resources[0] : null
  );
  // Wave 6B — o posto voltou a ter uma única área: a do próprio setor. A
  // entrada da qualidade é o popup Setup/Qualidade do botão Iniciar, e não uma
  // aba separada. A regra continua toda no backend.
  if (context.data.workflow === "highlight") {
    return <OperatorShell sector={sector}><HighlightPage /></OperatorShell>;
  }
  if (!selectedResource) {
    return <OperatorShell sector={sector}><ResourceSelection context={context.data} onSelect={setResource} /></OperatorShell>;
  }
  return (
    <OperatorShell
      sector={sector}
      resource={selectedResource}
      onBack={sector !== "Solda" && context.data.resources.length > 1 ? () => setResource(null) : undefined}
    >
      {context.data.workflow === "cutting" ? <CuttingPage resource={selectedResource} /> : <WorkbenchPage sector={sector} resource={selectedResource} />}
    </OperatorShell>
  );
}

export function operatorErrorMessage(reason: unknown) {
  return reason instanceof ApiError ? reason.message : "Não foi possível concluir a operação.";
}

export async function postOperator<T>(path: string, payload: unknown): Promise<T> {
  return api.post<T>(path, payload);
}
