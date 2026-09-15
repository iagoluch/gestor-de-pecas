import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useApiQuery } from "../hooks/useApiQuery";

/**
 * Sininho pessoal de chamadas — cada conta de gestão vê a própria contagem
 * de chamadas não vistas (decisão do usuário, 14/09/2026), atualizada ao
 * vivo. Clicar leva ao histórico e marca tudo como visto.
 */
export function ChamadaSino() {
  const query = useApiQuery<{ count: number }>("/api/v1/chamadas/nao-vistas");
  const navigate = useNavigate();
  const count = query.data?.count ?? 0;

  async function abrir() {
    navigate("/inicio/chamadas");
    try {
      await api.post("/api/v1/chamadas/marcar-vistas");
    } finally {
      query.reload();
    }
  }

  return (
    <button
      type="button"
      className="chamada-sino"
      onClick={() => void abrir()}
      aria-label={count > 0 ? `Chamadas — ${count} não vista(s)` : "Chamadas"}
      title="Chamadas"
    >
      <SinoIcon />
      {count > 0 ? <span className="chamada-sino__badge">{count > 99 ? "99+" : count}</span> : null}
    </button>
  );
}

function SinoIcon() {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true">
      <path
        d="M18 16v-5a6 6 0 1 0-12 0v5l-1.5 2h15L18 16Z"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M10 20a2 2 0 0 0 4 0" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}
