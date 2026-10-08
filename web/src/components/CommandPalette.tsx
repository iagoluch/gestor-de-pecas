import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import type { ManagementSection } from "../config/navigation";
import { tabVisibleFor } from "../config/navigation";

interface Destination {
  label: string;
  section: string;
  path: string;
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  sections: ManagementSection[];
  role?: string | null;
}

/**
 * Ir para qualquer tela (Ctrl K): lista só as telas que o menu já mostra para
 * o nível do usuário e navega para a rota existente — não abre nenhum fluxo novo.
 */
export function CommandPalette({ open, onClose, sections, role }: CommandPaletteProps) {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [term, setTerm] = useState("");
  const [index, setIndex] = useState(0);

  const destinations = useMemo<Destination[]>(
    () => sections.flatMap((section) =>
      section.tabs.filter((tab) => tabVisibleFor(tab, role)).map((tab) => ({ label: tab.label, section: section.label, path: tab.path })),
    ),
    [sections, role],
  );
  const results = useMemo(() => {
    const needle = term.trim().toLocaleLowerCase("pt-BR");
    if (!needle) return destinations;
    return destinations.filter((item) => `${item.section} ${item.label}`.toLocaleLowerCase("pt-BR").includes(needle));
  }, [destinations, term]);

  useEffect(() => {
    if (!open) return;
    setTerm("");
    setIndex(0);
    inputRef.current?.focus();
  }, [open]);

  if (!open) return null;

  function go(item: Destination | undefined) {
    if (!item) return;
    onClose();
    navigate(item.path);
  }

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "Escape") onClose();
    else if (event.key === "ArrowDown") { event.preventDefault(); setIndex((value) => Math.min(value + 1, results.length - 1)); }
    else if (event.key === "ArrowUp") { event.preventDefault(); setIndex((value) => Math.max(value - 1, 0)); }
    else if (event.key === "Enter") go(results[index]);
  }

  return (
    <div className="palette-overlay" onMouseDown={onClose}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="Ir para qualquer tela" onMouseDown={(event) => event.stopPropagation()} onKeyDown={onKeyDown}>
        <input
          ref={inputRef}
          value={term}
          onChange={(event) => { setTerm(event.target.value); setIndex(0); }}
          placeholder="Digite o nome de uma tela…"
          aria-label="Buscar tela"
        />
        <ul>
          {results.length === 0 ? <li className="palette__empty">Nenhuma tela encontrada</li> : results.map((item, position) => (
            <li key={item.path}>
              <button type="button" className={position === index ? "is-active" : ""} onMouseEnter={() => setIndex(position)} onClick={() => go(item)}>
                <strong>{item.label}</strong>
                <small>{item.section}</small>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
