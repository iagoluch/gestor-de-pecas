import { assets } from "./assets";

export type ManagementSectionId =
  | "home"
  | "panels"
  | "operations"
  | "production"
  | "manufacturing"
  | "quality"
  | "maintenance"
  | "diretoria"
  | "analytics"
  | "melhoria"
  | "audit"
  | "reports"
  | "traceability"
  | `area-${string}`
  | "dev";

export interface ManagementTab {
  label: string;
  path: string;
  screen: string;
  /** Id da área da fábrica (`app/core/areas.py`): só quem tem essa área na sessão vê a aba. */
  area?: string;
  /** Só a conta admin vê esta aba (decisão do usuário, 14/09/2026). */
  adminOnly?: boolean;
  /**
   * Níveis (`usuarios.nivel`) que veem esta aba. Omitido, vale a regra comum
   * da gestão. A autorização de verdade continua no backend.
   */
  levels?: readonly string[];
  /**
   * Níveis NÃO distinguíveis pelo nível efetivo da sessão (ex.: `manutencao`,
   * personalizado com molde `lider`): valem contra `user.assigned_level`, além
   * de `levels`. A autorização de verdade continua no backend.
   */
  assignedLevels?: readonly string[];
}

/** Níveis do tempo padrão: espelha `STANDARD_TIME_LEVELS` do backend. */
export const STANDARD_TIME_LEVELS = ["admin", "manufatura"] as const;

/** Níveis das cotas padrão da Qualidade: espelha `QUALITY_TEMPLATE_MANAGEMENT_LEVELS` do backend. */
export const QUALITY_TEMPLATE_LEVELS = ["admin", "qualidade"] as const;

/** Sugestões de manutenção: admin pelo nível efetivo; perfil de Manutenção pelo nível atribuído à conta (`assigned_level`). */
export const MAINTENANCE_LEVELS = ["admin"] as const;
export const MAINTENANCE_ASSIGNED_LEVELS = ["manutencao"] as const;

/** Melhoria Contínua: admin pelo nível efetivo; o setor pelo nível atribuído à conta (efetivo `lider`, igual ao de outros líderes). */
export const IMPROVEMENT_LEVELS = ["admin"] as const;
export const IMPROVEMENT_ASSIGNED_LEVELS = ["melhoria_continua"] as const;

/** Passa na trava de nível (`levels`) ou, quando declarado, no nível atribuído (`assignedLevels`)? */
function levelAllowed(
  item: { levels?: readonly string[]; assignedLevels?: readonly string[] },
  role: string | null | undefined,
  assignedLevel: string | null | undefined,
) {
  if (!item.levels) return true;
  if (role && item.levels.includes(role)) return true;
  return Boolean(assignedLevel && item.assignedLevels?.includes(assignedLevel));
}

/** Níveis da aba Diretoria: espelha `DIRECTOR_LEVELS` do backend. */
export const DIRECTOR_LEVELS = ["admin", "diretoria"] as const;

/**
 * A aba aparece para este nível? Usado pelo menu e pelo guarda de rota.
 * `areaIds` = ids das áreas da sessão (`user.areas`); aba de área sem ela some.
 */
export function tabVisibleFor(
  tab: ManagementTab,
  role: string | null | undefined,
  areaIds?: readonly string[],
  assignedLevel?: string | null,
) {
  if (tab.adminOnly && role !== "admin") return false;
  if (!levelAllowed(tab, role, assignedLevel)) return false;
  if (tab.area && !areaIds?.includes(tab.area)) return false;
  return true;
}

export interface ManagementSection {
  id: ManagementSectionId;
  label: string;
  icon: string;
  defaultPath: string;
  tabs: ManagementTab[];
  /** Só a conta admin vê a seção inteira (decisão do usuário, 14/09/2026). */
  adminOnly?: boolean;
  /** Níveis (`usuarios.nivel`) que veem a seção. Omitido, vale a regra comum da gestão. */
  levels?: readonly string[];
  /** Ver `ManagementTab.assignedLevels`. */
  assignedLevels?: readonly string[];
}

/**
 * Quem enxerga todas as áreas (admin, gerente industrial) não precisa de 7 seções no
 * menu: o setor vira filtro em Consulta Operacional > Recursos (`?setor=`). A rota
 * `/areas/<setor>` e o guarda de rota seguem iguais (usam `tabVisibleFor`).
 */
function seesAllAreas(areaIds?: readonly string[]) {
  return Boolean(areaIds) && AREA_SECTIONS.every((area) => areaIds!.includes(area.id.replace("area-", "")));
}

/** A seção aparece no menu para este nível? Seção de áreas some se a conta não tem nenhuma (ou tem todas). */
export function sectionVisibleFor(
  section: ManagementSection,
  role: string | null | undefined,
  areaIds?: readonly string[],
  assignedLevel?: string | null,
) {
  if (section.adminOnly && role !== "admin") return false;
  if (!levelAllowed(section, role, assignedLevel)) return false;
  if (section.tabs.some((tab) => tab.area)) {
    if (seesAllAreas(areaIds)) return false;
    if (!section.tabs.some((tab) => tabVisibleFor(tab, role, areaIds, assignedLevel))) return false;
  }
  return true;
}

/** Destino do clique na seção: nas seções por área, a primeira aba que a conta enxerga. */
export function sectionPathFor(
  section: ManagementSection,
  role: string | null | undefined,
  areaIds?: readonly string[],
  assignedLevel?: string | null,
) {
  if (!section.tabs.some((tab) => tab.area)) return section.defaultPath;
  return section.tabs.find((tab) => tabVisibleFor(tab, role, areaIds, assignedLevel))?.path ?? section.defaultPath;
}

/**
 * Uma seção do menu por área da fábrica (decisão do usuário, 09/10/2026), igual a
 * Manufatura e Qualidade, com o nome do setor. Quem vê qual vem da sessão
 * (`user.areas`, montada em `app/core/areas.py` a partir do nível da conta): o
 * líder da Serra só enxerga "Serra"; admin e gerente, todas. Os dados são os de
 * Consulta Operacional, filtrados pelos setores da área.
 */
const AREA_SECTIONS: ManagementSection[] = [
  ["dobra-corte", "Dobra e Corte"],
  ["usinagem", "Usinagem"],
  ["serra", "Serra"],
  ["solda", "Solda"],
  ["pintura", "Pintura"],
  ["prototipo", "Protótipo"],
  ["projetos-ferramentaria", "Projetos/Ferramentaria"],
].map(([area, label]) => ({
  id: `area-${area}`,
  label,
  icon: assets.navigation.areas[area as keyof typeof assets.navigation.areas],
  defaultPath: `/areas/${area}`,
  tabs: [{ label: "Recursos", path: `/areas/${area}`, screen: `areas-${area}`, area }],
}));

export const managementSections: ManagementSection[] = [
  {
    id: "home",
    label: "Tela inicial",
    icon: assets.navigation.home,
    defaultPath: "/inicio/visao-geral",
    tabs: [
      { label: "Visão Geral", path: "/inicio/visao-geral", screen: "home-overview" },
      { label: "IA", path: "/inicio/ia", screen: "home-ai" },
      // Histórico de chamadas visto pela gestão (e pelo sininho). Separado da
      // aba do IagoDev, que cuida só do cadastro de contatos (admin).
      { label: "Chamadas da Gestão", path: "/inicio/chamadas", screen: "home-chamadas" },
    ],
  },
  {
    id: "panels",
    label: "Painéis Operacionais",
    icon: assets.navigation.panels,
    defaultPath: "/inicio/andon",
    tabs: [
      { label: "Andon", path: "/inicio/andon", screen: "panels-andon" },
      { label: "Mapa da fábrica", path: "/inicio/mapa-fabrica", screen: "panels-factory-map" },
      // Metas: aba oculta temporariamente a pedido do usuário (01/10/2026).
      // Página e rota seguem existindo (`/inicio/metas`) — para voltar, basta
      // descomentar a linha abaixo.
      // { label: "Metas", path: "/inicio/metas", screen: "panels-goals" },
      { label: "Pausas", path: "/inicio/pausas", screen: "panels-pauses" },
    ],
  },
  {
    id: "operations",
    label: "Consulta Operacional",
    icon: assets.navigation.operations,
    defaultPath: "/consulta-operacional/visao-geral",
    tabs: [
      { label: "Visão Geral", path: "/consulta-operacional/visao-geral", screen: "operations-overview" },
      { label: "Recursos", path: "/consulta-operacional/recursos", screen: "operations-resources" },
      { label: "OPs em andamento", path: "/consulta-operacional/ops-em-andamento", screen: "operations-orders" },
    ],
  },
  {
    id: "production",
    label: "Produção",
    icon: assets.navigation.production,
    defaultPath: "/producao/ordens",
    tabs: [
      { label: "Ordens de Produção", path: "/producao/ordens", screen: "production-orders" },
      { label: "Produção realizada", path: "/producao/realizada", screen: "production-completed" },
      { label: "Planejado × Realizado", path: "/producao/planejado-realizado", screen: "production-plan-actual" },
    ],
  },
  {
    id: "manufacturing",
    label: "Manufatura",
    icon: assets.navigation.manufacturing,
    defaultPath: "/manufatura/tempo-padrao",
    // Seção da engenharia de manufatura (decisão do usuário, 07/10/2026): o
    // cadastro do tempo padrão saiu de Produção e ganhou casa própria; novas
    // telas da engenharia entram aqui. O gestor comum não vê a seção nem a rota.
    levels: STANDARD_TIME_LEVELS,
    tabs: [
      { label: "Tempo padrão", path: "/manufatura/tempo-padrao", screen: "manufacturing-standard-time", levels: STANDARD_TIME_LEVELS },
    ],
  },
  {
    id: "quality",
    label: "Qualidade",
    icon: assets.navigation.quality,
    defaultPath: "/qualidade/cotas",
    // Seção da conta Qualidade (decisão do usuário, 07/10/2026): as cotas padrão
    // por produto saíram de Produção; novas telas dela entram aqui. O gestor
    // comum não vê a seção nem a rota.
    levels: QUALITY_TEMPLATE_LEVELS,
    tabs: [
      { label: "Cotas padrão", path: "/qualidade/cotas", screen: "quality-templates", levels: QUALITY_TEMPLATE_LEVELS },
      // SPC somente leitura: a API (`GET /quality/spc`) usa a mesma guarda das cotas padrão.
      { label: "SPC", path: "/qualidade/spc", screen: "quality-spc", levels: QUALITY_TEMPLATE_LEVELS },
      // Decisão de RNC: a API (`/quality/rnc`) usa a guarda da Qualidade (Qualidade e admin).
      { label: "Decisão de RNC", path: "/qualidade/rnc", screen: "quality-rnc", levels: QUALITY_TEMPLATE_LEVELS },
    ],
  },
  {
    id: "maintenance",
    label: "Manutenção",
    icon: assets.navigation.manufacturing,
    defaultPath: "/manutencao/sugestoes",
    // Sugestões de paradas de manutenção (26/10/2026): só o perfil de Manutenção
    // (nível atribuído `manutencao`) e o admin. O gestor comum não vê a seção
    // nem a rota; a API (`/maintenance/*`) recusa os demais.
    levels: MAINTENANCE_LEVELS,
    assignedLevels: MAINTENANCE_ASSIGNED_LEVELS,
    tabs: [
      { label: "Sugestões", path: "/manutencao/sugestoes", screen: "maintenance-suggestions", levels: MAINTENANCE_LEVELS, assignedLevels: MAINTENANCE_ASSIGNED_LEVELS },
    ],
  },
  {
    id: "diretoria",
    label: "Diretoria",
    icon: assets.navigation.diretoria,
    defaultPath: "/diretoria",
    // Aba da diretoria (spec de 16/10/2026): custo de produção por produto.
    // O gestor comum não vê a seção nem a rota.
    levels: DIRECTOR_LEVELS,
    tabs: [
      { label: "Diretoria", path: "/diretoria", screen: "diretoria", levels: DIRECTOR_LEVELS },
    ],
  },
  {
    id: "melhoria",
    label: "Melhoria Contínua",
    icon: assets.navigation.melhoria,
    defaultPath: "/melhoria-continua",
    // Visão de oportunidades (23/10/2026), exclusiva do setor de Melhoria
    // Contínua e do admin (27/10/2026): as consultas são as das Análises, então
    // o corte é só de menu e rota.
    levels: IMPROVEMENT_LEVELS,
    assignedLevels: IMPROVEMENT_ASSIGNED_LEVELS,
    tabs: [
      { label: "Oportunidades", path: "/melhoria-continua", screen: "melhoria-oportunidades", levels: IMPROVEMENT_LEVELS, assignedLevels: IMPROVEMENT_ASSIGNED_LEVELS },
    ],
  },
  {
    id: "analytics",
    label: "Análises",
    icon: assets.navigation.analytics,
    defaultPath: "/analises/oee",
    tabs: [
      { label: "OEE", path: "/analises/oee", screen: "analytics-oee" },
      { label: "Horas & Utilização", path: "/analises/horas-utilizacao", screen: "analytics-hours" },
      { label: "Paradas & Setup", path: "/analises/paradas", screen: "analytics-downtimes" },
      { label: "Qualidade", path: "/analises/qualidade", screen: "analytics-quality" },
      { label: "Tempo padrão", path: "/analises/tempo-padrao-real", screen: "analytics-standard" },
      { label: "Cronoanálise", path: "/analises/cronoanalise", screen: "analytics-chrono" },
      { label: "Capacidade", path: "/analises/capacidade-gargalos", screen: "analytics-capacity" },
      { label: "Confiabilidade", path: "/analises/confiabilidade", screen: "analytics-reliability" },
    ],
  },
  {
    id: "audit",
    label: "Auditoria",
    icon: assets.navigation.audit,
    defaultPath: "/auditoria/apontamentos",
    tabs: [
      { label: "Apontamentos", path: "/auditoria/apontamentos", screen: "audit-appointments" },
      { label: "Alertas e inconsistências", path: "/auditoria/alertas-inconsistencias", screen: "audit-alerts-issues" },
      { label: "Confiabilidade dos dados", path: "/auditoria/confiabilidade", screen: "audit-reliability" },
    ],
  },
  {
    id: "reports",
    label: "Relatórios",
    icon: assets.navigation.reports,
    defaultPath: "/relatorios",
    tabs: [
      { label: "Relatórios", path: "/relatorios", screen: "reports" },
    ],
  },
  {
    id: "traceability",
    label: "Rastreabilidade",
    icon: assets.navigation.traceability,
    defaultPath: "/rastreabilidade/op-produto",
    tabs: [
      { label: "OP / Produto", path: "/rastreabilidade/op-produto", screen: "traceability-order" },
      { label: "Lote / Material / Nesting", path: "/rastreabilidade/lote-material-nesting", screen: "traceability-nesting" },
    ],
  },
  ...AREA_SECTIONS,
  {
    id: "dev",
    label: "IagoDev",
    icon: assets.navigation.dev,
    defaultPath: "/inicio/crachas",
    adminOnly: true,
    // Configurações exclusivas da conta admin. Crachás e Cadastro já
    // existem; novas telas de configuração (ex.: parâmetros de integração,
    // feature flags) entram aqui conforme forem criadas — decisão do
    // usuário, 15/09/2026.
    // O histórico de chamadas da gestão (sininho) saiu daqui e vive na Tela
    // inicial ("Chamadas da Gestão"): esta seção é toda admin-only, então a
    // gestão comum nunca mais entra no IagoDev para ver chamadas
    // (decisão do usuário, 01/10/2026).
    tabs: [
      { label: "Crachás", path: "/inicio/crachas", screen: "dev-badges", adminOnly: true },
      { label: "Cadastro", path: "/inicio/cadastro", screen: "dev-users", adminOnly: true },
      { label: "Chamadas do IagoDev", path: "/inicio/chamadas-dev", screen: "dev-chamadas", adminOnly: true },
      { label: "Turnos", path: "/inicio/turnos", screen: "dev-turnos", adminOnly: true },
      { label: "Alterações", path: "/inicio/alteracoes", screen: "dev-alteracoes", adminOnly: true },
      { label: "Sistema", path: "/inicio/sistema", screen: "dev-sistema", adminOnly: true },
    ],
  },
];

export const managementRoutes = managementSections.flatMap((section) =>
  section.tabs.map((tab) => ({ ...tab, sectionId: section.id })),
);

export function sectionById(id: ManagementSectionId) {
  return managementSections.find((section) => section.id === id)!;
}

// "Tela inicial", "Painéis Operacionais" e "DEV" compartilham o prefixo de
// URL /inicio/*, então a seção ativa só pode ser decidida comparando com as
// rotas reais de cada uma — comparar só o primeiro trecho da URL marcaria as
// três ao mesmo tempo.
export function isSectionActive(section: ManagementSection, pathname: string) {
  return section.tabs.some((tab) => pathname === tab.path || pathname.startsWith(`${tab.path}/`));
}
