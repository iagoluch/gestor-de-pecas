import type { PropsWithChildren } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { LoadingState } from "./components/DataState";
import { FilterProvider } from "./filters/FilterContext";
import { AppShell } from "./layouts/AppShell";
import { LoginPage } from "./pages/LoginPage";
import { AndonPage } from "./pages/AndonPage";
import { WeldingManagementPage } from "./pages/WeldingManagementPage";
import { ManagementOverviewPage } from "./pages/ManagementOverviewPage";
import { ManagementGoalsPage } from "./pages/home/GoalsPage";
import { ManagementPausesPage } from "./pages/home/PausesPage";
import { ManagementBadgesPage } from "./pages/home/BadgesPage";
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
  AnalyticsSetupPage,
  AnalyticsStandardPage,
} from "./pages/analytics/AnalyticsPages";
import { AuditAppointmentsPage, AuditIssuesPage, AuditReliabilityPage } from "./pages/audit/AuditPages";
import { HomeAlertsPage, HomeSectorsPage } from "./pages/home/HomePages";
import { OperationsOrdersPage, OperationsOverviewPage, OperationsResourcesPage, OperationsTimePage } from "./pages/operations/OperationsPages";
import { ProductionCompletedPage, ProductionOrdersPage, ProductionPlanActualPage } from "./pages/production/ProductionPages";
import {
  AnalyticalDataReportPage,
  IndicatorsReportPage,
  LossesReportPage,
  ManagementReportPage,
  ProductionReportPage,
} from "./pages/reports/ReportsPages";
import { TraceabilityNestingPage, TraceabilityOrderPage, TraceabilityTimelinePage } from "./pages/traceability/TraceabilityPages";

function roleHome(user: { management_access: boolean; andon_access?: boolean }) {
  if (user.management_access) return "/inicio/visao-geral";
  if (user.andon_access) return "/andon";
  return "/operador";
}

function RequireAuth({ management = false, andon = false, operator = false, children }: PropsWithChildren<{ management?: boolean; andon?: boolean; operator?: boolean }>) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="app-loading"><LoadingState label="Verificando sessão…" /></div>;
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  if (management && !user.management_access) return <Navigate to={roleHome(user)} replace />;
  if (andon && !user.andon_access && !user.management_access) return <Navigate to={roleHome(user)} replace />;
  if (operator && !user.operator_access) return <Navigate to={roleHome(user)} replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/andon" element={<RequireAuth andon><AndonPage /></RequireAuth>} />
      {/* Visão gerencial da Solda. Compartilha a autorização do Andon porque
          participa do mesmo ciclo de TV, sem aplicação nem login separados. */}
      <Route path="/welding-management" element={<RequireAuth andon><WeldingManagementPage /></RequireAuth>} />
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
        <Route path="inicio/solda" element={<Navigate to="/welding-management" replace />} />
        <Route path="inicio/metas" element={<ManagementGoalsPage />} />
        <Route path="inicio/pausas" element={<ManagementPausesPage />} />
        <Route path="inicio/crachas" element={<ManagementBadgesPage />} />
        <Route path="inicio/ia" element={<AIPage />} />

        <Route path="consulta-operacional/visao-geral" element={<OperationsOverviewPage />} />
        <Route path="consulta-operacional/recursos" element={<OperationsResourcesPage />} />
        <Route path="consulta-operacional/ops-em-andamento" element={<OperationsOrdersPage />} />
        <Route path="consulta-operacional/tempo-mes" element={<OperationsTimePage />} />

        <Route path="producao/ordens" element={<ProductionOrdersPage />} />
        <Route path="producao/realizada" element={<ProductionCompletedPage />} />
        <Route path="producao/planejado-realizado" element={<ProductionPlanActualPage />} />

        <Route path="analises/oee" element={<AnalyticsOeePage />} />
        <Route path="analises/horas-utilizacao" element={<AnalyticsHoursPage />} />
        <Route path="analises/paradas" element={<AnalyticsDowntimesPage />} />
        <Route path="analises/setup" element={<AnalyticsSetupPage />} />
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
