import { api } from "./api";

export async function loginSession(credentials) {
  const response = await api.post("/api/v1/auth/login", credentials);
  return response.data;
}

export async function getCurrentUser() {
  const response = await api.get("/api/v1/auth/me");
  return response.data;
}

export async function logoutSession() {
  await api.post("/api/v1/auth/logout");
}
