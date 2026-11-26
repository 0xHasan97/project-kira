/**
 * The call wire, typed.
 *
 * The engine owns the truth (`kira-engine/src/kira/voice/call.py`); this file is what the client
 * is allowed to assume about it. Nothing here trusts a frame: an event missing a field it promises
 * is dropped rather than half-handled, because a call that reacts to a broken `turn_done` silently
 * stops taking turns.
 */
import { API_PREFIX } from "../contracts.ts";
import type { ChainRecord, VoiceStatus, WireUsage } from "../contracts.ts";

export type CallEvent =
  | { type: "ready"; session_id: string; voice: VoiceStatus; limits: { max_utterance_s: number; silence_ms: number } }
  | { type: "speech_start" }
  | { type: "speech_end"; discarded: boolean }
  | { type: "transcript"; text: string; final: boolean }
  | { type: "thinking" }
  | { type: "answer_delta"; text: string }
  | { type: "audio_out"; pcm: string; seq: number; text: string }
  | { type: "turn_done"; session_id: string; usage: WireUsage; chain: ChainRecord[] }
  | { type: "cancelled"; reason: string }
  | { type: "error"; code: string; message: string };

export type CallCommand =
  | { type: "hello"; token: string; model: string | null; mode: string | null; session_id: string | null }
  | { type: "audio"; pcm: string }
  | { type: "frame"; jpeg: string; mime: "image/jpeg" }
  | { type: "text"; text: string }
  | { type: "barge" }
  | { type: "close" };

/** Each event's own promise, from the spec's table: the keys that must be present to trust it. */
const REQUIRED: Record<CallEvent["type"], string[]> = {
  ready: ["session_id", "voice", "limits"],
  speech_start: [],
  speech_end: ["discarded"],
  transcript: ["text", "final"],
  thinking: [],
  answer_delta: ["text"],
  audio_out: ["pcm", "seq", "text"],
  turn_done: ["session_id", "usage", "chain"],
  cancelled: ["reason"],
  error: ["code", "message"],
};

export function parseEvent(raw: unknown): CallEvent | null {
  if (typeof raw === "string") {
    try {
      raw = JSON.parse(raw);
    } catch {
      return null;
    }
  }
  if (!raw || typeof raw !== "object") return null;
  const candidate = raw as Record<string, unknown>;
  const type = candidate.type;
  if (typeof type !== "string" || !(type in REQUIRED)) return null;
  for (const key of REQUIRED[type as CallEvent["type"]]) {
    if (!(key in candidate)) return null;
  }
  return candidate as CallEvent;
}

/**
 * The socket address, derived from the engine base the user already typed.
 *
 * `URL` rather than string surgery keeps a port intact, and the path comes from the published
 * `API_PREFIX` so a version bump moves the socket with every other route instead of behind it.
 */
export function voiceUrl(baseUrl: string): string {
  const url = new URL(baseUrl || window.location.origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = `${API_PREFIX}/voice`;
  url.search = "";
  return url.toString();
}

/** 16-bit mono samples to base64, exactly as `/v1/voice` expects them in an `audio` packet. */
export function encodePcm(samples: Int16Array): string {
  const bytes = new Uint8Array(samples.buffer, samples.byteOffset, samples.byteLength);
  let binary = "";
  for (let index = 0; index < bytes.length; index += 1) binary += String.fromCharCode(bytes[index]);
  return btoa(binary);
}
