import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import * as api from "../api/endpoints";
import { ApiError, setAuthEventHandler } from "../api/http";
import type { MeData } from "../api/types";

interface AuthContextValue {
  me: MeData | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<MeData>;
  logout: () => Promise<void>;
  changePassword: (oldPassword: string, newPassword: string) => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<MeData | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.getMe();
      setMe(data);
    } catch (error) {
      // Only a 401 means the session is gone; transient/network errors must not
      // silently sign the user out.
      if (error instanceof ApiError && error.http === 401) {
        setMe(null);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Global auth-failure hook: expired session -> back to /login; forced
  // password change -> re-check /me so the router redirects to /account.
  useEffect(() => {
    setAuthEventHandler((event) => {
      if (event === "unauthenticated") {
        setMe(null);
      } else if (event === "password_change_required") {
        void refresh();
      }
    });
    return () => setAuthEventHandler(undefined);
  }, [refresh]);

  const login = useCallback(async (username: string, password: string) => {
    const { data } = await api.login(username, password);
    setMe(data);
    return data;
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      setMe(null);
    }
  }, []);

  const changePassword = useCallback(
    async (oldPassword: string, newPassword: string) => {
      await api.changePassword(oldPassword, newPassword);
      // Server revokes all sessions on success; force re-login.
      setMe(null);
    },
    [],
  );

  const value = useMemo<AuthContextValue>(
    () => ({ me, loading, login, logout, changePassword, refresh }),
    [me, loading, login, logout, changePassword, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}
