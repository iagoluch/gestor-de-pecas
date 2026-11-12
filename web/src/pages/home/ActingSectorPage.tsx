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
        <>
          <SectionCard title="Setores" action={<span className="acting-sector-hint">Clique no cartão para entrar na tela do operador.</span>} className="content-section">
            <div className="acting-sector-grid">
              {query.data.items.filter((sector) => !SOLDA_SETORES.includes(sector.name)).map((sector) => (
                <SectorCard key={sector.level} name={sector.name} resources={sector.resources} action="Entrar no setor" onClick={() => void enter(sector)} />
              ))}
            </div>
          </SectionCard>
          <SectionCard title="Solda, Projetos e Protótipo" action={<span className="acting-sector-hint">Clique para abrir o mapa Produto → Subconjunto.</span>} className="content-section">
            <div className="acting-sector-grid">
              {SOLDA_SETORES.map((nome) => {
                // Solda: um cartão por setor abre o mapa Produto -> Subconjunto (não entra direto numa estação).
                const recursos = query.data!.items.filter((sector) => sector.name === nome).flatMap((sector) => sector.resources);
                if (!recursos.length) return null;
                return (
                  <SectorCard key={nome} name={nome} resources={recursos} action="Ver produtos" onClick={() => navigate(`/inicio/apontamento-por-setor/solda/${encodeURIComponent(nome)}`)} />
                );
              })}
            </div>
          </SectionCard>
        </>
      ) : null}
    </PageFrame>
  );
}

function SectorCard({ name, resources, action, onClick }: { name: string; resources: string[]; action: string; onClick: () => void }) {
  return (
    <button type="button" className="acting-sector-card" onClick={onClick}>
      <span className="acting-sector-card__head">
        <strong>{name}</strong>
        <span className="acting-sector-card__count">{`${resources.length} recurso(s)`}</span>
      </span>
      <span className="acting-sector-card__resources">
        {resources.length
          ? resources.map((resource) => <span key={resource} className="acting-sector-card__chip">{resource}</span>)
          : <span className="acting-sector-card__empty">Sem recurso cadastrado</span>}
      </span>
      <span className="acting-sector-card__action">{action} →</span>
    </button>
  );
}
