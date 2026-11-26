import { act, fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useCall } from "./useCall.ts";
import type { CallState } from "./useCall.ts";
import type { CallAudioLike } from "./audio.ts";

class FakeSocket {
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readyState = 1;
  constructor(public url: string) {}
  send(data: string) { this.sent.push(data); }
  close() { this.readyState = 3; this.onclose?.(); }
  emit(payload: unknown) { this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent); }
  last() { return JSON.parse(this.sent[this.sent.length - 1]); }
  count(type: string) { return this.sent.filter((raw) => JSON.parse(raw).type === type).length; }
}

class FakeAudio implements CallAudioLike {
  played: string[] = [];
  micStarted = false;
  stopped = false;
  level: ((value: number) => void) | null = null;
  playback: ((value: number) => void) | null = null;
  playbackRegistered = 0;
  async startMic(_onPacket: (pcm: string) => void, onLevel: (value: number) => void) {
    this.micStarted = true;
    this.level = onLevel;
  }
  onPlaybackLevel(onLevel: ((value: number) => void) | null) {
    this.playback = onLevel;
    if (onLevel) this.playbackRegistered += 1;
  }
  async startCamera() {}
  stopCamera() {}
  frame() { return "aGVsbG8="; }
  async play(pcm: string) { this.played.push(pcm); }
  stopPlayback() {}
  setMuted() {}
  stopAll() { this.stopped = true; }
}

const READY = {
  type: "ready",
  session_id: "s1",
  voice: {
    stt: { mode: "local", available: false, detail: "faster-whisper is not installed" },
    tts: { mode: "local", available: false, detail: "piper is not installed" },
    vision: null,
    limits: { max_utterance_s: 30, silence_ms: 700 },
  },
  limits: { max_utterance_s: 30, silence_ms: 700 },
};

function Probe({ socket, audio, sink }: { socket: FakeSocket; audio: FakeAudio; sink?: { current: CallState | null } }) {
  const call = useCall(
    { baseUrl: "http://127.0.0.1:8901", token: "t", model: "", mode: "AUTO" },
    { connect: () => socket as unknown as WebSocket, audio },
  );
  if (sink) sink.current = call;
  return (
    <div>
      <span data-testid="phase">{call.phase}</span>
      <span data-testid="live">{call.live}</span>
      <span data-testid="error">{call.error ?? ""}</span>
      <span data-testid="voice">{call.voice ? `${call.voice.stt.mode}:${call.voice.stt.available}` : ""}</span>
      <span data-testid="transcript">{call.entries.map((entry) => `${entry.role}:${entry.text}`).join(" ")}</span>
      <span data-testid="playback">{call.playbackLevel.current}</span>
      <button onClick={() => void call.start()}>start</button>
      <button onClick={() => call.say("hello")}>say</button>
      <button onClick={() => call.look()}>look</button>
      <button onClick={() => call.toggleMute()}>mute</button>
      <button onClick={() => void call.end()}>end</button>
    </div>
  );
}

function openCall() {
  const socket = new FakeSocket("ws://127.0.0.1:8901/v1/voice");
  const audio = new FakeAudio();
  const sink: { current: CallState | null } = { current: null };
  render(<Probe socket={socket} audio={audio} sink={sink} />);
  fireEvent.click(screen.getByText("start"));
  expect(socket.url).toBe("ws://127.0.0.1:8901/v1/voice");
  act(() => socket.onopen?.());
  act(() => socket.emit(READY));
  return { socket, audio, sink };
}

it("greets with hello and carries typed turns both ways", () => {
  const { socket } = openCall();
  expect(JSON.parse(socket.sent[0])).toEqual({ type: "hello", token: "t", model: null, mode: "AUTO", session_id: null });
  expect(screen.getByTestId("phase").textContent).toBe("listening");
  // The `ready` block is the only place a call learns what it cannot do, so it has to survive to state.
  expect(screen.getByTestId("voice").textContent).toBe("local:false");
  fireEvent.click(screen.getByText("say"));
  expect(JSON.parse(socket.sent[1])).toEqual({ type: "text", text: "hello" });
  act(() => socket.emit({ type: "transcript", text: "hello", final: true }));
  act(() => socket.emit({ type: "answer_delta", text: "Hi " }));
  act(() => socket.emit({ type: "answer_delta", text: "there." }));
  expect(screen.getByTestId("live").textContent).toBe("Hi there.");
  expect(screen.getByTestId("phase").textContent).toBe("speaking");
  act(() => socket.emit({ type: "turn_done", session_id: "s1", usage: { prompt_tokens: 1, completion_tokens: 2 }, chain: [{ event: "served", provider: "gemini", model: "gemini-2.5-flash" }] }));
  expect(screen.getByTestId("phase").textContent).toBe("listening");
  expect(screen.getByTestId("transcript").textContent).toBe("user:hello assistant:Hi there.");
});

it("plays sentences, barges on speech and looks on request", () => {
  const { socket, audio } = openCall();
  act(() => socket.emit({ type: "audio_out", pcm: "AAAA", seq: 1, text: "Hi." }));
  expect(audio.played).toEqual(["AAAA"]);
  act(() => socket.emit({ type: "answer_delta", text: "Hi." }));
  expect(screen.getByTestId("phase").textContent).toBe("speaking");
  act(() => audio.level?.(0.5));
  expect(socket.last()).toEqual({ type: "barge" });
  expect(screen.getByTestId("phase").textContent).toBe("listening");
  act(() => socket.emit({ type: "cancelled", reason: "barge" }));
  expect(screen.getByTestId("live").textContent).toBe("");
  const before = socket.sent.length;
  fireEvent.click(screen.getByText("look"));
  expect(JSON.parse(socket.sent[before])).toEqual({ type: "frame", jpeg: "aGVsbG8=", mime: "image/jpeg" });
  expect(JSON.parse(socket.sent[before + 1])).toEqual({ type: "text", text: "what do you see?" });
  fireEvent.click(screen.getByText("end"));
  expect(audio.stopped).toBe(true);
  expect(screen.getByTestId("phase").textContent).toBe("ended");
});

it("keeps a call usable when the mic refuses", async () => {
  const socket = new FakeSocket("ws://x");
  const audio = new FakeAudio();
  audio.startMic = () => Promise.reject(new Error("Permission denied"));
  render(<Probe socket={socket} audio={audio} />);
  fireEvent.click(screen.getByText("start"));
  act(() => socket.onopen?.());
  await act(async () => { await Promise.resolve(); });
  expect(screen.getByTestId("error").textContent).toBe("Permission denied");
  act(() => socket.emit(READY));
  fireEvent.click(screen.getByText("say"));
  expect(socket.last()).toEqual({ type: "text", text: "hello" });
});

it("waits 700 ms before it lets the same voice interrupt again", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-29T12:00:00Z"));
  try {
    const { socket, audio } = openCall();
    act(() => socket.emit({ type: "answer_delta", text: "Speaking at length." }));
    act(() => audio.level?.(0.5));
    expect(socket.count("barge")).toBe(1);
    // Still speaking, still loud: one interruption is enough to cut the sentence off.
    act(() => socket.emit({ type: "answer_delta", text: " More text." }));
    act(() => audio.level?.(0.5));
    expect(socket.count("barge")).toBe(1);
    vi.advanceTimersByTime(800);
    act(() => socket.emit({ type: "answer_delta", text: " Even more." }));
    act(() => audio.level?.(0.5));
    expect(socket.count("barge")).toBe(2);
  } finally {
    vi.useRealTimers();
  }
});

it("hands the answer's loudness to the stage without rendering the call", () => {
  const { audio, sink } = openCall();
  expect(audio.playbackRegistered, "opening a call registers one mouth listener").toBe(1);
  const rendered = sink.current;
  expect(rendered).toBeTruthy();

  // 0.1 RMS is the answer being spoken; the stage wants it on the same scale the mic bar shows.
  act(() => audio.playback?.(0.1));
  expect(sink.current?.playbackLevel.current).toBeCloseTo(0.4, 6);
  // And no render happened: the sink still holds the object from the last one, because a mouth is a
  // 60 Hz consumer and a React pass per frame is how a call stutters.
  expect(sink.current).toBe(rendered);

  // The microphone, by contrast, is a bar someone reads, so it does re-render.
  act(() => audio.level?.(0.1));
  expect(sink.current).not.toBe(rendered);
  expect(screen.getByTestId("playback").textContent).toBe("0.4");
});

it("unregisters the mouth when the call ends", () => {
  const { audio, sink } = openCall();
  act(() => audio.playback?.(0.2));
  expect(sink.current?.playbackLevel.current).toBeCloseTo(0.8, 6);
  fireEvent.click(screen.getByText("end"));
  expect(audio.playback).toBeNull();
  expect(sink.current?.playbackLevel.current).toBe(0);
});
