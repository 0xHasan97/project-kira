import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { currentShell, navigateShell, onShell, SHELLS, type Shell } from "./shell.ts";

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
});

describe("shell", () => {
  it("defaults to chat when nothing is stored", () => {
    expect(currentShell()).toBe("chat");
  });

  it("falls back to chat on an unknown value", () => {
    localStorage.setItem("kira.shell", "terminal");
    expect(currentShell()).toBe("chat");
  });

  it("reads both documented shells", () => {
    for (const shell of SHELLS) {
      localStorage.setItem("kira.shell", shell);
      expect(currentShell()).toBe(shell);
    }
  });

  it("notifies subscribers on navigate and stops after unsubscribe", () => {
    const seen: Shell[] = [];
    const off = onShell((shell) => seen.push(shell));
    navigateShell("agent");
    expect(seen).toEqual(["agent"]);
    off();
    navigateShell("chat");
    expect(seen).toEqual(["agent"]);
  });

  it("navigateShell fires even when the shell already matches", () => {
    navigateShell("chat");
    const seen: Shell[] = [];
    onShell((shell) => seen.push(shell));
    navigateShell("chat");
    expect(seen).toEqual(["chat"]);
  });

  it("follows a write from another tab", () => {
    const seen: Shell[] = [];
    onShell((shell) => seen.push(shell));
    localStorage.setItem("kira.shell", "agent");
    window.dispatchEvent(new StorageEvent("storage", { key: "kira.shell", newValue: "agent" }));
    expect(seen).toEqual(["agent"]);
  });

  it("ignores a storage event for some other key", () => {
    const seen: Shell[] = [];
    onShell((shell) => seen.push(shell));
    window.dispatchEvent(new StorageEvent("storage", { key: "kira.theme", newValue: "violet" }));
    expect(seen).toEqual([]);
  });
});
