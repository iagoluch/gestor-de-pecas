import type { PropsWithChildren } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { EmptyState, LoadingState } from "./components/DataState";
import { DIRECTOR_LEVELS, MAINTENANCE_ASSIGNED_LEVELS, MAINTENANCE_LEVELS, QUALITY_TEMPLATE_LEVELS, STANDARD_TIME_LEVELS } from "./config/navigation";
import { FilterProvider } from "./filters/FilterContext";
import { AppShell } from "./layouts/AppShell";
import { LoginPage } from "./pages/LoginPage";
import { ChangePasswordPage } from "./pages/ChangePasswordPage";
import { AndonPage } from "./pages/AndonPage";
import { ManagementOverviewPage } from "./pages/ManagementOverviewPage";
import { ManagementGoalsPage } from "./pages/home/GoalsPage";
import { ManagementPausesPage } from "./pages/home/PausesPage";
import { ManagementBadgesPage } from "./pages/home/BadgesPage";
import { ManagementChamadasPage } from "./pages/home/ChamadasPage";
import { DevChamadasContatosPage } from "./pages/home/ChamadasContatosPage";
import { ManagementShiftsPage } from "./pages/home/ShiftsPage";
import { ManagementSystemPage } from "./pages/home/SystemPage";
import { ManagementUsersPage } from "./pages/home/UsersPage";
import { AIPage } from "./pages/AIPage";
import { OperatorPortalPage } from "./pages/operator/OperatorPortalPage";
import {
  AnalyticsCapacityPage,
  AnalyticsChronoPage,
  AnalyticsDowntimesPage,
  AnalyticsHoursPage,
  AnalyticsOeePage,
  AnalyticsQualityPage,
  AnalyticsReliabilityPage,
  AnalyticsStandardPage,
} from "./pages/analytics/AnalyticsPages";
import { AuditAppointmentsPage, AuditIssuesPage, AuditReliabilityPage } from "./pages/audit/AuditPages";
import { HomeAlertsPage, HomeSectorsPage } from "./pages/home/HomePages";
import { AreaPage } from "./pages/areas/AreaPage";
import { OperationsOrdersPage,OperationsOverviewPage, OperationsResourcesPage, OperationsTimePage } from "./pages/operations/OperationsPages";
import { ProductionCompletedPage, ProductionOrdersPage, ProductionPlanActualPage } from "./pages/production/ProductionPages";
import { MaintenanceSuggestionsPage, MaintenanceTerminalPage } from "./pages/maintenance/MaintenanceSuggestionsPage";
import { QualitySpcPage } from "./pages/production/QualitySpcPage";
import { QualityTemplatesPage } from "./pages/production/QualityTemplatesPage";
import { StandardTimePage } from "./pages/production/StandardTimePage";
import { DirectorPage } from "./pages/director/DirectorPage";
import { ImprovementPage } from "./pages/improvement/ImprovementPage";
import {
  AnalyticalDataReportPage,
  IndicatorsReportPage,
  LossesReportPage,
  ManagementReportPage,
  ProductionReportPage,
} from "./pages/reports/ReportsPages";
import { TraceabilityNestingPage, TraceabilityOrderPage, TraceabilityTimelinePage } from "./pages/traceability/TraceabilityPages";

function roleHome(user: { management_access: boolean; andon_access?: boolean; maintenance_access?: boolean }) {
  if (user.management_access) return "/inicio/visao-geral";
  if (user.andon_access) return "/andon";
  if (user.maintenance_access) return "/manutencao";
  return "/operador";
}

function RequireAuth({ management = false, andon = false, operator = false, maintenance = false, children }: PropsWithChildren<{ management?: boolean; andon?: boolean; operator?: boolean; maintenance?: boolean }>) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="app-loading"><LoadingState label="Verificando sessão…" /></div>;
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  // Gestão na senha padrão: a API recusa tudo até a troca, então a tela pede a nova senha antes.
  if (user.password_change_required) return <ChangePasswordPage />;
  if (management && !user.management_access) return <Navigate to={roleHome(user)} replace />;
  if (andon && !user.andon_access && !user.management_access) return <Navigate to={roleHome(user)} replace />;
  if (operator && !user.operator_access) return <Navigate to={roleHome(user)} replace />;
  if (maintenance && !user.maintenance_access) return <Navigate to={roleHome(user)} replace />;
  return children;
}

/**
 * Telas só de admin (as mesmas `adminOnly` do menu, que já as esconde):
 * pela URL direta o gestor recebia 403 como erro genérico ou tela vazia.
 * Aqui a página nem monta — sem chamada à API e com o motivo explícito (GE-07).
 * A autorização continua no backend; isto só evita a mensagem enganosa.
 */
function RequireAdmin({ children }: PropsWithChildren) {
  const { user } = useAuth();
  if (user?.role === "admin") return children;
  return (
    <div className="page-wrap">
      <section className="page-panel">
        <EmptyState title="Acesso restrito ao administrador" detail="Esta tela é exclusiva da conta de administração. Peça a um administrador se precisar de alguma alteração aqui." />
      </section>
    </div>
  );
}

/**
 * Tempo padrão: só engenharia de manufatura e admin. O gestor comum não vê a
 * aba (menu filtrado) e, pela URL direta, a página nem monta nem chama a API.
 */
function RequireStandardTimeAccess({ children }: PropsWithChildren) {
  const { user } = useAuth();
  if (user && (STANDARD_TIME_LEVELS as readonly string[]).includes(user.role)) return children;
  return (
    <div className="page-wrap">
      <section className="page-panel">
        <EmptyState title="Acesso restrito à engenharia de manufatura" detail="Esta tela é exclusiva da engenharia de manufatura e da administração. Peça a elas se precisar de alguma alteração aqui." />
      </section>
    </div>
  );
}

/**
 * Cotas padrão da Qualidade: só a conta qualidade e o admin. O gestor comum não
 * vê a aba e, pela URL direta, a página nem monta nem chama a API.
 */
function RequireQualityTemplateAccess({ children, detail = "Esta tela é exclusiva da Qualidade e da administração. Peça a elas se precisar de alguma alteração nas cotas padrão." }: PropsWithChildren<{ detail?: string }>) {
  const { user } = useAuth();
  if (user && (QUALITY_TEMPLATE_LEVELS as readonly string[]).includes(user.role)) return children;
  return (
    <div className="page-wrap">
      <section className="page-panel">
        <EmptyState title="Acesso restrito à Qualidade" detail={detail} />
      </section>
    </div>
  );
}

/**
 * Sugestões de manutenção: só o mantenedor e o admin. O mantenedor tem nível
 * efetivo `lider`; quem o distingue é o nível atribuído à conta (`assigned_level`).
 * Os demais não veem o item de menu e, pela URL direta, a página nem monta nem
 * chama a API.
 */
function RequireMaintenanceAccess({ children }: PropsWithChildren) {
  const { user } = useAuth();
  const allowed = Boolean(user && ((MAINTENANCE_LEVELS as readonly string[]).includes(user.role)
    || (user.assigned_level && (MAINTENANCE_ASSIGNED_LEVELS as readonly string[]).includes(user.assigned_level))));
  if (allowed) return children;
  return (
    <div className="page-wrap">
      <section className="page-panel">
        <EmptyState title="Acesso restrito à Manutenção" detail="Esta tela é exclusiva da Manutenção e da administração. Peça a elas se precisar consultar as sugestões de manutenção." />
      </section>
    </div>
  );
}

/**
 * Aba Diretoria: só a diretoria e o admin. Quem não é desses níveis volta para a
 * tela inicial da gestão (o menu já esconde o item); a API recusa de qualquer forma.
 */
function RequireDiretoriaAccess({ children }: PropsWithChildren) {
  const { user } = useAuth();
  if (user && (DIRECTOR_LEVELS as readonly string[]).includes(user.role)) return children;
  return <Navigate to="/inicio/visao-geral" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/andon" element={<RequireAuth andon><AndonPage /></RequireAuth>} />
      <Route path="/mapa-fabrica" element={<RequireAuth management><AndonPage mapOnly /></RequireAuth>} />
      <Route
        path="/"
        element={(
          <RequireAuth management>
            <FilterProvider><AppShell /></FilterProvider>
          </RequireAuth>
        )}
      >
        <Route index element={<Navigate to="/inicio/visao-geral" replace />} />
        <Route path="inicio/visao-geral" element={<ManagementOverviewPage />} />
        <Route path="inicio/setores" element={<HomeSectorsPage />} />
        <Route path="inicio/alertas" element={<HomeAlertsPage />} />
        <Route path="inicio/andon" element={<Navigate to="/andon" replace />} />
        <Route path="inicio/mapa-fabrica" element={<Navigate to="/mapa-fabrica" replace />} />
        <Route path="inicio/metas" element={<ManagementGoalsPage />} />
        <Route path="inicio/pausas" element={<ManagementPausesPage />} />
        <Route path="inicio/crachas" element={<RequireAdmin><ManagementBadgesPage /></RequireAdmin>} />
        <Route path="inicio/chamadas" element={<ManagementChamadasPage />} />
        <Route path="inicio/chamadas-dev" element={<RequireAdmin><DevChamadasContatosPage /></RequireAdmin>} />
        <Route path="inicio/turnos" element={<RequireAdmin><ManagementShiftsPage /></RequireAdmin>} />
        <Route path="inicio/sistema" element={<RequireAdmin><ManagementSystemPage /></RequireAdmin>} />
        <Route path="inicio/cadastro" element={<RequireAdmin><ManagementUsersPage /></RequireAdmin>} />
        <Route path="inicio/ia" element={<AIPage />} />

        <Route path="consulta-operacional/visao-geral" element={<OperationsOverviewPage />} />
        <Route path="consulta-operacional/recursos" element={<OperationsResourcesPage />} />
        <Route path="consulta-operacional/ops-em-andamento" element={<OperationsOrdersPage />} />
        <Route path="consulta-operacional/tempo-mes" element={<OperationsTimePage />} />

        <Route path="areas/:areaId" element={<AreaPage />} />

        <Route path="producao/ordens"element={<ProductionOrdersPage />} />
        <Route path="producao/realizada" element={<ProductionCompletedPage />} />
        <Route path="producao/planejado-realizado" element={<ProductionPlanActualPage />} />
        <Route path="manufatura/tempo-padrao" element={<RequireStandardTimeAccess><StandardTimePage /></RequireStandardTimeAccess>} />
        <Route path="qualidade/cotas" element={<RequireQualityTemplateAccess><QualityTemplatesPage /></RequireQualityTemplateAccess>} />
        <Route path="qualidade/spc" element={<RequireQualityTemplateAccess detail="Esta tela é exclusiva da Qualidade e da administração. Peça a elas se precisar consultar o SPC."><QualitySpcPage /></RequireQualityTemplateAccess>} />
        <Route path="manutencao/sugestoes" element={<RequireMaintenanceAccess><MaintenanceSuggestionsPage /></RequireMaintenanceAccess>} />

        <Route path="diretoria" element={<RequireDiretoriaAccess><DirectorPage /></RequireDiretoriaAccess>} />

        <Route path="melhoria-continua" element={<ImprovementPage />} />

        <Route path="analises/oee" element={<AnalyticsOeePage />} />
        <Route path="analises/horas-utilizacao" element={<AnalyticsHoursPage />} />
        <Route path="analises/paradas" element={<AnalyticsDowntimesPage />} />
        <Route path="analises/qualidade" element={<AnalyticsQualityPage />} />
        <Route path="analises/tempo-padrao-real" element={<AnalyticsStandardPage />} />
        <Route path="analises/cronoanalise" element={<AnalyticsChronoPage />} />
        <Route path="analises/capacidade-gargalos" element={<AnalyticsCapacityPage />} />
        <Route path="analises/confiabilidade" element={<AnalyticsReliabilityPage />} />

        <Route path="auditoria/apontamentos" element={<AuditAppointmentsPage />} />
        <Route path="auditoria/inconsistencias" element={<AuditIssuesPage />} />
        <Route path="auditoria/confiabilidade" element={<AuditReliabilityPage />} />

        <Route path="relatorios/gerencial" element={<ManagementReportPage />} />
        <Route path="relatorios/producao" element={<ProductionReportPage />} />
        <Route path="relatorios/perdas" element={<LossesReportPage />} />
        <Route path="relatorios/indicadores" element={<IndicatorsReportPage />} />
        <Route path="relatorios/dados-analiticos" element={<AnalyticalDataReportPage />} />

        <Route path="rastreabilidade/op-produto" element={<TraceabilityOrderPage />} />
        <Route path="rastreabilidade/linha-do-tempo" element={<TraceabilityTimelinePage />} />
        <Route path="rastreabilidade/lote-material-nesting" element={<TraceabilityNestingPage />} />
      </Route>
      <Route path="/operador/*" element={<RequireAuth operator><OperatorPortalPage /></RequireAuth>} />
      <Route path="/manutencao" element={<RequireAuth maintenance><MaintenanceTerminalPage /></RequireAuth>} />
      <Route path="*" element={<RoleHome />} />
    </Routes>
  );
}

function RoleHome() {
  const { user, loading } = useAuth();
  if (loading) return <div className="app-loading"><LoadingState label="Verificando sessão…" /></div>;
  if (!user) return <Navigate to="/login" replace />;
  return <Navigate to={roleHome(user)} replace />;
}
