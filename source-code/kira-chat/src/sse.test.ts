import { describe, expect, it } from "vitest";
import { SseBuffer } from "./sse.ts";

const collect = (pieces: string[]): string[] => {
  const buffer = new SseBuffer();
  const out: string[] = [];
  for (const piece of pieces) out.push(...buffer.push(piece));
  return out;
};

describe("SseBuffer", () => {
  it("returns nothing until a frame is closed", () => {
    expect(collect(['data: {"type":"delta"\n'])).toEqual([]);
  });

  it("splits frames on the blank line", () => {
    expect(collect(['data: one\n\ndata: two\n\n'])).toEqual(["one", "two"]);
  });

  it("reassembles a frame split across network chunks", () => {
    expect(collect(['data: {"type":"de', 'lta","text":"hi"}', "\n\n"])).toEqual(['{"type":"delta","text":"hi"}']);
  });

  it("normalises CRLF line endings", () => {
    expect(collect(["data: one\r\n\r\ndata: two\r\n\r\n"])).toEqual(["one", "two"]);
  });

  it("joins multi-line data and ignores comments and heartbeats", () => {
    expect(collect([": keep-alive\n\n", "data: a\ndata: b\n\n", "\n"])).toEqual(["a\nb"]);
  });

  it("drops the OpenAI-style [DONE] sentinel", () => {
    expect(collect(["data: [DONE]\n\n"])).toEqual([]);
  });

  it("exposes a truncated tail so a cut stream is visible", () => {
    const buffer = new SseBuffer();
    buffer.push("data: half\n");
    expect(buffer.remainder()).toBe("data: half\n");
  });
});
