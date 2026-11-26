import { expect, it } from "vitest";
import { parseEvent, voiceUrl } from "./protocol.ts";

it("builds a ws url from the engine base", () => {
  expect(voiceUrl("http://127.0.0.1:8901")).toBe("ws://127.0.0.1:8901/v1/voice");
  expect(voiceUrl("https://kira.example")).toBe("wss://kira.example/v1/voice");
});

it("rejects unknown and malformed events", () => {
  expect(parseEvent({ type: "nope" })).toBeNull();
  expect(parseEvent({ type: "audio_out" })).toBeNull();
  expect(parseEvent("hello")).toBeNull();
});

it("accepts the documented events", () => {
  expect(parseEvent({ type: "speech_end", discarded: false })?.type).toBe("speech_end");
  expect(parseEvent({ type: "transcript", text: "hi", final: true })?.type).toBe("transcript");
  expect(parseEvent({ type: "audio_out", pcm: "AAA", seq: 1, text: "Hi." })?.type).toBe("audio_out");
});

it("parses a frame straight off the socket", () => {
  // The wire hands `MessageEvent.data` over as text; the hook must not assume it was decoded first.
  expect(parseEvent(JSON.stringify({ type: "speech_start" }))?.type).toBe("speech_start");
  expect(parseEvent("{not json")).toBeNull();
});
