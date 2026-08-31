import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import UptimeMonitors from "./UptimeMonitors";
import { listMonitoredServices } from "../services/monitoredServices";
import {
  createUptimeMonitor,
  deactivateUptimeMonitor,
  listUptimeMonitors,
} from "../services/uptimeMonitors";

vi.mock("../services/monitoredServices", () => ({ listMonitoredServices: vi.fn() }));
vi.mock("../services/uptimeMonitors", () => ({
  createUptimeMonitor: vi.fn(),
  deactivateUptimeMonitor: vi.fn(),
  listUptimeMonitors: vi.fn(),
}));

const service = {
  id: "f00dcafe-0922-4c06-98e5-b8f5e9d62fd0",
  slug: "public-site",
  display_name: "Public site",
  active: true,
};
const monitor = {
  id: "6a19844f-c960-4f05-9df7-93b5b9269a19",
  service_id: service.id,
  service_slug: service.slug,
  service_display_name: service.display_name,
  url: "https://example.com/",
  active: true,
  last_checked_at: "2026-08-31T20:00:00Z",
  last_is_up: true,
  last_status_code: 204,
  last_response_time_ms: 37,
  uptime_24h_percent: 99.95,
  created_at: "2026-08-31T19:00:00Z",
  updated_at: "2026-08-31T20:00:00Z",
};

describe("Uptime monitors", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listMonitoredServices.mockResolvedValue([service]);
    listUptimeMonitors.mockResolvedValue([]);
  });

  it("creates a monitor using exactly a URL and existing service", async () => {
    createUptimeMonitor.mockResolvedValue(monitor);
    const user = userEvent.setup();
    render(<UptimeMonitors />);

    await screen.findByText(/no website monitors yet/i);
    await user.click(screen.getByRole("button", { name: /add website monitor/i }));
    const dialog = screen.getByRole("dialog", { name: /add website monitor/i });
    expect(within(dialog).getAllByRole("textbox")).toHaveLength(1);
    expect(within(dialog).getAllByRole("combobox")).toHaveLength(1);

    await user.type(within(dialog).getByLabelText("Website URL"), "  https://example.com  ");
    await user.selectOptions(within(dialog).getByLabelText("Existing service"), service.id);
    await user.click(within(dialog).getByRole("button", { name: /^create monitor$/i }));

    expect(createUptimeMonitor).toHaveBeenCalledWith({
      url: "https://example.com",
      service_id: service.id,
    });
    expect(await screen.findByRole("link", { name: "https://example.com/" })).toBeVisible();
  });

  it("shows current status, rolling uptime, latency, and last check", async () => {
    listUptimeMonitors.mockResolvedValue([monitor]);
    render(<UptimeMonitors />);

    const table = await screen.findByRole("table");
    expect(within(table).getByText("Up")).toBeVisible();
    expect(screen.getByText("99.95%")).toBeVisible();
    expect(screen.getByText("37 ms")).toBeVisible();
    expect(screen.getByText("HTTP 204")).toBeVisible();
    expect(screen.getByText("Public site")).toBeVisible();
  });

  it("requires confirmation before stopping a monitor", async () => {
    listUptimeMonitors.mockResolvedValue([monitor]);
    deactivateUptimeMonitor.mockResolvedValue();
    const user = userEvent.setup();
    render(<UptimeMonitors />);

    await screen.findByRole("link", { name: "https://example.com/" });
    await user.click(screen.getByRole("button", { name: /stop monitoring https:\/\/example.com/i }));
    expect(screen.getByText(/history remains available/i)).toBeVisible();
    await user.click(screen.getByRole("button", { name: /^stop monitor$/i }));

    expect(deactivateUptimeMonitor).toHaveBeenCalledWith(monitor.id);
    expect(await screen.findByText(/no website monitors yet/i)).toBeVisible();
  });

  it("warns when background refresh fails instead of silently showing stale data", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    listUptimeMonitors
      .mockResolvedValueOnce([monitor])
      .mockRejectedValueOnce(new Error("refresh failed"));
    try {
      render(<UptimeMonitors />);
      await screen.findByRole("link", { name: "https://example.com/" });
      await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
      expect(await screen.findByRole("alert")).toHaveTextContent(/may be out of date/i);
      expect(screen.getByRole("button", { name: /retry/i })).toBeVisible();
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows a retryable error instead of an empty state", async () => {
    listUptimeMonitors.mockRejectedValue({ response: { data: { detail: "Uptime unavailable" } } });
    render(<UptimeMonitors />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Uptime unavailable");
    expect(screen.getByRole("button", { name: /retry/i })).toBeVisible();
    expect(screen.queryByText(/no website monitors yet/i)).not.toBeInTheDocument();
  });
});
