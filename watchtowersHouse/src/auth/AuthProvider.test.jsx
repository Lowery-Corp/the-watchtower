import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import App from "../App";
import { AuthProvider } from "./AuthProvider";
import { getCurrentUser, loginSession, logoutSession } from "../services/auth";
import { SESSION_EXPIRED_EVENT } from "../services/api";
import { listApiKeys } from "../services/apiKeys";
import { listMonitoredServices } from "../services/monitoredServices";

vi.mock("../services/auth", () => ({
  getCurrentUser: vi.fn(),
  loginSession: vi.fn(),
  logoutSession: vi.fn(),
}));

vi.mock("../services/apiKeys", () => ({ listApiKeys: vi.fn() }));
vi.mock("../services/monitoredServices", () => ({
  createMonitoredService: vi.fn(),
  deactivateMonitoredService: vi.fn(),
  listMonitoredServices: vi.fn(),
  updateMonitoredService: vi.fn(),
}));

describe("browser authentication", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listApiKeys.mockResolvedValue([]);
    listMonitoredServices.mockResolvedValue([]);
  });

  it("logs in, provisions the current profile, and opens Home", async () => {
    getCurrentUser
      .mockRejectedValueOnce({ response: { status: 401 } })
      .mockResolvedValueOnce({
        id: "2b18df27-4f10-4edf-9bc0-da25674f17a8",
        username: "watcher@example.com",
        is_admin: false,
        profile_id: "464c8d2a-11ac-498e-92d0-aed71ea16c94",
        display_name: "Night Watch",
      });
    loginSession.mockResolvedValue({
      id: "2b18df27-4f10-4edf-9bc0-da25674f17a8",
      username: "watcher@example.com",
      is_admin: false,
    });

    render(
      <MemoryRouter initialEntries={["/login"]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    );

    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/email/i), "watcher@example.com");
    await user.type(
      screen.getByLabelText(/password/i),
      "correct horse battery staple",
    );
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(loginSession).toHaveBeenCalledWith({
      email: "watcher@example.com",
      password: "correct horse battery staple",
    });
    expect(getCurrentUser).toHaveBeenCalledTimes(2);
    expect(
      await screen.findByRole("heading", { name: /welcome back, night watch/i }),
    ).toBeVisible();
  });

  it("protects the monitored-services route from anonymous users", async () => {
    getCurrentUser.mockRejectedValueOnce({ response: { status: 401 } });

    render(
      <MemoryRouter initialEntries={["/services"]}>
        <AuthProvider><App /></AuthProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: /sign in to watchtower/i })).toBeVisible();
  });

  it("returns to the requested protected route after login", async () => {
    getCurrentUser
      .mockRejectedValueOnce({ response: { status: 401 } })
      .mockResolvedValueOnce({
        id: "user-1",
        username: "watcher@example.com",
        is_admin: false,
        profile_id: "profile-1",
        display_name: "Night Watch",
      });
    loginSession.mockResolvedValue({ id: "user-1", username: "watcher@example.com" });

    render(
      <MemoryRouter initialEntries={[{
        pathname: "/login",
        state: { from: { pathname: "/services" } },
      }]}>
        <AuthProvider><App /></AuthProvider>
      </MemoryRouter>,
    );

    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/email/i), "watcher@example.com");
    await user.type(screen.getByLabelText(/password/i), "test-password");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByRole("heading", { name: "Monitored Services" })).toBeVisible();
  });

  it("keeps a generic backend authentication failure visible", async () => {
    getCurrentUser.mockRejectedValueOnce({ response: { status: 401 } });
    loginSession.mockRejectedValueOnce({
      response: { status: 401, data: { detail: "Authentication failed" } },
    });

    render(
      <MemoryRouter initialEntries={["/login"]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    );

    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/email/i), "wrong@example.com");
    await user.type(screen.getByLabelText(/password/i), "not-the-password");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password");
    expect(screen.getByRole("button", { name: /sign in/i })).toBeEnabled();
  });

  it("summarizes profile services and active API keys on Home", async () => {
    getCurrentUser.mockResolvedValue({
      id: "2b18df27-4f10-4edf-9bc0-da25674f17a8",
      username: "watcher@example.com",
      is_admin: false,
      profile_id: "464c8d2a-11ac-498e-92d0-aed71ea16c94",
      display_name: "Night Watch",
    });
    listMonitoredServices.mockResolvedValue([{ id: "service-1", active: true }]);
    listApiKeys.mockResolvedValue([
      {
        id: "key-1",
        credential_kind: "service_ingestion",
        revoked_at: null,
        expires_at: null,
      },
      {
        id: "key-2",
        credential_kind: "service_ingestion",
        revoked_at: "2026-07-20T23:30:00Z",
        expires_at: null,
      },
      {
        id: "key-3",
        credential_kind: "service_ingestion",
        revoked_at: null,
        expires_at: "2020-01-01T00:00:00Z",
      },
      {
        id: "profile-key",
        credential_kind: "profile_uptime",
        revoked_at: null,
        expires_at: null,
      },
    ]);

    render(
      <MemoryRouter initialEntries={["/home"]}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByText("Monitored services").parentElement).toHaveTextContent("1");
      expect(screen.getByText("Active API keys").parentElement).toHaveTextContent("1");
      expect(screen.getByText("Total API keys").parentElement).toHaveTextContent("3");
    });
  });

  it("preserves the session-expiration explanation after redirecting to Login", async () => {
    getCurrentUser.mockResolvedValue({
      id: "user-1",
      username: "watcher@example.com",
      is_admin: false,
      profile_id: "profile-1",
      display_name: "Night Watch",
    });

    render(
      <MemoryRouter initialEntries={["/home"]}>
        <AuthProvider><App /></AuthProvider>
      </MemoryRouter>,
    );
    await screen.findByRole("heading", { name: /welcome back/i });

    act(() => window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT)));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Your session expired. Sign in again to continue.",
    );
    expect(screen.getByRole("button", { name: /sign in/i })).toBeVisible();
  });

  it("keeps the logout control from calling the deferred logout flow", async () => {
    getCurrentUser.mockResolvedValue({
      id: "user-1",
      username: "watcher@example.com",
      is_admin: false,
      profile_id: "profile-1",
      display_name: "Night Watch",
    });

    render(
      <MemoryRouter initialEntries={["/home"]}>
        <AuthProvider><App /></AuthProvider>
      </MemoryRouter>,
    );
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /sign out/i }));

    expect(logoutSession).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /welcome back/i })).toBeVisible();
  });
});
