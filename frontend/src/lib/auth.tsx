import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, tokens } from "./api";
import type { User } from "./types";

interface LoginResult {
  requires2fa: boolean;
  challengeToken?: string;
}

interface AuthState {
  user: User | null;
  loading: boolean;
  login(email: string, password: string): Promise<LoginResult>;
  completeTwoFactor(challengeToken: string, code: string): Promise<void>;
  logout(): Promise<void>;
  reload(): Promise<void>;
}

const Ctx = createContext<AuthState | null>(null);

export const STAFF_ROLES = ["support", "compliance", "finance", "admin", "super_admin"];

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const qc = useQueryClient();

  const reload = useCallback(async () => {
    try {
      setUser(await api<User>("/me"));
    } catch {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    tokens.onAuthLost(() => {
      tokens.set(null);
      setUser(null);
    });
    (async () => {
      if (tokens.hasSession() && (await tokens.bootstrap())) await reload();
      setLoading(false);
    })();
  }, [reload]);

  const finish = useCallback(
    async (data: { access_token: string }) => {
      tokens.set(data.access_token);
      await reload();
    },
    [reload],
  );

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      async login(email, password) {
        const data = await api("/auth/login", { body: { email, password } });
        if (data.requires_2fa) return { requires2fa: true, challengeToken: data.challenge_token };
        await finish(data);
        return { requires2fa: false };
      },
      async completeTwoFactor(challengeToken, code) {
        await finish(await api("/auth/login/2fa", { body: { challenge_token: challengeToken, code } }));
      },
      async logout() {
        try {
          await api("/auth/logout", { method: "POST" });
        } catch {
          /* already signed out */
        }
        tokens.set(null);
        qc.clear();
        setUser(null);
      },
      reload,
    }),
    [user, loading, finish, reload, qc],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}

export const isStaff = (u: User | null) => !!u && STAFF_ROLES.includes(u.role);
