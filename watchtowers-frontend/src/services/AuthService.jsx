import { api } from "./api";

export const loginUser = async (username, password) => {
  try {
    const auth_payload = {
      username: username,
      password: password,
    };
    const response = await api.post("/api/v1/auth/login", auth_payload);
    return response.data;
  } catch (error) {
    throw error;
  }
};

export const registerUser = async (email, password) => {
  try {
    const response = await api.post("/api/v1/users/create", { email, password });
    return response.data;
  } catch (error) {
    throw error;
  }
};

export const logoutUser = async () => {
  try {
    const response = await api.post("/api/v1/auth/logout");
    return response.data;
  } catch (error) {
    throw error;
  }
};
