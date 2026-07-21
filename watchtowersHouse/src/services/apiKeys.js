import { api } from "./api";

export async function listApiKeys() {
  const response = await api.get("/api/v1/api-keys");
  return response.data;
}

export async function createApiKey(payload) {
  const response = await api.post("/api/v1/api-keys", payload);
  return response.data;
}

export async function updateApiKey(apiKeyId, payload) {
  const response = await api.patch(`/api/v1/api-keys/${apiKeyId}`, payload);
  return response.data;
}

export async function revokeApiKey(apiKeyId) {
  await api.delete(`/api/v1/api-keys/${apiKeyId}`);
}
