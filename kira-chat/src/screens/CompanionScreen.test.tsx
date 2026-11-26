import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";
import { KiraClient } from "../api.ts";
import { ELLEN_ID, fakeEngine } from "../fake-engine.ts";
import { CompanionScreen, readBridge } from "./CompanionScreen.tsx";
import type { CompanionBridge } from "./CompanionScreen.tsx";

type Engine = ReturnType<typeof fakeEngine>;

function clientFor(engine: Engine): KiraClient {
  vi.stubGlobal("fetch", engine.fetch);
  return new KiraClient({ baseUrl: "http://127.0.0.1:8901", token: "sekret" });
}

function bridge(
  overrides: { set?: CompanionBridge["set_click_through"]; state?: CompanionBridge["get_state"] } = {},
): { set: Mock<CompanionBridge["set_click_through"]>; state: Mock<CompanionBridge["get_state"]>; api: CompanionBridge } {
  const set = vi.fn<CompanionBridge["set_click_through"]>(overrides.set ?? (async () => ({ ok: true, click_through: true })));
  const state = vi.fn<CompanionBridge["get_state"]>(overrides.state ?? (async () => ({ click_through: false, supported: true })));
  return { set, state, api: { set_click_through: set, get_state: state } };
}

beforeEach(() => {
  localStorage.clear();
  // The desktop window injects this before it navigates, so a card that is running has a token. The
  // one test that cares about the empty case passes `token=""` rather than relying on this being absent.
  localStorage.setItem("kira.token", "sekret");
  vi.restoreAllMocks();
  document.documentElement.removeAttribute("data-window");
  // The URL the window sits on once it has been booted; the one test that cares about the frame
  // before that navigation writes the empty hash itself.
  window.location.hash = "#/companion";
});

describe("CompanionScreen", () => {
  it("marks the document as the companion window, which is how the page goes transparent", async () => {
    const engine = fakeEngine();
    render(<CompanionScreen client={clientFor(engine)} connected />);

    await screen.findByText("ellen");
    expect(document.documentElement.dataset.window).toBe("companion");
  });

  it("is the card and nothing else: no rail, no model picker, no prose", async () => {
    const engine = fakeEngine();
    const view = render(<CompanionScreen client={clientFor(engine)} connected />);

    expect(await screen.findByText("ellen")).toBeTruthy();
    expect(view.container.querySelector(".rail")).toBeNull();
    expect(view.container.querySelector(".bar")).toBeNull();
    // jsdom has no WebGL, so the stage says it cannot draw - and that line is the only explanation
    // the card needs. A pet that explained itself would be a screen, not a pet.
    expect(await screen.findByText(/cannot draw 3D/)).toBeTruthy();
    expect(view.container.textContent).not.toMatch(/redistribution not permitted/);
  });

  it("asks the window to go click-through and keeps the switch in whatever the window said", async () => {
    const engine = fakeEngine();
    const { api, set } = bridge();
    render(<CompanionScreen client={clientFor(engine)} connected bridge={api} />);

    const toggle = (await screen.findByRole("checkbox", { name: "click through" })) as HTMLInputElement;
    expect(toggle.checked).toBe(false);
    fireEvent.click(toggle);

    await waitFor(() => expect(set).toHaveBeenCalledWith(true));
    await waitFor(() => expect((screen.getByRole("checkbox", { name: "click through" }) as HTMLInputElement).checked).toBe(true));
  });

  it("puts the switch back and says why when the window refuses", async () => {
    const engine = fakeEngine();
    const { api } = bridge({ set: async () => ({ ok: false, error: "no window handle" }) });
    render(<CompanionScreen client={clientFor(engine)} connected bridge={api} />);

    const toggle = (await screen.findByRole("checkbox", { name: "click through" })) as HTMLInputElement;
    fireEvent.click(toggle);

    expect((await screen.findByRole("alert")).textContent).toContain("no window handle");
    expect((screen.getByRole("checkbox", { name: "click through" }) as HTMLInputElement).checked).toBe(false);
  });

  it("starts from the state the window reports, not from a guess", async () => {
    const engine = fakeEngine();
    const { api, state } = bridge({ state: async () => ({ click_through: true, supported: true }) });
    render(<CompanionScreen client={clientFor(engine)} connected bridge={api} />);

    await waitFor(() => expect(state).toHaveBeenCalled());
    await waitFor(() => expect((screen.getByRole("checkbox", { name: "click through" }) as HTMLInputElement).checked).toBe(true));
  });

  it("says the switch belongs to the desktop window when the page is open in a browser", async () => {
    const engine = fakeEngine();
    render(<CompanionScreen client={clientFor(engine)} connected bridge={null} />);

    const toggle = (await screen.findByRole("checkbox", { name: "click through" })) as HTMLInputElement;
    expect(toggle.disabled).toBe(true);
    expect(screen.getByText(/desktop window/)).toBeTruthy();
  });

  it("hides to the tray rather than closing the engine down", async () => {
    const engine = fakeEngine();
    const close = vi.fn();
    render(<CompanionScreen client={clientFor(engine)} connected bridge={bridge().api} />);

    vi.spyOn(window, "close").mockImplementation(close);
    fireEvent.click(await screen.findByRole("button", { name: "hide" }));
    // `window.close()` is the shell's cue to hide the card to the tray; the app window and the engine
    // are this window's host, and a card that could kill them is a card that could kill Kira.
    expect(close).toHaveBeenCalled();
  });
  it("says there is no face on stage yet and names the screen that puts one there", async () => {
    const engine = fakeEngine({ characters: { characters: [], active: null } });
    render(<CompanionScreen client={clientFor(engine)} connected />);

    expect(await screen.findByText(/no character on stage/)).toBeTruthy();
    expect(screen.getByText(/Avatar screen/)).toBeTruthy();
  });

  it("has nothing to draw before a token arrives, and says which window to fill in", async () => {
    const engine = fakeEngine();
    const view = render(<CompanionScreen client={clientFor(engine)} connected={false} token="" />);

    expect(view.container.textContent).toContain("connect in the Kira window");
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("keeps its hands off the native bridge until the window has navigated to the card", async () => {
    const engine = fakeEngine();
    const { api, set, state } = bridge();
    // The desktop window is created on `/chat/?companion=1` and navigated to `#/companion` a moment
    // later. Measured on the live card: a `get_state()` made from the first document was answered to a
    // page that had already been replaced, and pywebview raised in its own thread.
    window.location.hash = "";
    const view = render(<CompanionScreen client={clientFor(engine)} connected bridge={api} />);
    await waitFor(() => expect(state).not.toHaveBeenCalled());
    expect((screen.getByRole("checkbox", { name: "click through" }) as HTMLInputElement).disabled).toBe(true);

    window.location.hash = "#/companion";
    view.rerender(<CompanionScreen client={clientFor(engine)} connected bridge={api} />);
    await waitFor(() => expect(state).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("checkbox", { name: "click through" }));
    await waitFor(() => expect(set).toHaveBeenCalledWith(true));
  });

  it("reads the stage again when the app window picks a different body", async () => {
    const engine = fakeEngine();
    const view = render(<CompanionScreen client={clientFor(engine)} connected />);
    expect(await screen.findByText("ellen")).toBeTruthy();
    const profileReads = () => engine.calls.filter((call) => call.url === `/v1/kira/characters/${ELLEN_ID}`).length;
    expect(profileReads()).toBe(1);

    view.rerender(<CompanionScreen client={clientFor(engine)} connected pull={1} />);
    await waitFor(() => expect(profileReads()).toBe(2));
    expect(await screen.findByText("ellen")).toBeTruthy();
  });

  it("re-reads the stage when the card comes back to the front", async () => {
    const engine = fakeEngine();
    render(<CompanionScreen client={clientFor(engine)} connected />);
    expect(await screen.findByText("ellen")).toBeTruthy();
    const profileReads = () => engine.calls.filter((call) => call.url === `/v1/kira/characters/${ELLEN_ID}`).length;
    expect(profileReads()).toBe(1);

    // The two windows share no re-render, so the card notices the app window's pick on focus.
    fireEvent(window, new Event("focus"));
    await waitFor(() => expect(profileReads()).toBe(2));
  });
});

describe("readBridge", () => {
  it("finds the object the desktop window publishes and nothing else", () => {
    expect(readBridge()).toBeNull();
    (window as unknown as { pywebview: unknown }).pywebview = { api: { set_click_through: vi.fn(), get_state: vi.fn() } };
    expect(readBridge()).not.toBeNull();
    delete (window as unknown as { pywebview?: unknown }).pywebview;
    expect(readBridge()).toBeNull();
  });
});
