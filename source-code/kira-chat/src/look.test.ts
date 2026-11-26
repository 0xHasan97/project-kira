import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { currentLook, DEFAULT_LOOK, onLook, setLook } from "./look.ts";

beforeEach(() => localStorage.clear());
afterEach(() => localStorage.clear());

describe("look", () => {
  it("starts at the donor defaults", () => {
    expect(currentLook()).toEqual(DEFAULT_LOOK);
  });

  it("survives corrupt json without throwing", () => {
    localStorage.setItem("kira.look", "{oops");
    expect(currentLook()).toEqual(DEFAULT_LOOK);
  });

  it("fills missing fields from the defaults", () => {
    localStorage.setItem("kira.look", JSON.stringify({ glass: false }));
    expect(currentLook()).toEqual({ ...DEFAULT_LOOK, glass: false });
  });

  it("refuses an unknown enum value field by field", () => {
    localStorage.setItem("kira.look", JSON.stringify({ caption: "huge", scale: "xxl", density: "airy", motion: "maybe" }));
    expect(currentLook()).toEqual(DEFAULT_LOOK);
  });

  it("merges a patch, persists it, and notifies", () => {
    const seen: string[] = [];
    onLook((look) => seen.push(look.caption));
    setLook({ caption: "xl" });
    expect(currentLook().caption).toBe("xl");
    expect(seen).toEqual(["xl"]);
    expect(localStorage.getItem("kira.look")).toContain('"caption":"xl"');
  });
});
