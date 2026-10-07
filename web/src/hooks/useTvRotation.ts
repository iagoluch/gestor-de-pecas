import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

/**
 * Ciclo automático da TV de gestão à vista.
 *
 * A TV alterna sozinha entre as visões do ciclo, 10 segundos em cada uma, sem
 * nenhuma interação humana. O ciclo só existe para o **perfil dedicado de TV**:
 * um gestor que abre a mesma rota no navegador continua navegando por conta
 * própria, sem a tela mudar embaixo dele.
 *
 * Cada visão do ciclo continua sendo a mesma tela de sempre — o ciclo não
 * duplica projeção, não altera atualização automática e não interfere no que
 * cada uma exibe.
 */

/** Tempo de exibição de cada visão, em segundos. */
export const TV_ROTATION_SECONDS = 10;

/**
 * Ordem do ciclo. A TV mostra só o Andon (decisão do usuário, 06/10/2026);
 * a tela gerencial da Solda foi removida em 07/10/2026.
 */
export const TV_ROTATION_ROUTES = ["/andon"] as const;

export type TvRotationRoute = (typeof TV_ROTATION_ROUTES)[number];

export function nextTvRotationRoute(current: string): TvRotationRoute | null {
  const index = TV_ROTATION_ROUTES.indexOf(current as TvRotationRoute);
  if (index === -1) return null;
  return TV_ROTATION_ROUTES[(index + 1) % TV_ROTATION_ROUTES.length];
}

/**
 * Agenda a troca para a próxima visão do ciclo.
 *
 * Devolve `true` quando a sessão é a TV dedicada, para a tela poder se compor
 * em modo passivo. O temporizador é reiniciado a cada visão porque o efeito
 * remonta na navegação — é isso que dá 10 segundos por tela, e não 10 segundos
 * para o ciclo inteiro.
 */
export function useTvRotation(currentRoute: string): boolean {
  const { user } = useAuth();
  const navigate = useNavigate();
  const isTelevision = user?.role === "andon";

  useEffect(() => {
    if (!isTelevision) return undefined;
    const next = nextTvRotationRoute(currentRoute);
    if (!next || next === currentRoute) return undefined; // ciclo de uma tela só: nada a alternar
    const timer = window.setTimeout(
      () => navigate(next, { replace: true }),
      TV_ROTATION_SECONDS * 1000,
    );
    return () => window.clearTimeout(timer);
  }, [currentRoute, isTelevision, navigate]);

  return isTelevision;
}
