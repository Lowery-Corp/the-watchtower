import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ApiKeys from "./ApiKeys";
import { createApiKey, listApiKeys, revokeApiKey, updateApiKey } from "../services/apiKeys";
import { listMonitoredServices } from "../services/monitoredServices";

vi.mock("../services/apiKeys", () => ({
  createApiKey: vi.fn(),
  listApiKeys: vi.fn(),
  updateApiKey: vi.fn(),
  revokeApiKey: vi.fn(),
}));
vi.mock("../services/monitoredServices", () => ({
  listMonitoredServices: vi.fn(),
}));

const service = {
  id: "f00dcafe-0922-4c06-98e5-b8f5e9d62fd0",
  slug: "payments-api",
  display_name: "Payments API",
  environment: "production",
  active: true,
};

const createdKey = {
  id: "d7914462-ed17-44d4-ae2c-5df727e62aed",
  name: "Production ingestion",
  public_prefix: "tK42aBC91dEfGhij",
  scopes: ["events:write"],
  service_id: service.id,
  created_at: "2026-07-20T23:00:00Z",
  expires_at: null,
  last_used_at: null,
  revoked_at: null,
  api_key: "wtk_v1_tK42aBC91dEfGhij.one-time-plaintext-secret-value",
};

describe("API Keys", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listApiKeys.mockResolvedValue([]);
    listMonitoredServices.mockResolvedValue([service]);
  });

  it("creates a service-bound key and discloses its plaintext once", async () => {
    createApiKey.mockResolvedValue(createdKey);
    const user = userEvent.setup();
    render(<ApiKeys />);

    await screen.findByText(/no api keys issued/i);
    await user.click(screen.getByRole("button", { name: /create api key/i }));
    await user.type(screen.getByLabelText(/^key name$/i), "Production ingestion");
    await user.selectOptions(screen.getByLabelText(/bound service/i), service.id);
    await user.click(screen.getByRole("button", { name: /issue key/i }));

    expect(createApiKey).toHaveBeenCalledWith({
      name: "Production ingestion",
      service_id: service.id,
      expires_at: null,
    });
    expect(
      await screen.findByRole("dialog", { name: /copy your api key now/i }),
    ).toHaveTextContent(createdKey.api_key);
    expect(screen.getByText(/never be shown again/i)).toBeVisible();

    const execCommand = vi.fn(() => true);
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: undefined });
    Object.defineProperty(document, "execCommand", { configurable: true, value: execCommand });
    await user.click(screen.getByRole("button", { name: /copy secret/i }));
    expect(execCommand).toHaveBeenCalledWith("copy");
    expect(await screen.findByText(/^Copied/)).toBeVisible();

    await user.click(screen.getByRole("button", { name: /i have saved this key/i }));
    expect(screen.queryByText(createdKey.api_key)).not.toBeInTheDocument();
    expect(screen.getByText("Production ingestion")).toBeVisible();
  });

  it("revokes an active key and preserves its metadata row", async () => {
    const existingKey = { ...createdKey };
    delete existingKey.api_key;
    listApiKeys.mockResolvedValue([existingKey]);
    revokeApiKey.mockResolvedValue();
    const user = userEvent.setup();
    render(<ApiKeys />);

    await screen.findByText("Production ingestion");
    await user.click(screen.getByRole("button", { name: /revoke production ingestion/i }));
    await user.click(screen.getByRole("button", { name: /^revoke key$/i }));

    expect(revokeApiKey).toHaveBeenCalledWith(existingKey.id);
    expect(screen.getByText("Production ingestion")).toBeVisible();
    expect(await screen.findByText("Revoked")).toBeVisible();
  });

  it("renames safe key metadata without changing key restrictions", async () => {
    const existingKey = { ...createdKey };
    delete existingKey.api_key;
    const renamedKey = { ...existingKey, name: "Primary webhook" };
    listApiKeys.mockResolvedValue([existingKey]);
    updateApiKey.mockResolvedValue(renamedKey);
    const user = userEvent.setup();
    render(<ApiKeys />);

    await screen.findByText("Production ingestion");
    await user.click(screen.getByRole("button", { name: /edit production ingestion/i }));
    const nameField = screen.getByLabelText(/^key name$/i);
    await user.clear(nameField);
    await user.type(nameField, "Primary webhook");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    expect(updateApiKey).toHaveBeenCalledWith(existingKey.id, { name: "Primary webhook" });
    expect(await screen.findByText("Primary webhook")).toBeVisible();
    expect(screen.getByText("Payments API")).toBeVisible();
  });

  it("normalizes structured validation failures without rendering a false empty state", async () => {
    listApiKeys.mockRejectedValue({
      response: {
        data: {
          detail: [{ loc: ["body", "name"], msg: "Field required", type: "missing" }],
        },
      },
    });

    render(<ApiKeys />);

    expect(await screen.findByRole("alert")).toHaveTextContent("name: Field required");
    expect(screen.queryByText(/no api keys issued/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /retry/i })).toBeVisible();
  });

  it("rejects a whitespace-only key name before sending a request", async () => {
    const user = userEvent.setup();
    render(<ApiKeys />);
    await screen.findByText(/no api keys issued/i);
    await user.click(screen.getByRole("button", { name: /create api key/i }));
    await user.type(screen.getByLabelText(/^key name$/i), "   ");
    await user.click(screen.getByRole("button", { name: /issue key/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/enter a key name/i);
    expect(createApiKey).not.toHaveBeenCalled();
  });

  it("supports keyboard dismissal and restores focus to the opening control", async () => {
    const user = userEvent.setup();
    render(<ApiKeys />);
    await screen.findByText(/no api keys issued/i);
    const createButton = screen.getByRole("button", { name: /create api key/i });
    await user.click(createButton);

    expect(screen.getByLabelText(/^key name$/i)).toHaveFocus();
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(createButton).toHaveFocus();
  });

  it("cannot dismiss key creation while issuance is in flight", async () => {
    let resolveCreate;
    createApiKey.mockImplementation(() => new Promise((resolve) => { resolveCreate = resolve; }));
    const user = userEvent.setup();
    render(<ApiKeys />);
    await screen.findByText(/no api keys issued/i);
    await user.click(screen.getByRole("button", { name: /create api key/i }));
    await user.type(screen.getByLabelText(/^key name$/i), "Production ingestion");
    await user.click(screen.getByRole("button", { name: /issue key/i }));

    expect(screen.getByRole("button", { name: /cancel/i })).toBeDisabled();
    await user.keyboard("{Escape}");
    expect(screen.getByRole("dialog", { name: /create api key/i })).toBeVisible();

    resolveCreate(createdKey);
    expect(await screen.findByRole("dialog", { name: /copy your api key now/i })).toBeVisible();
  });
});
