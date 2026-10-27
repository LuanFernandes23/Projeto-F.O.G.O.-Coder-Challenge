import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useSyncExternalStore,
} from "react";
import type { ReactNode } from "react";

import { api } from "@/lib/api/client";
import type { CurrentUser, Permission } from "@/lib/api/types";
import { tokenStore } from "@/lib/auth-store";

interface AuthContextValue {
  user: CurrentUser | undefined;
  isAuthenticated: boolean;
  isLoading: boolean;
  can: (permission: Permission) => boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const token = useSyncExternalStore(tokenStore.subscribe, tokenStore.get, () => null);
  const queryClient = useQueryClient();
  const me = useQuery({
    queryKey: ["auth", "me", token],
    queryFn: () => api<CurrentUser>("/auth/me"),
    enabled: Boolean(token),
    staleTime: 5 * 60_000,
    retry: false,
  });

  useEffect(() => {
    if (!token) queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== "auth" });
  }, [token, queryClient]);

  const login = useCallback(async (email: string, password: string) => {
    const form = new URLSearchParams({ username: email, password });
    const result = await api<{ access_token: string }>("/auth/token", { method: "POST", form });
    tokenStore.set(result.access_token);
  }, []);

  const logout = useCallback(() => tokenStore.clear(), []);

  const value = useMemo<AuthContextValue>(() => {
    const permissions = new Set(me.data?.permissions ?? []);
    return {
      user: me.data,
      isAuthenticated: Boolean(token && me.data),
      isLoading: Boolean(token) && me.isLoading,
      can: (permission) => permissions.has(permission),
      login,
      logout,
    };
  }, [me.data, me.isLoading, token, login, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth deve ser usado dentro de <AuthProvider>");
  return context;
}
