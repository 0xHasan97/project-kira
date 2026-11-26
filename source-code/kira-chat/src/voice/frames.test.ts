import { expect, it } from "vitest";
import { FRAME_INTERVAL_MS, frameDue } from "./frames.ts";

it("is due four seconds after the last frame", () => {
  expect(frameDue(1000, 4999)).toBe(false);
  expect(frameDue(1000, 5000)).toBe(true);
});

it("pauses while the tab is hidden", () => {
  // A backgrounded tab is not a call: the picture would describe a room nobody is looking at.
  expect(frameDue(1000, 9000, true)).toBe(false);
});

it("takes the cadence from the contract, not from a caller's guess", () => {
  expect(FRAME_INTERVAL_MS).toBe(4000);
  expect(frameDue(0, FRAME_INTERVAL_MS)).toBe(true);
});
