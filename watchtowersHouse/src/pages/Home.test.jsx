import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Home from "./Home";
import { listApiKeys } from "../services/apiKeys";
import { listMonitoredServices } from "../services/monitoredServices";

vi.mock("../auth/AuthProvider", () => ({
  useAuth: () => ({
    user: {
      username: "operator",
      display_name: "Operator",
      profile_id: "78b41fa2-9f50-4889-b7a5-6af21760af4f",
      is_admin: false,
    },
  }),
}));
vi.mock("../services/apiKeys", () => ({ listApiKeys: vi.fn() }));
vi.mock("../services/monitoredServices", () => ({ listMonitoredServices: vi.fn() }));

const serviceKey = {
  id: "d7914462-ed17-44d4-ae2c-5df727e62aed",
  credential_kind: "service_ingestion",
  expires_at: null,
  revoked_at: null,
};

const profileKey = {
  id: "54d70211-1d1e-4d94-8fb6-3bc8ea8f0a53",
  credential_kind: "profile_uptime",
  expires_at: null,
  revoked_at: null,
};

describe("Home", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listMonitoredServices.mockResolvedValue([]);
  });

  it("excludes profile uptime credentials from active and total service-key counts", async () => {
    listApiKeys.mockResolvedValue([
      serviceKey,
      profileKey,
      { ...serviceKey, id: "revoked-service-key", revoked_at: "2026-09-20T12:00:00Z" },
    ]);

    render(
      <MemoryRouter>
        <Home />
      </MemoryRouter>,
    );

    const activeCard = screen.getByText("Active API keys").closest("article");
    const totalCard = screen.getByText("Total API keys").closest("article");
    expect(await within(activeCard).findByText("1")).toBeVisible();
    expect(within(totalCard).getByText("2")).toBeVisible();
  });
});
