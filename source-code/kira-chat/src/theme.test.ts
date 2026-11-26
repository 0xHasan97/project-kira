import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { currentTheme, navigateTheme, onTheme, THEMES, type Theme } from "./theme.ts";

beforeEach(() => localStorage.clear());
afterEach(() => localStorage.clear());

describe("theme", () => {
  it("defaults to MYRAA's own default, charcoal", () => {
    expect(currentTheme()).toBe("charcoal"); // MYRAA App.tsx:305
  });

  it("keeps MYRAA's order, so the picker reads like the donor's", () => {
    expect([...THEMES]).toEqual(["violet", "crimson", "emerald", "celestial", "gold", "rose", "charcoal"]);
  });

  it("falls back on an unknown theme", () => {
    localStorage.setItem("kira.theme", "neon");
    expect(currentTheme()).toBe("charcoal");
  });

  it("notifies on change, even for the active theme, and stops after unsubscribe", () => {
    const seen: Theme[] = [];
    const off = onTheme((t) => seen.push(t));
    navigateTheme("violet");
    expect(seen).toEqual(["violet"]);
    off();
    navigateTheme("gold");
    expect(seen).toEqual(["violet"]);
  });
});
