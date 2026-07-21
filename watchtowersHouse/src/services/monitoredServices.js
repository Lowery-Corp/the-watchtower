import { api } from "./api";

export async function listMonitoredServices() {
  const response = await api.get("/api/v1/services");
  return response.data;
}

export async function createMonitoredService(payload) {
  const response = await api.post("/api/v1/services", payload);
  return response.data;
}

export async function updateMonitoredService(serviceId, payload) {
  const response = await api.patch(`/api/v1/services/${serviceId}`, payload);
  return response.data;
}

export async function deactivateMonitoredService(serviceId) {
  await api.delete(`/api/v1/services/${serviceId}`);
}
