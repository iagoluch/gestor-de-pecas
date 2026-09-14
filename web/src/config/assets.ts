import logo from "../../../assets/branding/logo_gestor_pecas.png";
import profile from "../../../assets/branding/icone_perfil.png";
import home from "../../../assets/web/navigation/home.png";
import operations from "../../../assets/web/navigation/operations.png";
import production from "../../../assets/web/navigation/production.png";
import analytics from "../../../assets/web/navigation/analytics.png";
import audit from "../../../assets/web/navigation/audit.png";
import reports from "../../../assets/web/navigation/reports.png";
import traceability from "../../../assets/web/navigation/traceability.png";
import search from "../../../assets/icons/Pesquisa.svg";
import clock from "../../../assets/icons/Relógio.svg";
import trash from "../../../assets/icons/Lixeira.svg";
import operatorLogo from "../../../assets/operator_mockup/logo_operator.png";
import operatorProfile from "../../../assets/operator_mockup/profile_operator_transparent.png";
import actionStart from "../../../assets/operator_mockup/action_start.png";
import actionStop from "../../../assets/operator_mockup/action_stop.png";
import actionFinish from "../../../assets/operator_mockup/action_finish.png";
import actionSetup from "../../../assets/operator_mockup/action_setup.png";
import actionRework from "../../../assets/operator_mockup/action_rework.png";
import navDestaque from "../../../assets/operator_mockup/nav_destaque_transparent.png";
import navDobra from "../../../assets/operator_mockup/nav_dobra_transparent.png";
import navUsinagem from "../../../assets/operator_mockup/nav_usinagem_transparent.png";
import navSerra from "../../../assets/operator_mockup/nav_serra_transparent.png";
import navCorte from "../../../assets/operator_mockup/nav_corte_transparent.png";
import navPintura from "../../../assets/operator_mockup/nav_pintura_transparent.png";
import navSolda from "../../../assets/operator_mockup/nav_solda_transparent.png";
// Os ícones de navegação usam as variantes transparentes: o recorte veio da
// aba ativa (azul) e, sem o chroma-key, o fundo aparecia como um quadrado
// sobre a aba inativa. A Qualidade reutiliza o ícone oficial de auditoria;
// nenhum asset novo foi inventado.
import navQualidade from "../../../assets/web/navigation/audit.png";
import dobra1303 from "../../../assets/icons/Dobra_1303.svg";
import dobra2204 from "../../../assets/icons/Dobra_2204.svg";
import dobraGasparini from "../../../assets/icons/Gasparini.svg";
import serraSfg from "../../../assets/icons/Serra_SFG-330.png";
import serraS4220 from "../../../assets/icons/Serra_S4220.png";
import serraSfha from "../../../assets/icons/Serra_SFHA-10.png";
// Fotos oficiais das máquinas de Usinagem, extraídas do MP-CAL-001 (Manual de
// Processos Fabris GTS, rev. 02) — seções 8.1.1 a 8.1.4 — e recortadas com
// fundo transparente. O nome de cada chave é exatamente o do cadastro do posto
// em `app/core/resource_mapping.py`; nenhum nome foi criado aqui.
import usinagemRomiD1000 from "../../../assets/icons/Usinagem_RomiD1000.png";
import usinagemEurostec from "../../../assets/icons/Usinagem_Eurostec.png";
import usinagemRomiGl350m from "../../../assets/icons/Usinagem_RomiGL350M.png";
import usinagemFresadoraFtv31 from "../../../assets/icons/Usinagem_FresadoraFTV31.png";
import cortePlasma from "../../../assets/icons/Corte_TerraBlade4.png";
import corteLaser from "../../../assets/icons/Corte_Ensis3015.jpg";
import logoDobra from "../../../assets/icons/Logo_Dobra.svg";
import logoUsinagem from "../../../assets/icons/Logo_Usinagem.svg";
import logoSerra from "../../../assets/icons/Logo_Serra.svg";
import logoCorte from "../../../assets/icons/Logo_Corte.svg";

export const assets = {
  logo,
  profile,
  search,
  clock,
  trash,
  operator: {
    logo: operatorLogo,
    profile: operatorProfile,
    actions: { start: actionStart, stop: actionStop, finish: actionFinish, setup: actionSetup, rework: actionRework },
    navigation: { Destaque: navDestaque, Dobra: navDobra, Usinagem: navUsinagem, Serra: navSerra, Corte: navCorte, Pintura: navPintura, Solda: navSolda, Qualidade: navQualidade,
      // Wave 6F — os cinco setores que substituíram a antiga "Solda"
      // reaproveitam o mesmo ícone da frente até a arte própria existir.
      "Solda Aço": navSolda, "Solda Alumínio": navSolda, "Solda Robô": navSolda,
      "Proj. Ferramentaria": navSolda, "Protótipo": navSolda },
    resources: {
      "1303": dobra1303,
      "2204": dobra2204,
      Gasparini: dobraGasparini,
      "SFG-330": serraSfg,
      S4220: serraS4220,
      "SFHA-10": serraSfha,
      "Romi D 1000": usinagemRomiD1000,
      Eurostec: usinagemEurostec,
      "Romi GL 350M": usinagemRomiGl350m,
      "Fresadora FTV31": usinagemFresadoraFtv31,
      "Plasma TerraBlade 4": cortePlasma,
      "Laser Ensis 3015": corteLaser,
    },
    sectors: { Dobra: logoDobra, Usinagem: logoUsinagem, Serra: logoSerra, Corte: logoCorte },
  },
  navigation: {
    home,
    operations,
    production,
    analytics,
    audit,
    reports,
    traceability,
  },
} as const;
