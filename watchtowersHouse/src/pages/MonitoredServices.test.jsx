import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MonitoredServices from "./MonitoredServices";
import {
  createMonitoredService,
  deactivateMonitoredService,
  listMonitoredServices,
  updateMonitoredService,
} from "../services/monitoredServices";

vi.mock("../services/monitoredServices", () => ({
  createMonitoredService: vi.fn(),
  deactivateMonitoredService: vi.fn(),
  listMonitoredServices: vi.fn(),
  updateMonitoredService: vi.fn(),
}));

const service = {
  id: "f00dcafe-0922-4c06-98e5-b8f5e9d62fd0",
  slug: "payments-api",
  display_name: "Payments API",
  environment: "production",
  active: true,
  created_at: "2026-07-20T23:00:00Z",
  updated_at: "2026-07-20T23:00:00Z",
};

describe("Monitored Services", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listMonitoredServices.mockResolvedValue([]);
  });

  it("creates a profile-owned monitored service", async () => {
    createMonitoredService.mockResolvedValue(service);
    const user = userEvent.setup();
    render(<MonitoredServices />);

    await screen.findByText(/no monitored services registered/i);
    await user.click(screen.getByRole("button", { name: /add monitored service/i }));
    await user.type(screen.getByLabelText(/service slug/i), "payments-api");
    await user.type(screen.getByLabelText(/display name/i), "Payments API");
    await user.type(screen.getByLabelText(/environment/i), "production");
    await user.click(screen.getByRole("button", { name: /^create service$/i }));

    expect(createMonitoredService).toHaveBeenCalledWith({
      slug: "payments-api",
      display_name: "Payments API",
      environment: "production",
    });
    expect(await screen.findByText("Payments API")).toBeVisible();
    expect(screen.getByText("payments-api")).toBeVisible();
  });

  it("edits mutable service metadata without changing the slug", async () => {
    listMonitoredServices.mockResolvedValue([service]);
    updateMonitoredService.mockResolvedValue({
      ...service,
      display_name: "Payment Gateway",
      environment: "staging",
    });
    const user = userEvent.setup();
    render(<MonitoredServices />);

    await screen.findByText("Payments API");
    await user.click(screen.getByRole("button", { name: /edit payments api/i }));
    const name = screen.getByLabelText(/display name/i);
    const environment = screen.getByLabelText(/environment/i);
    await user.clear(name);
    await user.type(name, "Payment Gateway");
    await user.clear(environment);
    await user.type(environment, "staging");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    expect(updateMonitoredService).toHaveBeenCalledWith(service.id, {
      display_name: "Payment Gateway",
      environment: "staging",
    });
    expect(await screen.findByText("Payment Gateway")).toBeVisible();
    expect(screen.getByText("payments-api")).toBeVisible();
  });

  it("deactivates a service while retaining its historical row", async () => {
    listMonitoredServices.mockResolvedValue([service]);
    deactivateMonitoredService.mockResolvedValue();
    const user = userEvent.setup();
    render(<MonitoredServices />);

    await screen.findByText("Payments API");
    await user.click(screen.getByRole("button", { name: /deactivate payments api/i }));
    expect(screen.getByText(/historical events remain available/i)).toBeVisible();
    await user.click(screen.getByRole("button", { name: /^deactivate service$/i }));

    expect(deactivateMonitoredService).toHaveBeenCalledWith(service.id);
    expect(screen.getByText("Payments API")).toBeVisible();
    expect(await screen.findByText("Inactive")).toBeVisible();
  });

  it("reactivates an inactive service", async () => {
    const inactive = { ...service, active: false };
    listMonitoredServices.mockResolvedValue([inactive]);
    updateMonitoredService.mockResolvedValue({ ...service, active: true });
    const user = userEvent.setup();
    render(<MonitoredServices />);

    await screen.findByText("Inactive");
    await user.click(screen.getByRole("button", { name: /reactivate payments api/i }));

    expect(updateMonitoredService).toHaveBeenCalledWith(service.id, { active: true });
    expect(await screen.findByText("Active")).toBeVisible();
  });

  it("shows a retryable load failure instead of a false empty state", async () => {
    listMonitoredServices.mockRejectedValue({
      response: { data: { detail: "Service registry unavailable" } },
    });

    render(<MonitoredServices />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Service registry unavailable");
    expect(screen.getByRole("button", { name: /retry/i })).toBeVisible();
    expect(screen.queryByText(/no monitored services registered/i)).not.toBeInTheDocument();
  });

  it("rejects whitespace-only service fields before sending a request", async () => {
    const user = userEvent.setup();
    render(<MonitoredServices />);

    await screen.findByText(/no monitored services registered/i);
    await user.click(screen.getByRole("button", { name: /add monitored service/i }));
    await user.type(screen.getByLabelText(/service slug/i), "   ");
    await user.type(screen.getByLabelText(/display name/i), "   ");
    await user.type(screen.getByLabelText(/environment/i), "   ");
    await user.click(screen.getByRole("button", { name: /^create service$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/complete every service field/i);
    expect(createMonitoredService).not.toHaveBeenCalled();
  });
});
