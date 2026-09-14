import { useAuth } from "../auth/AuthContext";

export function OperatorPendingPage() {
  const { logout } = useAuth();
  return (
    <main className="pending-page">
      <section>
        <h1>Interface Web do operador em checkpoint</h1>
        <p>O fluxo produtivo continua disponível no aplicativo desktop enquanto a camada gerencial Web é validada.</p>
        <button type="button" onClick={() => void logout()}>Sair</button>
      </section>
    </main>
  );
}

