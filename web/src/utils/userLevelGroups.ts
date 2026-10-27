/**
 * Agrupa os níveis de acesso por setor para os seletores de conta: cada setor
 * mostra junto o líder, o supervisor e os operadores dele. Só organiza a lista —
 * quem enxerga o quê continua sendo decidido pelo backend.
 */

export interface LevelGroup<T> {
  label: string;
  levels: T[];
}

const SOLDA_SUPERVISOR = "supervisor_almoxarifado_solda_pintura";

/** Setores na ordem em que aparecem; `match` diz quais níveis pertencem a cada um. */
const SETORES: { label: string; match: (nivel: string) => boolean }[] = [
  { label: "Solda Aço", match: (n) => /^estacao\d+aco$/.test(n) || n === SOLDA_SUPERVISOR },
  { label: "Solda Alumínio", match: (n) => /^estacao\d+alu$/.test(n) || n === SOLDA_SUPERVISOR },
  { label: "Solda Robô", match: (n) => n === "robo1" },
  { label: "Pintura", match: (n) => ["lider_pintura", "lider_pintura_almoxarifado", "operador_pintura", SOLDA_SUPERVISOR].includes(n) },
  { label: "Dobra e Corte", match: (n) => ["lider_dobra_corte", "operador_corte", "operador_dobra", "supervisor_caldeiraria"].includes(n) },
  { label: "Usinagem", match: (n) => ["lider_usinagem", "operador_usinagem", "supervisor_caldeiraria"].includes(n) },
  { label: "Serra", match: (n) => ["lider_serra", "operador_serra", "supervisor_caldeiraria"].includes(n) },
  { label: "Montagem", match: (n) => n === "operador_montagem" },
  { label: "Destaque", match: (n) => ["operador_destaque", "comum"].includes(n) },
  { label: "Almoxarifado", match: (n) => ["almoxarifado", "lider_almoxarifado", "lider_pintura_almoxarifado", SOLDA_SUPERVISOR].includes(n) },
  { label: "Projetos e Ferramentaria", match: (n) => ["projetos", "lider_projetos_ferramentaria"].includes(n) },
  { label: "Protótipo", match: (n) => ["prototipo", "supervisor_prototipo"].includes(n) },
  {
    label: "Gestão e apoio",
    match: (n) => [
      "admin", "diretoria", "gerente_industrial", "gestor", "manufatura", "qualidade", "pcp", "projetos_adm",
      "melhoria_continua", "controladoria", "manutencao", "andon", "lider", "supervisor",
    ].includes(n),
  },
];

/** Chefia primeiro (supervisor, líder), depois os operadores em ordem natural. */
function ordem(nivel: string): number {
  if (nivel.startsWith("supervisor")) return 0;
  if (nivel.startsWith("lider")) return 1;
  return 2;
}

/**
 * Divide os níveis em grupos por setor. Um nível que atende mais de um setor
 * (ex.: o supervisor de Solda/Pintura) aparece em cada um. Nível novo que não
 * cabe em nenhum setor cai em "Outros", nunca some.
 */
export function groupLevelsBySector<T>(levels: T[], toName: (level: T) => string, toLabel: (level: T) => string): LevelGroup<T>[] {
  const collator = new Intl.Collator("pt-BR", { numeric: true });
  const sorted = [...levels].sort((a, b) => ordem(toName(a)) - ordem(toName(b)) || collator.compare(toLabel(a), toLabel(b)));
  const groups: LevelGroup<T>[] = SETORES.map(({ label, match }) => ({
    label,
    levels: sorted.filter((level) => match(toName(level))),
  }));
  const used = new Set(groups.flatMap((group) => group.levels));
  groups.push({ label: "Outros", levels: sorted.filter((level) => !used.has(level)) });
  return groups.filter((group) => group.levels.length > 0);
}
