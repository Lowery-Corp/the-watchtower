import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import App from "./App";

vi.mock("./auth/AuthProvider", () => ({
  useAuth: () => ({
    user: { username: "operator", display_name: "Operator", is_admin: false },
    authLoading: false,
    authError: null,
    isAuthenticated: true,
  }),
}));

describe("About route", () => {
  it("explains Watchtower and gives operators an implementation path", () => {
    render(
      <MemoryRouter initialEntries={["/about"]}>
        <App />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading", { level: 1, name: "About Watchtower" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "How Watchtower works" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Implement Watchtower in your service" })).toBeVisible();
    expect(screen.getByText("Register a monitored service")).toBeVisible();
    expect(screen.getByText("Issue a service-bound API key")).toBeVisible();
    expect(screen.getByText("Send version 1 events")).toBeVisible();
    expect(screen.getByText(/\/api\/v1\/webhooks\/events/)).toBeVisible();
    expect(screen.getByText(/X-Watchtower-API-Key/)).toBeVisible();
    expect(screen.getByText(/"spec_version": "1.0"/)).toBeVisible();
    expect(screen.getByRole("link", { name: "Open Services" })).toHaveAttribute("href", "/services");
    expect(screen.getByRole("link", { name: "Open API Keys" })).toHaveAttribute("href", "/api-keys");
  });
});
