import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { PropsWithChildren } from "react";
import { api, ApiError, SESSION_EXPIRED_EVENT, setActingSector } from "../api/client";
import { clearLastSnapshots } from "../hooks/useApiQuery";
import type { SessionUser } from "../types/api";

interface AuthValue {
  user: SessionUser | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<SessionUser>;
  changePassword: (newPassword: string) => Promise<SessionUser>;
  logout: () => Promise<void>;
  /** Entra no modo "apontar como setor" (nível do setor) e recarrega a sessão. A saída é `leaveActingSector`. */
  actAsSector: (level: string) => Promise<SessionUser>;
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

  useEffect(() => {
    const expired = () => {
      clearLastSnapshots();
      setUser(null);
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, expired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, expired);
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    setActingSector(null);
    const authenticated = await api.post<SessionUser>("/api/v1/auth/login", { username, password });
    setUser(authenticated);
    return authenticated;
  }, []);

  const changePassword = useCallback(async (newPassword: string) => {
    const released = await api.post<SessionUser>("/api/v1/auth/password", { new_password: newPassword });
    setUser(released);
    return released;
  }, []);

  const logout = useCallback(async () => {
    setActingSector(null);
    await api.post<void>("/api/v1/auth/logout");
    clearLastSnapshots();
    setUser(null);
  }, []);

  const actAsSector = useCallback(async (level: string) => {
    setActingSector(level);
    try {
      const next = await api.get<SessionUser>("/api/v1/auth/session");
      clearLastSnapshots();
      setUser(next);
      return next;
    } catch (error) {
      setActingSector(null);
      throw error;
    }
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, changePassword, logout, actAsSector }),
    [user, loading, login, changePassword, logout, actAsSector],
  );
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


/** Setores a que os dados da conta ficam restritos (`null` = fábrica toda ou sem login). */
export function useSectorScope(): string[] | null {
  const scope = useContext(AuthContext)?.user?.sector_scope;
  return scope?.length ? scope : null;
}
