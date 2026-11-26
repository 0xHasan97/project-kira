import { describe, expect, it } from "vitest";
import { answersToday, keyBadge } from "./keying.ts";

describe("keying", () => {
  it("counts a provider that asks for no credential as able to answer", () => {
    // A local server on loopback has no key to store. Reported as "no key", it looks broken in the
    // picker, the sidebar, the options panel and the Providers table at once.
    expect(answersToday({ key_present: false, needs_key: false })).toBe(true);
    expect(keyBadge({ key_present: false, needs_key: false })).toEqual({ text: "no key needed", ok: true });
  });

  it("still calls a missing key a missing key", () => {
    expect(answersToday({ key_present: false, needs_key: true })).toBe(false);
    expect(keyBadge({ key_present: false, needs_key: true })).toEqual({ text: "no key", ok: false });
  });

  it("reports a stored key as stored", () => {
    expect(answersToday({ key_present: true, needs_key: true })).toBe(true);
    expect(keyBadge({ key_present: true, needs_key: true })).toEqual({ text: "key ok", ok: true });
  });
});
