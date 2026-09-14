import { FormEvent, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { assets } from "../config/assets";

export function LoginPage() {
  const { user, login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  const homeFor = (account: { management_access: boolean; andon_access?: boolean }) => {
    if (account.management_access) return "/inicio/visao-geral";
    if (account.andon_access) return "/andon";
    return "/operador";
  };

  if (user) return <Navigate to={homeFor(user)} replace />;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const authenticated = await login(username, password);
      const requested = (location.state as { from?: string } | null)?.from;
      navigate(requested ?? homeFor(authenticated), { replace: true });
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Não foi possível entrar.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-card">
        <img className="login-card__logo" src={assets.logo} alt="Gestor de Peças" />
        <div>
          <p>Gestão industrial e execução real</p>
          <h1>Entrar no Gestor</h1>
        </div>
        <form onSubmit={submit}>
          <label>
            Usuário
            <input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required />
          </label>
          <label>
            Senha
            <input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required />
          </label>
          {error ? <p className="form-error" role="alert">{error}</p> : null}
          <button type="submit" disabled={submitting}>{submitting ? "Entrando…" : "Entrar"}</button>
        </form>
        <small>Use o mesmo usuário do Gestor de Peças.</small>
      </section>
    </main>
  );
}
