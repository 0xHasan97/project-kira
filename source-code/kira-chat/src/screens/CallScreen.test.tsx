import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { KiraClient } from "../api.ts";
import { ELLEN_ID, fakeEngine } from "../fake-engine.ts";
import { CallScreen } from "./CallScreen.tsx";

type Engine = ReturnType<typeof fakeEngine>;

function clientFor(fetchImpl: unknown): KiraClient {
  vi.stubGlobal("fetch", fetchImpl);
  return new KiraClient({ baseUrl: "http://127.0.0.1:8901", token: "sekret" });
}

function renderScreen(engine: Engine) {
  render(<CallScreen client={clientFor(engine.fetch)} token="sekret" model="" mode="AUTO" />);
  return engine;
}

beforeEach(() => {
  localStorage.clear();
});

describe("the call's face", () => {
  it("puts the body that is on stage in the call's own column", async () => {
    const engine = renderScreen(fakeEngine());

    // The library's active pick is read on mount, before anyone presses start: the face belongs to the
    // call's frame, not to the moment an answer begins.
    const canvas = await screen.findByLabelText("ellen on stage");
    expect(canvas.closest(".call-stage")).toBeTruthy();
    expect(screen.queryByText(/no face on this call/)).toBeNull();
    // And it is the picked body being asked for, not the first row the library happens to hold. The
    // canvas is on the pane before the mesh route is reached, so this waits on the call, not the paint.
    await waitFor(() =>
      expect(engine.calls.filter((call) => call.url.endsWith("/mesh")).map((call) => call.url)).toEqual([
        `/v1/kira/characters/${ELLEN_ID}/mesh`,
      ]),
    );
  });

  it("says a call has no face when the library has no pick, and keeps the call", async () => {
    renderScreen(fakeEngine({ characters: { characters: [], active: null } }));

    expect(await screen.findByText(/no face on this call/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "start call" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("treats a library that will not answer as an empty one", async () => {
    render(
      <CallScreen
        client={clientFor(() => Promise.reject(new TypeError("failed to fetch")))}
        token="sekret"
        model=""
        mode="AUTO"
      />,
    );

    // Nothing in the avatar route is worth failing a call over — the voice carries the turn either way,
    // and a screen that turned a read error into an alert would be blaming the user for their own library.
    expect(await screen.findByText(/no face on this call/)).toBeTruthy();
    expect(screen.getByText("not connected")).toBeTruthy();
  });
});
