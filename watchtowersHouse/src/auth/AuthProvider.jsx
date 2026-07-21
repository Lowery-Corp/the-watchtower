import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { getCurrentUser, loginSession, logoutSession } from "../services/auth";
import { SESSION_EXPIRED_EVENT } from "../services/api";

const AuthContext = createContext(null);

function getLoginErrorMessage(error) {
  return error?.response?.status === 401
    ? "Invalid email or password."
    : "Unable to sign in right now. Try again shortly.";
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState("");

  const refreshCurrentUser = useCallback(async () => {
    const currentUser = await getCurrentUser();
    setUser(currentUser);
    return currentUser;
  }, []);

  const login = useCallback(async ({ email, password }) => {
    setAuthError("");
    try {
      await loginSession({ email, password });
      await refreshCurrentUser();
      return { ok: true };
    } catch (error) {
      const message = getLoginErrorMessage(error);
      setUser(null);
      setAuthError(message);
      return { ok: false, error: message };
    }
  }, [refreshCurrentUser]);

  const logout = useCallback(async () => {
    setAuthError("");
    try {
      await logoutSession();
      setUser(null);
      return { ok: true };
    } catch {
      const message = "Sign out could not be confirmed. Check your connection and try again.";
      setAuthError(message);
      return { ok: false, error: message };
    }
  }, []);

  useEffect(() => {
    let active = true;
    getCurrentUser()
      .then((currentUser) => {
        if (active) setUser(currentUser);
      })
      .catch(() => {
        if (active) setUser(null);
      })
      .finally(() => {
        if (active) setAuthLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const handleSessionExpired = () => {
      setUser(null);
      setAuthError("Your session expired. Sign in again to continue.");
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired);
  }, []);

  const clearAuthError = useCallback(() => setAuthError(""), []);

  const value = useMemo(() => ({
    user,
    authLoading,
    authError,
    isAuthenticated: Boolean(user),
    login,
    logout,
    clearAuthError,
  }), [user, authLoading, authError, login, logout, clearAuthError]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
}
