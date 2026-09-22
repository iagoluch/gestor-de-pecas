import { Component, type ErrorInfo, type ReactNode } from "react";

/**
 * Rede de segurança para as superfícies Web: sem isso, qualquer exceção não
 * tratada durante o render derruba a árvore inteira do React e deixa só o
 * fundo azul padrão — sem aviso, sem forma de o operador entender o que houve.
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean }> {
  state = { hasError: false };

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Erro não tratado na interface Web:", error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="state-box state-box--error" role="alert">
          <strong>Esta tela encontrou um problema e precisa recarregar</strong>
          <span>Os dados já confirmados permanecem registrados. Recarregue para continuar.</span>
          <button type="button" onClick={() => window.location.reload()}>Recarregar</button>
        </div>
      );
    }
    return this.props.children;
  }
}
