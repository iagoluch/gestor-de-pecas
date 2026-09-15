import { assets } from "./assets";

export type ManagementSectionId =
  | "home"
  | "panels"
  | "operations"
  | "production"
  | "analytics"
  | "audit"
  | "reports"
  | "traceability"
  | "dev";

export interface ManagementTab {
  label: string;
  path: string;
  screen: string;
  /** Só a conta admin vê esta aba (decisão do usuário, 14/09/2026). */
  adminOnly?: boolean;
}

export interface ManagementSection {
  id: ManagementSectionId;
  label: string;
  icon: string;
  defaultPath: string;
  tabs: ManagementTab[];
  /** Só a conta admin vê a seção inteira (decisão do usuário, 14/09/2026). */
  adminOnly?: boolean;
}

export const managementSections: ManagementSection[] = [
  {
    id: "home",
    label: "Tela inicial",
    icon: assets.navigation.home,
    defaultPath: "/inicio/visao-geral",
    tabs: [
      { label: "Visão Geral", path: "/inicio/visao-geral", screen: "home-overview" },
      { label: "Setores", path: "/inicio/setores", screen: "home-sectors" },
      { label: "Alertas", path: "/inicio/alertas", screen: "home-alerts" },
      { label: "IA", path: "/inicio/ia", screen: "home-ai" },
    ],
  },
  {
    id: "panels",
    label: "Painéis Operacionais",
    icon: assets.navigation.panels,
    defaultPath: "/inicio/andon",
    tabs: [
      { label: "Andon", path: "/inicio/andon", screen: "panels-andon" },
      { label: "Solda", path: "/inicio/solda", screen: "panels-welding" },
      { label: "Metas", path: "/inicio/metas", screen: "panels-goals" },
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
      { label: "Tempo MES", path: "/consulta-operacional/tempo-mes", screen: "operations-time" },
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
    id: "analytics",
    label: "Análises",
    icon: assets.navigation.analytics,
    defaultPath: "/analises/oee",
    tabs: [
      { label: "OEE", path: "/analises/oee", screen: "analytics-oee" },
      { label: "Horas & Utilização", path: "/analises/horas-utilizacao", screen: "analytics-hours" },
      { label: "Paradas", path: "/analises/paradas", screen: "analytics-downtimes" },
      { label: "Setup", path: "/analises/setup", screen: "analytics-setup" },
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
      { label: "Inconsistências", path: "/auditoria/inconsistencias", screen: "audit-issues" },
      { label: "Confiabilidade dos dados", path: "/auditoria/confiabilidade", screen: "audit-reliability" },
    ],
  },
  {
    id: "reports",
    label: "Relatórios",
    icon: assets.navigation.reports,
    defaultPath: "/relatorios/gerencial",
    tabs: [
      { label: "Gerencial", path: "/relatorios/gerencial", screen: "reports-management" },
      { label: "Produção", path: "/relatorios/producao", screen: "reports-production" },
      { label: "Perdas", path: "/relatorios/perdas", screen: "reports-losses" },
      { label: "Indicadores", path: "/relatorios/indicadores", screen: "reports-indicators" },
      { label: "Dados analíticos", path: "/relatorios/dados-analiticos", screen: "reports-analytics" },
    ],
  },
  {
    id: "traceability",
    label: "Rastreabilidade",
    icon: assets.navigation.traceability,
    defaultPath: "/rastreabilidade/op-produto",
    tabs: [
      { label: "OP / Produto", path: "/rastreabilidade/op-produto", screen: "traceability-order" },
      { label: "Linha do tempo", path: "/rastreabilidade/linha-do-tempo", screen: "traceability-timeline" },
      { label: "Lote / Material / Nesting", path: "/rastreabilidade/lote-material-nesting", screen: "traceability-nesting" },
    ],
  },
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
    tabs: [
      { label: "Crachás", path: "/inicio/crachas", screen: "dev-badges" },
      { label: "Cadastro", path: "/inicio/cadastro", screen: "dev-users" },
      { label: "Chamadas", path: "/inicio/chamadas", screen: "dev-chamadas" },
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
