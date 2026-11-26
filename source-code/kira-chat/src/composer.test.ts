import { describe, expect, it } from "vitest";
import { autosize, elapsed, wantsSend } from "./composer.ts";

describe("wantsSend", () => {
  it("sends on Enter, and leaves Shift+Enter for a new line", () => {
    expect(wantsSend({ key: "Enter" })).toBe(true);
    expect(wantsSend({ key: "Enter", shiftKey: true })).toBe(false);
  });

  it("keeps the old Ctrl/Cmd+Enter send", () => {
    expect(wantsSend({ key: "Enter", ctrlKey: true, shiftKey: true })).toBe(true);
    expect(wantsSend({ key: "Enter", metaKey: true })).toBe(true);
  });

  it("never sends while an IME is composing - Enter there is a candidate pick", () => {
    expect(wantsSend({ key: "Enter", isComposing: true })).toBe(false);
  });

  it("leaves every other key alone", () => {
    expect(wantsSend({ key: "a" })).toBe(false);
    expect(wantsSend({ key: "Escape" })).toBe(false);
  });
});

function box(scrollHeight: number) {
  return { scrollHeight, style: { height: "", overflowY: "" } };
}

describe("autosize", () => {
  it("grows to the content, and stops at the cap", () => {
    const small = box(60);
    autosize(small, 180);
    expect(small.style.height).toBe("60px");
    expect(small.style.overflowY).toBe("hidden");

    const huge = box(400);
    autosize(huge, 180);
    expect(huge.style.height).toBe("180px");
    expect(huge.style.overflowY).toBe("auto");
  });
});

describe("elapsed", () => {
  it("counts seconds, then minutes, then hours without jitter", () => {
    expect(elapsed(0, 4_000)).toBe("4s");
    expect(elapsed(0, 65_000)).toBe("1m 05s");
    expect(elapsed(0, 3_845_000)).toBe("1h 04m");
  });
});
