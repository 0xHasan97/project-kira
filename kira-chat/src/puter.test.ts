import { describe, expect, it } from "vitest";
import { chatText, mediaSrc, modelCost, puterError, transcriptText } from "./puter.ts";

describe("Puter SDK helpers", () => {
  it("reads normalized and block-array chat content", () => {
    expect(chatText({ message: { content: "hello" } })).toBe("hello");
    expect(
      chatText({ message: { content: [{ type: "text", text: "a" }, { type: "text", text: "b" }] } }),
    ).toBe("ab");
    expect(chatText({ message: { content: null } })).toBe("");
  });

  it("reads string and object transcripts", () => {
    expect(transcriptText("plain")).toBe("plain");
    expect(transcriptText({ text: "object", model: "whisper" })).toBe("object");
    expect(transcriptText({})).toBe("");
  });

  it("accepts element-like media and refuses an empty result", () => {
    expect(mediaSrc({ src: "https://cdn.test/a.png", toString: () => "" })).toBe("https://cdn.test/a.png");
    expect(mediaSrc("blob:https://kira.test/a")).toBe("blob:https://kira.test/a");
    expect(() => mediaSrc({ toString: () => "[object Object]" })).toThrow("no media URL");
  });

  it("keeps an SDK rejection's message and code", () => {
    expect(puterError({ message: "no plan", code: "subscription_required" })).toBe(
      "no plan (subscription_required)",
    );
    expect(puterError(new Error("offline"))).toBe("offline");
    expect(
      puterError({
        error: "auth_window_closed",
        msg: "Authentication window was closed by the user without completing the process.",
      }),
    ).toBe(
      "Authentication window was closed by the user without completing the process. (auth_window_closed)",
    );
  });

  it("describes a catalogue price without inventing one", () => {
    expect(
      modelCost({
        id: "m",
        provider: "p",
        cost: { tokens: 1_000_000, input: 500, output: 2_500 },
      }),
    ).toBe("$5.00 in / $25.00 out per 1,000,000 tokens");
    expect(modelCost({ id: "m", provider: "p" })).toBe("—");
  });
});
