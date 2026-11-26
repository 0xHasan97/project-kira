import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { KiraClient } from "../api.ts";
import { ConfirmProvider } from "../confirm.tsx";
import { fakeEngine } from "../fake-engine.ts";
import { RemoteScreen } from "./RemoteScreen.tsx";

const DEVICE = { id: "dev-1", name: "phone", created_at: 1_700_000_000, last_seen_at: 1_700_000_060 };

function clientFor(engine: ReturnType<typeof fakeEngine>) {
  vi.stubGlobal("fetch", engine.fetch);
  return new KiraClient({ baseUrl: "http://127.0.0.1:8901", token: "sekret" });
}

function renderScreen(engine: ReturnType<typeof fakeEngine>) {
  return render(
    <ConfirmProvider>
      <RemoteScreen client={clientFor(engine)} connected />
    </ConfirmProvider>,
  );
}

async function confirmWith(secret = "fake-confirm") {
  fireEvent.change(await screen.findByLabelText("Confirm secret"), { target: { value: secret } });
  fireEvent.click(screen.getByRole("button", { name: "confirm write" }));
}

beforeEach(() => {
  localStorage.clear();
});

describe("RemoteScreen", () => {
  it("lists the paired devices with when each was last seen", async () => {
    renderScreen(fakeEngine({ devices: [DEVICE] }));
    expect(await screen.findByText("phone")).toBeTruthy();
    expect(screen.getByText("2023-11-14 22:13")).toBeTruthy();
    expect(screen.queryByText(/no device has paired yet/)).toBeNull();
  });

  it("says nothing is paired yet instead of showing an empty table", async () => {
    renderScreen(fakeEngine({ devices: [] }));
    expect(await screen.findByText(/no device has paired yet/)).toBeTruthy();
  });

  it("mints a code behind the confirm dialog and shows the link a phone can open", async () => {
    const engine = fakeEngine({ devices: [] });
    renderScreen(engine);

    fireEvent.change(screen.getByLabelText("public address"), { target: { value: "https://kira.example.ts.net" } });
    fireEvent.click(screen.getByRole("button", { name: "make a pairing code" }));
    await confirmWith();

    expect(await screen.findByText("ABCD1234")).toBeTruthy();
    const link = screen.getByRole("link", { name: /#\/pair\?code=ABCD1234/ });
    expect(link.getAttribute("href")).toBe("https://kira.example.ts.net/chat/#/pair?code=ABCD1234");
    const mint = engine.calls.find((call) => call.url === "/v1/kira/pairing-code");
    expect(mint?.headers["X-Kira-Confirm"]).toBe("fake-confirm");
  });

  it("mints nothing when the dialog is cancelled", async () => {
    const engine = fakeEngine({ devices: [] });
    renderScreen(engine);

    fireEvent.click(screen.getByRole("button", { name: "make a pairing code" }));
    fireEvent.click(await screen.findByRole("button", { name: "cancel" }));

    expect(engine.calls.some((call) => call.url === "/v1/kira/pairing-code")).toBe(false);
  });

  it("revokes a device behind the dialog and drops it from the list", async () => {
    const engine = fakeEngine({ devices: [DEVICE] });
    renderScreen(engine);

    fireEvent.click(await screen.findByRole("button", { name: "revoke phone" }));
    await confirmWith();

    await waitFor(() => expect(screen.queryByText("phone")).toBeNull());
    expect(await screen.findByText(/no device has paired yet/)).toBeTruthy();
    expect(engine.calls.find((call) => call.method === "DELETE")?.url).toBe("/v1/kira/devices/dev-1");
  });

  it("shows the engine's refusal when a code cannot be minted", async () => {
    renderScreen(fakeEngine({ devices: [] }));

    fireEvent.click(screen.getByRole("button", { name: "make a pairing code" }));
    await confirmWith("wrong");

    expect((await screen.findByRole("alert")).textContent).toContain("unauthorized");
  });
});
