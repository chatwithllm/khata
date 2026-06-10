/**
 * App-wide auth state. On mount it loads any stored token and validates it via
 * GET /api/auth/me; screens read `user` + status to gate navigation. Login/
 * register/google all funnel through `authenticate`, which persists the token
 * then fetches the user.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import * as authApi from '../api/auth';
import type { AuthResponse, User } from '../api/types';
import { clearToken, loadToken, setToken } from './session';

type Status = 'loading' | 'authenticated' | 'unauthenticated';

type AuthContextValue = {
  status: Status;
  user: User | null;
  signIn: (fn: () => Promise<AuthResponse>) => Promise<void>;
  signOut: () => Promise<void>;
  setUser: (u: User) => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<Status>('loading');
  const [user, setUserState] = useState<User | null>(null);

  useEffect(() => {
    (async () => {
      const token = await loadToken();
      if (!token) {
        setStatus('unauthenticated');
        return;
      }
      try {
        const { user } = await authApi.me();
        setUserState(user);
        setStatus('authenticated');
      } catch {
        await clearToken();
        setStatus('unauthenticated');
      }
    })();
  }, []);

  const signIn = useCallback(async (fn: () => Promise<AuthResponse>) => {
    const res = await fn();
    await setToken(res.token);
    setUserState(res.user);
    setStatus('authenticated');
  }, []);

  const signOut = useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      // best-effort; we clear the token regardless
    }
    await clearToken();
    setUserState(null);
    setStatus('unauthenticated');
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ status, user, signIn, signOut, setUser: setUserState }),
    [status, user, signIn, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
