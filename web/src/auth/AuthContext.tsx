import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { PropsWithChildren } from "react";
import { api, ApiError } from "../api/client";
import type { SessionUser } from "../types/api";

interface AuthValue {
  user: SessionUser | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<SessionUser>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: PropsWithChildren) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<SessionUser>("/api/v1/auth/session")
      .then(setUser)
      .catch((error) => {
        if (!(error instanceof ApiError) || error.status !== 401) console.error(error);
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const authenticated = await api.post<SessionUser>("/api/v1/auth/login", { username, password });
    setUser(authenticated);
    return authenticated;
  }, []);

  const logout = useCallback(async () => {
    await api.post<void>("/api/v1/auth/logout");
    setUser(null);
  }, []);

  const value = useMemo(() => ({ user, loading, login, logout }), [user, loading, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth deve ser usado dentro de AuthProvider.");
  return value;
}

/**
 * Variante que não explode fora do ``AuthProvider`` — usada por componentes
 * de layout (como ``PageFrame``) que também são montados isoladamente em
 * testes de tela sem a árvore de autenticação inteira.
 */
export function useOptionalAuth() {
  return useContext(AuthContext);
}

