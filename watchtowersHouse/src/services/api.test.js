import { describe, expect, it } from "vitest";
import { getErrorMessage } from "./api";

describe("getErrorMessage", () => {
  it("returns string API details", () => {
    expect(getErrorMessage({ response: { data: { detail: "Request failed" } } }, "Fallback"))
      .toBe("Request failed");
  });

  it("normalizes FastAPI validation detail arrays", () => {
    const error = {
      response: {
        data: {
          detail: [
            { loc: ["body", "name"], msg: "Field required", type: "missing" },
            { loc: ["body", "expires_at"], msg: "Must be in the future", type: "value_error" },
          ],
        },
      },
    };

    expect(getErrorMessage(error, "Fallback"))
      .toBe("name: Field required; expires_at: Must be in the future");
  });

  it("uses a safe fallback for unknown structured details", () => {
    expect(getErrorMessage({ response: { data: { detail: { internal: true } } } }, "Fallback"))
      .toBe("Fallback");
  });
});
