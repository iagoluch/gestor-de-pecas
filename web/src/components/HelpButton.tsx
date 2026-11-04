import { useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { topicoParaRota, type ManualId } from "../help/helpContent";

/** Ícone "?" do topo: abre o manual numa nova aba, já no tópico da tela atual. */
export function HelpButton({ manual }: { manual: ManualId }) {
  const { pathname } = useLocation();
  const { user } = useAuth();
  const topico = topicoParaRota(manual, pathname, user?.role);
  const href = `/ajuda/${manual}${topico ? `/${topico.id}` : ""}`;
  return (
    <a
      className="theme-toggle theme-toggle--icon help-button"
      href={href}
      target="_blank"
      rel="noopener"
      aria-label="Abrir o manual desta tela"
      title="Manual: ajuda sobre esta tela"
    >
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" aria-hidden="true">
        <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.7" />
        <path d="M9.4 9.4a2.7 2.7 0 1 1 3.9 2.4c-.8.4-1.3 1-1.3 1.9" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
        <circle cx="12" cy="16.9" r="1" fill="currentColor" />
      </svg>
    </a>
  );
}
