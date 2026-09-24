// Aplica o tema salvo antes da primeira pintura, pra não piscar claro e depois
// trocar pra escuro (ou o contrário) quando o React montar. Fica em arquivo
// próprio (e não inline no index.html) porque a CSP é `script-src 'self'`.
try {
  var storedTheme = localStorage.getItem("gestor.theme");
  if (storedTheme === "light" || storedTheme === "dark") {
    document.documentElement.dataset.theme = storedTheme;
  }
} catch (error) {
  // Storage bloqueado (aba privada etc.): segue o tema do sistema.
}
