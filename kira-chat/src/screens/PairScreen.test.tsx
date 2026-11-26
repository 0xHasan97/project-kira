import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fakeEngine } from "../fake-engine.ts";
import { PairScreen } from "./PairScreen.tsx";

beforeEach(() => {
  localStorage.clear();
  window.location.hash = "#/pair?code=abcd-1234";
});

describe("PairScreen", () => {
  it("pairs with the code from the link and hands the token up", async () => {
    const engine = fakeEngine();
    vi.stubGlobal("fetch", engine.fetch);
    const paired = vi.fn();
    render(<PairScreen onPaired={paired} />);

    expect((screen.getByLabelText("pairing code") as HTMLInputElement).value).toBe("ABCD1234");
    fireEvent.change(screen.getByLabelText("device name"), { target: { value: "phone" } });
    fireEvent.click(screen.getByRole("button", { name: "pair" }));

    await waitFor(() => expect(paired).toHaveBeenCalledWith("kd_test_token"));
    const call = engine.calls.find((entry) => entry.url === "/v1/kira/pair");
    expect(JSON.parse(String(call?.body))).toEqual({ code: "ABCD1234", name: "phone" });
    // The code is the only secret a phone has: no confirm header rides along.
    expect(call?.headers["X-Kira-Confirm"]).toBeUndefined();
  });

  it("says the code is not valid in the engine's words and keeps the form", async () => {
    const engine = fakeEngine({
      pairError: {
        code: "pairing_refused",
        message: "that pairing code is not valid any more - make a new one on the desktop",
        status: 400,
        retryable: false,
      },
    });
    vi.stubGlobal("fetch", engine.fetch);
    const paired = vi.fn();
    render(<PairScreen onPaired={paired} />);

    fireEvent.change(screen.getByLabelText("device name"), { target: { value: "phone" } });
    fireEvent.click(screen.getByRole("button", { name: "pair" }));

    expect((await screen.findByRole("alert")).textContent).toContain("not valid any more");
    expect(paired).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "pair" })).toBeTruthy();
  });

  it("asks for a name before it spends the code", () => {
    const engine = fakeEngine();
    vi.stubGlobal("fetch", engine.fetch);
    render(<PairScreen onPaired={() => {}} />);

    fireEvent.click(screen.getByRole("button", { name: "pair" }));

    expect(screen.getByRole("alert").textContent).toContain("name");
    expect(engine.calls).toEqual([]);
  });
});
