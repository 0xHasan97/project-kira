import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  APPEARANCES,
  DEFAULT_APPEARANCE,
  currentAppearance,
  onAppearance,
  resolveAppearance,
  setAppearance,
  systemPrefersDark,
} from "./appearance.ts";

function media(matches: boolean) {
  return {
    matches,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  } as unknown as MediaQueryList;
}

beforeEach(() => {
  localStorage.clear();
  vi.unstubAllGlobals();
});

describe("appearance", () => {
  it("starts on system, and ignores a stored value it does not know", () => {
    expect(APPEARANCES).toEqual(["system", "light", "dark"]);
    expect(currentAppearance()).toBe(DEFAULT_APPEARANCE);
    localStorage.setItem("kira.appearance", "sepia");
    expect(currentAppearance()).toBe("system");
  });

  it("resolves the desktop's choice, and lets an explicit choice win", () => {
    expect(resolveAppearance("system", true)).toBe("dark");
    expect(resolveAppearance("system", false)).toBe("light");
    expect(resolveAppearance("light", true)).toBe("light");
    expect(resolveAppearance("dark", false)).toBe("dark");
  });

  it("falls back to light when the browser has no matchMedia", () => {
    expect(systemPrefersDark()).toBe(false);
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => media(true)),
    );
    expect(systemPrefersDark()).toBe(true);
  });

  it("writes kira.appearance and notifies on every choice, even the active one", () => {
    const seen: string[] = [];
    const stop = onAppearance((value) => seen.push(value));
    setAppearance("dark");
    setAppearance("dark");
    expect(localStorage.getItem("kira.appearance")).toBe("dark");
    expect(seen).toEqual(["dark", "dark"]);
    expect(currentAppearance()).toBe("dark");
    stop();
    setAppearance("light");
    expect(seen).toEqual(["dark", "dark"]);
  });

  it("follows another tab's write, and treats a cleared key as system", () => {
    const seen: string[] = [];
    const stop = onAppearance((value) => seen.push(value));
    window.dispatchEvent(
      new StorageEvent("storage", {
        key: "kira.appearance",
        newValue: "light",
      }),
    );
    window.dispatchEvent(
      new StorageEvent("storage", { key: "kira.appearance", newValue: null }),
    );
    window.dispatchEvent(
      new StorageEvent("storage", { key: "kira.theme", newValue: "violet" }),
    );
    expect(seen).toEqual(["light", "system"]);
    stop();
  });
});
