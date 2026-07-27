import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { SESSION_EXPIRED_EVENT, api, notifySessionExpired } from "../services/api";

const AuthContext = createContext(null);

const SESSION_EXPIRATION_IGNORED_PATHS = [
  "/api/v1/auth/login",
  "/api/v1/auth/logout",
  "/api/v1/auth/me",
  "/api/v1/auth/register",
];

const shouldHandleSessionExpiration = (error) => {
  if (error?.response?.status !== 401) {
    return false;
  }

  const requestUrl = error?.config?.url ?? "";
  return !SESSION_EXPIRATION_IGNORED_PATHS.some((path) =>
    requestUrl.includes(path)
  );
};

export function AuthProvider({ children }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [user, setUser] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState(null);

  const login = async ({ username, password }) => {
    try {
      setAuthError(null);

      const response = await api.post("/api/v1/auth/login", {
        email: username,
        password,
      });

      if (response.data?.user) {
        setUser(response.data.user);
        return { ok: true };
      }

      const meResponse = await api.get("/api/v1/auth/me");
      if (meResponse.data?.user) {
        setUser(meResponse.data.user);
        return { ok: true };
      }

      const message = "Login failed";
      setAuthError(message);
      return { ok: false, error: message };
    } catch (error) {
      const message =
        error?.response?.data?.detail ||
        error?.response?.data?.message ||
        "Login failed";

      setAuthError(message);
      setUser(null);

      return {
        ok: false,
        error: message,
      };
    }
  };

  const logout = async () => {
    try {
      await api.post("/api/v1/auth/logout");
    } catch {
      // ignore logout API errors and still clear local user state
    } finally {
      setUser(null);
      setAuthError(null);
    }
  };

  const createUser = async ({ username, password }) => {
    try {
      setAuthError(null);

      const response = await api.post("/api/v1/auth/register", {
        email: username,
        password,
      });

      if (response.data?.ok === true) {
        const loginResult = await login({ username, password });

        if (!loginResult.ok) {
          const message = loginResult.error || "User created but login failed";
          setAuthError(message);
          return { ok: false, error: message };
        }

        return { ok: true };
      }

      const message = response.data?.message || "User creation failed";
      setAuthError(message);
      return { ok: false, error: message };
    } catch (error) {
      const message =
        error?.response?.data?.detail ||
        error?.response?.data?.message ||
        "User creation failed";

      setAuthError(message);

      return {
        ok: false,
        error: message,
      };
    }
  };

  const hasPermission = (permission) => {
    if (!user) return false;
    return (user.permissions || []).includes(permission);
  };

  const handleSessionExpired = useCallback(() => {
    setUser(null);
    setAuthError("Your session has expired. Please log in again.");

    if (!location.pathname.startsWith("/user/login")) {
      navigate("/user/login", {
        replace: true,
        state: { from: location },
      });
    }
  }, [location, navigate]);

  useEffect(() => {
    const interceptorId = api.interceptors.response.use(
      (response) => response,
      (error) => {
        if (shouldHandleSessionExpiration(error)) {
          notifySessionExpired();
        }

        return Promise.reject(error);
      }
    );

    return () => {
      api.interceptors.response.eject(interceptorId);
    };
  }, []);

  useEffect(() => {
    window.addEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired);

    return () => {
      window.removeEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired);
    };
  }, [handleSessionExpired]);

  useEffect(() => {
    const loadCurrentUser = async () => {
      try {
        setAuthError(null);

        const response = await api.get("/api/v1/auth/me");
        if (response.data?.user) {
          setUser(response.data.user);
        } else {
          setUser(null);
        }
      } catch {
        setUser(null);
      } finally {
        setAuthLoading(false);
      }
    };

    loadCurrentUser();
  }, []);

  const value = useMemo(
    () => ({
      user,
      authError,
      login,
      logout,
      createUser,
      hasPermission,
      isAuthenticated: !!user,
      authLoading,
      clearAuthError: () => setAuthError(null),
    }),
    [user, authError, authLoading]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const context = useContext(AuthContext);

  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }

  return context;
}