import { lazy } from "react";

export const AndonPage = lazy(() => import("../pages/AndonPage").then((module) => ({ default: module.AndonPage })));
export const WeldingManagementPage = lazy(() => import("../pages/WeldingManagementPage").then((module) => ({ default: module.WeldingManagementPage })));
export const ManagementOverviewPage = lazy(() => import("../pages/ManagementOverviewPage").then((module) => ({ default: module.ManagementOverviewPage })));
export const AIPage = lazy(() => import("../pages/AIPage").then((module) => ({ default: module.AIPage })));
export const OperatorPortalPage = lazy(() => import("../pages/operator/OperatorPortalPage").then((module) => ({ default: module.OperatorPortalPage })));

export const ManagementGoalsPage = lazy(() => import("../pages/home/GoalsPage").then((module) => ({ default: module.ManagementGoalsPage })));
export const ManagementPausesPage = lazy(() => import("../pages/home/PausesPage").then((module) => ({ default: module.ManagementPausesPage })));
export const ManagementBadgesPage = lazy(() => import("../pages/home/BadgesPage").then((module) => ({ default: module.ManagementBadgesPage })));
export const ManagementChamadasPage = lazy(() => import("../pages/home/ChamadasPage").then((module) => ({ default: module.ManagementChamadasPage })));
export const ManagementShiftsPage = lazy(() => import("../pages/home/ShiftsPage").then((module) => ({ default: module.ManagementShiftsPage })));
export const ManagementSystemPage = lazy(() => import("../pages/home/SystemPage").then((module) => ({ default: module.ManagementSystemPage })));
export const ManagementUsersPage = lazy(() => import("../pages/home/UsersPage").then((module) => ({ default: module.ManagementUsersPage })));
export const HomeAlertsPage = lazy(() => import("../pages/home/HomePages").then((module) => ({ default: module.HomeAlertsPage })));
export const HomeSectorsPage = lazy(() => import("../pages/home/HomePages").then((module) => ({ default: module.HomeSectorsPage })));

export const OperationsOrdersPage = lazy(() => import("../pages/operations/OperationsPages").then((module) => ({ default: module.OperationsOrdersPage })));
export const OperationsOverviewPage = lazy(() => import("../pages/operations/OperationsPages").then((module) => ({ default: module.OperationsOverviewPage })));
export const OperationsResourcesPage = lazy(() => import("../pages/operations/OperationsPages").then((module) => ({ default: module.OperationsResourcesPage })));
export const OperationsTimePage = lazy(() => import("../pages/operations/OperationsPages").then((module) => ({ default: module.OperationsTimePage })));

export const ProductionCompletedPage = lazy(() => import("../pages/production/ProductionPages").then((module) => ({ default: module.ProductionCompletedPage })));
export const ProductionOrdersPage = lazy(() => import("../pages/production/ProductionPages").then((module) => ({ default: module.ProductionOrdersPage })));
export const ProductionPlanActualPage = lazy(() => import("../pages/production/ProductionPages").then((module) => ({ default: module.ProductionPlanActualPage })));

export const AnalyticsCapacityPage = lazy(() => import("../pages/analytics/AnalyticsPages").then((module) => ({ default: module.AnalyticsCapacityPage })));
export const AnalyticsChronoPage = lazy(() => import("../pages/analytics/AnalyticsPages").then((module) => ({ default: module.AnalyticsChronoPage })));
export const AnalyticsDowntimesPage = lazy(() => import("../pages/analytics/AnalyticsPages").then((module) => ({ default: module.AnalyticsDowntimesPage })));
export const AnalyticsHoursPage = lazy(() => import("../pages/analytics/AnalyticsPages").then((module) => ({ default: module.AnalyticsHoursPage })));
export const AnalyticsOeePage = lazy(() => import("../pages/analytics/AnalyticsPages").then((module) => ({ default: module.AnalyticsOeePage })));
export const AnalyticsQualityPage = lazy(() => import("../pages/analytics/AnalyticsPages").then((module) => ({ default: module.AnalyticsQualityPage })));
export const AnalyticsReliabilityPage = lazy(() => import("../pages/analytics/AnalyticsPages").then((module) => ({ default: module.AnalyticsReliabilityPage })));
export const AnalyticsStandardPage = lazy(() => import("../pages/analytics/AnalyticsPages").then((module) => ({ default: module.AnalyticsStandardPage })));

export const AuditAppointmentsPage = lazy(() => import("../pages/audit/AuditPages").then((module) => ({ default: module.AuditAppointmentsPage })));
export const AuditIssuesPage = lazy(() => import("../pages/audit/AuditPages").then((module) => ({ default: module.AuditIssuesPage })));
export const AuditReliabilityPage = lazy(() => import("../pages/audit/AuditPages").then((module) => ({ default: module.AuditReliabilityPage })));

export const AnalyticalDataReportPage = lazy(() => import("../pages/reports/ReportsPages").then((module) => ({ default: module.AnalyticalDataReportPage })));
export const IndicatorsReportPage = lazy(() => import("../pages/reports/ReportsPages").then((module) => ({ default: module.IndicatorsReportPage })));
export const LossesReportPage = lazy(() => import("../pages/reports/ReportsPages").then((module) => ({ default: module.LossesReportPage })));
export const ManagementReportPage = lazy(() => import("../pages/reports/ReportsPages").then((module) => ({ default: module.ManagementReportPage })));
export const ProductionReportPage = lazy(() => import("../pages/reports/ReportsPages").then((module) => ({ default: module.ProductionReportPage })));

export const TraceabilityNestingPage = lazy(() => import("../pages/traceability/TraceabilityPages").then((module) => ({ default: module.TraceabilityNestingPage })));
export const TraceabilityOrderPage = lazy(() => import("../pages/traceability/TraceabilityPages").then((module) => ({ default: module.TraceabilityOrderPage })));
export const TraceabilityTimelinePage = lazy(() => import("../pages/traceability/TraceabilityPages").then((module) => ({ default: module.TraceabilityTimelinePage })));
