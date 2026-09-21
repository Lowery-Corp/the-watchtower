import { api } from "./api";

export async function listUptimeMonitors() {
  const response = await api.get("/api/v1/uptime-monitors");
  return response.data;
}

export async function createUptimeMonitor(payload) {
  const response = await api.post("/api/v1/uptime-monitors", payload);
  return response.data;
}

export async function deactivateUptimeMonitor(monitorId) {
  await api.delete(`/api/v1/uptime-monitors/${monitorId}`);
}
