import axios from "axios";

const AUTH_URL = import.meta.env.VITE_SCRAPPYS_SCRAPYARD_URL;
export const SESSION_EXPIRED_EVENT = "scrappy:session-expired";

export const api = axios.create({
  baseURL: AUTH_URL,
  withCredentials: true,
});

export const notifySessionExpired = () => {
  window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
};
