import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  currentRoute,
  initialRoute,
  navigate,
  onRoute,
  RAIL_ROUTES,
  ROUTES,
  takeLaunchToken,
  type Route,
} from "./hash-route.ts";

beforeEach(() => {
  // `initialRoute()` reads the query, and jsdom keeps window.location between tests.
  window.history.replaceState(null, "", "/chat/");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("hash-route", () => {
  it("treats an empty or unknown hash as chat", () => {
    window.location.hash = "";
    expect(currentRoute()).toBe("chat");
    window.location.hash = "#/nonsense";
    expect(currentRoute()).toBe("chat");
  });

  it("reads every documented route", () => {
    for (const route of ROUTES) {
      window.location.hash = `#/${route}`;
      expect(currentRoute()).toBe(route);
    }
  });

  it("serves the tool harness under its own route", () => {
    expect(ROUTES).toContain("tools");
  });

  it("serves the real-time call under its own route, next to chat", () => {
    // A call is the same conversation with a microphone: it sits beside Chat, not behind Overview.
    expect(ROUTES).toContain("call");
    expect(ROUTES.indexOf("call")).toBe(ROUTES.indexOf("chat") + 1);
  });

  it("serves pairing under its own route but keeps it off the rail", () => {
    // A phone arrives at #/pair from a link; the desktop that minted the code has no use for it.
    expect(ROUTES).toContain("pair");
    expect(RAIL_ROUTES).toContain("remote");
    expect(RAIL_ROUTES).not.toContain("pair");
  });

  it("serves the companion card off the query string the window was booted with", () => {
    // `kira-engine desktop --companion` opens `/chat/?companion=1` with no hash, and the app window
    // must not pick this route up just because somebody typed the query into a tab's address bar once.
    window.history.replaceState(null, "", "/chat/?companion=1");
    expect(window.location.hash).toBe("");
    expect(initialRoute()).toBe("companion");

    window.history.replaceState(null, "", "/chat/");
    expect(initialRoute()).toBe("chat");
    window.history.replaceState(null, "", "/chat/?companion=1");
    window.location.hash = "#/avatar";
    // A hash is a deliberate navigation and outranks the query: the card can be sent to a real route.
    expect(initialRoute()).toBe("avatar");
    window.location.hash = "";
  });

  it("consumes a launcher token from the fragment and leaves no token in history", () => {
    window.history.replaceState(null, "", "/chat/#/overview?token=a%20b%26c");
    expect(takeLaunchToken()).toBe("a b&c");
    expect(window.location.hash).toBe("#/overview");
    expect(window.location.href).not.toContain("token=");
    expect(takeLaunchToken()).toBe("");
  });

  it("keeps the card off the rail and out of the app's navigation", () => {
    expect(ROUTES).toContain("companion");
    expect(RAIL_ROUTES).not.toContain("companion");
    expect(RAIL_ROUTES).not.toContain("pair");
  });

  it("notifies subscribers on hashchange and stops after unsubscribe", () => {
    const seen: Route[] = [];
    const off = onRoute((route) => seen.push(route));
    window.location.hash = "#/providers";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    expect(seen).toEqual(["providers"]);
    off();
    window.location.hash = "#/models";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    expect(seen).toEqual(["providers"]);
  });

  it("navigate() fires the subscriber even when the hash already matches", () => {
    window.location.hash = "#/sessions";
    const seen: Route[] = [];
    onRoute((route) => seen.push(route));
    navigate("sessions");
    expect(seen).toEqual(["sessions"]);
  });
});
