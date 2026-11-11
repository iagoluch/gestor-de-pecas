import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError } from "../../api/client";
import { useAuth } from "../../auth/AuthContext";
import { LoadingState } from "../../components/DataState";
import { Notice } from "../../components/Notice";
import { PageFrame } from "../../components/PageFrame";
import { SectionCard } from "../../components/SectionCard";
import { useApiQuery } from "../../hooks/useApiQuery";
import { SOLDA_SETORES } from "./SoldaMapaPages";

interface ActingSector {
  level: string;
  name: string;
  resources: string[];
}

/**
 * Apontamento por setor: o admin/desenvolvedor entra na tela do operador de um setor
 * sem trocar de conta. O apontamento vale de verdade, no nome dele, marcado "(gestão)".
 */
export function ActingSectorPage() {
  const query = useApiQuery<{ items: ActingSector[] }>("/api/v1/management/operator-sectors", { ignoreLiveTick: true });
  const { actAsSector } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  async function enter(sector: ActingSector) {
    setError(null);
    try {
      await actAsSector(sector.level);
      navigate("/operador");
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Não foi possível entrar no setor.");
    }
  }

  return (
    <PageFrame
      sectionId="dev"
      title="Apontamento por setor"
      subtitle="Entre na tela do operador de um setor sem trocar de conta. O apontamento vale de verdade, no seu nome, marcado como feito pela gestão."
      filters={false}
      staleError={query.data ? query.error : null}
    >
      {error ? <Notice tone="error">{error}</Notice> : null}
      {query.loading && !query.data ? <LoadingState /> : null}
      {query.data ? (
        <SectionCard title="Escolha o setor" className="content-section">
          <div className="operator-resource-grid">
            {query.data.items.filter((sector) => !SOLDA_SETORES.includes(sector.name)).map((sector) => (
              <button type="button" key={sector.level} className="operator-resource-card" onClick={() => void enter(sector)}>
                <strong>{sector.name}</strong>
                <span className="operator-resource-card__usage">{`${sector.resources.length} recurso(s)`}</span>
              </button>
            ))}
            {SOLDA_SETORES.map((nome) => {
              // Solda: um cartão por setor abre o mapa Produto -> Subconjunto (não entra direto numa estação).
              const recursos = query.data!.items.filter((sector) => sector.name === nome).flatMap((sector) => sector.resources);
              if (!recursos.length) return null;
              return (
                <button type="button" key={nome} className="operator-resource-card" onClick={() => navigate(`/inicio/apontamento-por-setor/solda/${encodeURIComponent(nome)}`)}>
                  <strong>{nome}</strong>
                  <span className="operator-resource-card__usage">{`${recursos.length} recurso(s) · ver produtos`}</span>
                </button>
              );
            })}
          </div>
        </SectionCard>
      ) : null}
    </PageFrame>
  );
}
