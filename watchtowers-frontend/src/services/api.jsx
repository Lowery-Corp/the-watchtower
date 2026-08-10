import axios from "axios";

const WATCHTOWER_BACKEND = import.meta.env.VITE_WATCHTOWER_BACKEND_URL;
export const SESSION_EXPIRED_EVENT = "watchtower:session-expired";

export const api = axios.create({
  baseURL: WATCHTOWER_BACKEND,
  withCredentials: true,
});

export const notifySessionExpired = () => {
  window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
};
