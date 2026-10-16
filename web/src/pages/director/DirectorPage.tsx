import { useState } from "react";
import { useDocumentTitle } from "../../hooks/useDocumentTitle";
import type { DirectorPeriodName } from "../../types/director";
import { DirectorCosts } from "./DirectorCosts";
import { DirectorPanel } from "./DirectorPanel";
import { DirectorSheet } from "./DirectorSheet";

type View = "painel" | "ficha" | "custos";

const VIEWS: { id: View; label: string }[] = [
  { id: "painel", label: "Painel" },
  { id: "ficha", label: "Ficha" },
  { id: "custos", label: "Custos" },
];

const PERIODS: { id: DirectorPeriodName; label: string }[] = [
  { id: "hoje", label: "Hoje" },
  { id: "semana", label: "Semana" },
  { id: "mes", label: "Mês" },
];

/**
 * Aba Diretoria: respostas prontas sobre produção, perda e custo. Tudo vem
 * calculado do servidor (mesma fonte da Visão Geral); aqui só se escolhe o
 * recorte e se mostra o resultado.
 */
export function DirectorPage() {
  useDocumentTitle("Diretoria");
  const [view, setView] = useState<View>("painel");
  const [periodo, setPeriodo] = useState<DirectorPeriodName>("hoje");
  const [setor, setSetor] = useState("");
  const [recurso, setRecurso] = useState("");

  function openSector(name: string) {
    setSetor(name);
    setRecurso("");
    setView("ficha");
  }

  return (
    <div className="page-wrap">
      <section className="page-panel">
        <header className="page-heading page-heading--standalone">
          <div>
            <h1>Diretoria</h1>
            <p>Quanto produzimos, onde perdemos tempo e quanto isso custou.</p>
          </div>
        </header>
        <div className="director-toolbar">
          <div className="director-switch" role="group" aria-label="O que ver">
            {VIEWS.map((item) => (
              <button key={item.id} type="button" className="button" aria-pressed={view === item.id} onClick={() => setView(item.id)}>
                {item.label}
              </button>
            ))}
          </div>
          {view !== "custos" ? (
            <div className="director-switch" role="group" aria-label="Período">
              {PERIODS.map((item) => (
                <button key={item.id} type="button" className="button" aria-pressed={periodo === item.id} onClick={() => setPeriodo(item.id)}>
                  {item.label}
                </button>
              ))}
            </div>
          ) : null}
        </div>
        {view === "painel" ? <DirectorPanel periodo={periodo} onOpenSector={openSector} /> : null}
        {view === "ficha" ? (
          <DirectorSheet
            periodo={periodo}
            setor={setor}
            recurso={recurso}
            onSetor={(value) => { setSetor(value); setRecurso(""); }}
            onRecurso={setRecurso}
          />
        ) : null}
        {view === "custos" ? <DirectorCosts /> : null}
      </section>
    </div>
  );
}
