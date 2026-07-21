import { api } from "./api";

export async function listMonitoredServices() {
  const response = await api.get("/api/v1/services");
  return response.data;
}
