import { useEffect, useMemo, useState } from "react";

/**
 * Rodízio de setores da TV do Andon, dentro da própria rota `/andon`.
 *
 * A TV mostra a visão geral e, em seguida, um setor por vez em tela cheia; ao
 * passar do último setor volta à visão geral e o ciclo recomeça. O temporizador
 * é reiniciado a cada etapa, então cada tela fica `ROTATION_SECONDS` inteiros.
 * Parada ou alerta não fixa o ciclo: o destaque acontece na visão geral.
 */

/** Tempo de exibição de cada etapa (um setor ou a visão geral), em segundos. */
export const ROTATION_SECONDS = 12;

interface CycleSector {
  name: string;
  resource_count?: number;
  resources: ReadonlyArray<unknown>;
}

/** Setores que entram no rodízio: os que têm recurso ativo, na ordem do snapshot. */
export function cycleSectorNames(sectors: ReadonlyArray<CycleSector> | undefined): string[] {
  return (sectors ?? [])
    .filter((sector) => (sector.resource_count ?? sector.resources.length) > 0)
    .map((sector) => sector.name);
}

/**
 * Devolve o setor em foco (`null` = visão geral). Com menos de dois setores não
 * há o que alternar e a tela fica sempre na visão geral. A primeira etapa é a
 * visão geral, para a TV abrir mostrando o quadro completo.
 */
export function useAndonSectorCycle(sectorNames: ReadonlyArray<string>, enabled: boolean): string | null {
  const [step, setStep] = useState(0);
  // Chave estável: o snapshot muda de identidade a cada atualização, mas a lista
  // de setores quase nunca muda, e o temporizador não pode reiniciar por isso.
  const namesKey = sectorNames.join("\u0000");
  const stages = useMemo<Array<string | null>>(
    () => (sectorNames.length > 1 ? [null, ...sectorNames] : [null]),
    [namesKey], // `namesKey` representa o conteúdo de `sectorNames`
  );
  const cycling = enabled && stages.length > 1;

  useEffect(() => {
    if (!cycling) return undefined;
    const timer = window.setTimeout(() => setStep((current) => current + 1), ROTATION_SECONDS * 1000);
    return () => window.clearTimeout(timer);
  }, [cycling, step]);

  if (!cycling) return null;
  return stages[step % stages.length];
}
