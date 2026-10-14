import { FormEvent, useState } from "react";
import { apiErrorMessage } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { assets } from "../config/assets";

/** Mesmo mínimo do backend para contas de gestão (app/core/password_policy.py). */
const MIN_MANAGEMENT_PASSWORD_LENGTH = 8;
const DEFAULT_PASSWORD = "123456";

/**
 * Etapa obrigatória para conta de gestão que entrou com a senha padrão
 * (auditoria 14/10/2026, SEC-05). Operadores nunca passam por aqui.
 */
export function ChangePasswordPage() {
  const { user, changePassword, logout } = useAuth();
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (password.length < MIN_MANAGEMENT_PASSWORD_LENGTH) {
      setError(`A nova senha precisa ter pelo menos ${MIN_MANAGEMENT_PASSWORD_LENGTH} caracteres.`);
      return;
    }
    if (password === DEFAULT_PASSWORD) {
      setError("Escolha uma senha diferente da senha padrão.");
      return;
    }
    if (password !== confirmation) {
      setError("As duas senhas não são iguais.");
      return;
    }
    setError("");
    setSubmitting(true);
    try {
      await changePassword(password);
    } catch (reason) {
      setError(apiErrorMessage(reason));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-card">
        <img className="login-card__logo" src={assets.logo} alt="Gestor de Peças" />
        <h1>Defina uma nova senha</h1>
        <p>
          {user?.name ? `${user.name}, sua` : "Sua"} conta ainda usa a senha padrão. Para entrar na gestão,
          escolha uma senha nova com pelo menos {MIN_MANAGEMENT_PASSWORD_LENGTH} caracteres.
        </p>
        <form noValidate onSubmit={submit}>
          <label>
            Nova senha
            <input type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} required />
          </label>
          <label>
            Repita a nova senha
            <input type="password" autoComplete="new-password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} required />
          </label>
          {error ? <p className="form-error" role="alert">{error}</p> : null}
          <button type="submit" disabled={submitting}>{submitting ? "Salvando…" : "Salvar e entrar"}</button>
          <button type="button" className="login-card__secondary" onClick={() => void logout()} disabled={submitting}>
            Sair
          </button>
        </form>
      </section>
    </main>
  );
}
