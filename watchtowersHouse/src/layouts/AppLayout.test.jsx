import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AppLayout from "./AppLayout";

const { logout } = vi.hoisted(() => ({
  logout: vi.fn(),
}));

vi.mock("../auth/AuthProvider", () => ({
  useAuth: () => ({
    user: { username: "operator", display_name: "Operator", is_admin: false },
    authError: null,
    logout,
  }),
}));

describe("AppLayout", () => {
  beforeEach(() => {
    logout.mockReset();
    logout.mockResolvedValue({ ok: true });
  });

  it("keeps the visible logout control intentionally inert", async () => {
    const user = userEvent.setup();

    render(
      <MemoryRouter initialEntries={["/home"]}>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/home" element={<p>Home content</p>} />
          </Route>
          <Route path="/login" element={<p>Login page</p>} />
        </Routes>
      </MemoryRouter>,
    );

    const button = screen.getByRole("button", { name: "Sign out" });
    expect(button).toBeVisible();

    await user.click(button);

    expect(logout).not.toHaveBeenCalled();
    expect(button).toHaveTextContent("Sign out");
    expect(button).toBeEnabled();
    expect(screen.getByText("Home content")).toBeVisible();
    expect(screen.queryByText("Login page")).not.toBeInTheDocument();
  });
});
