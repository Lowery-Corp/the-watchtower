import axios from "axios";

export const SESSION_EXPIRED_EVENT = "watchtower:session-expired";

export const api = axios.create({
  baseURL: import.meta.env.VITE_WATCHTOWER_API_URL || "",
  withCredentials: true,
  headers: { Accept: "application/json" },
});

const AUTH_PATHS = ["/api/v1/auth/login", "/api/v1/auth/logout", "/api/v1/auth/me"];

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const requestUrl = error?.config?.url || "";
    const isAuthPath = AUTH_PATHS.some((path) => requestUrl.includes(path));
    if (error?.response?.status === 401 && !isAuthPath) {
      window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
    }
    return Promise.reject(error);
  },
);

export function getErrorMessage(error, fallback) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (!item || typeof item !== "object" || typeof item.msg !== "string") return "";
        const location = Array.isArray(item.loc) ? item.loc.at(-1) : "";
        return location ? `${location}: ${item.msg}` : item.msg;
      })
      .filter(Boolean);
    if (messages.length) return messages.join("; ");
  }
  return typeof error?.message === "string" && error.message.trim()
    ? error.message
    : fallback;
}
