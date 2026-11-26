import { afterEach, describe, expect, it, vi } from "vitest";
import { downloadTranscript, transcriptFilename, transcriptMarkdown } from "./export.ts";

const TURNS = [
  { role: "user", content: "hi" },
  { role: "assistant", content: "hello", provider: "groq", model: "mini" },
];

describe("transcript export", () => {
  afterEach(() => vi.restoreAllMocks());

  it("keeps the speaker, the answer and who served it", () => {
    const text = transcriptMarkdown("sess-42", TURNS, new Date("2026-11-26T10:00:00Z"));
    expect(text).toContain("# Kira conversation");
    expect(text).toContain("- Session: `sess-42`");
    expect(text).toContain("- Exported: 2026-11-26T10:00:00.000Z");
    expect(text).toContain("## You\n\nhi");
    expect(text).toContain("## Kira\n\n_groq / mini_\n\nhello");
  });

  it("names the file from the session and never walks a path", () => {
    expect(transcriptFilename("sess/42?", new Date("2026-11-26T10:00:00Z"))).toBe(
      "kira-sess-42-2026-11-26.md",
    );
    expect(transcriptFilename(null, new Date("2026-11-26T10:00:00Z"))).toBe("kira-chat-2026-11-26.md");
  });

  it("says a conversation was empty instead of writing a header only", () => {
    expect(transcriptMarkdown("sess-1", [])).toContain("_No turns in this conversation._");
  });

  it("downloads through a blob URL and revokes it", async () => {
    const create = vi.fn(() => "blob:kira");
    const revoke = vi.fn();
    Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke });
    let clicked: HTMLAnchorElement | null = null;
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        clicked = this;
      });
    downloadTranscript("sess-42", TURNS);
    expect(create).toHaveBeenCalledOnce();
    expect(click).toHaveBeenCalledOnce();
    expect(clicked!.download).toMatch(/^kira-sess-42-.*\.md$/);
    expect(clicked!.href).toBe("blob:kira");
    await new Promise((resolve) => window.setTimeout(resolve, 0));
    expect(revoke).toHaveBeenCalledWith("blob:kira");
  });
});
