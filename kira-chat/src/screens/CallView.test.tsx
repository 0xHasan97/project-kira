import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { expect, it, vi } from "vitest";
import { CallView } from "./CallView.tsx";
import type { CallState } from "../voice/useCall.ts";
import type { VoiceStatus } from "../contracts.ts";

const OFF_STACK: VoiceStatus = {
  stt: { mode: "off", available: false, detail: "listening is off for this call" },
  tts: { mode: "off", available: false, detail: "speaking is off for this call" },
  vision: null,
  limits: { max_utterance_s: 30, silence_ms: 700 },
};

const LOCAL_STACK: VoiceStatus = {
  stt: { mode: "local", available: true, detail: "faster-whisper · base" },
  tts: { mode: "local", available: false, detail: "piper is not installed" },
  vision: { provider: "openrouter", model: "claude-sonnet-4-5" },
  limits: { max_utterance_s: 30, silence_ms: 700 },
};

function state(overrides: Partial<CallState> = {}): CallState {
  return {
    phase: "idle",
    voice: null,
    entries: [],
    live: "",
    error: null,
    muted: false,
    camera: false,
    level: 0,
    sessionId: null,
    chain: [],
    videoRef: { current: null },
    playbackLevel: { current: 0 },
    start: vi.fn(),
    end: vi.fn(),
    toggleMute: vi.fn(),
    toggleCamera: vi.fn(),
    look: vi.fn(),
    say: vi.fn(),
    ...overrides,
  };
}

function renderView(call = state(), status: VoiceStatus | null = null, stage?: ReactNode) {
  render(<CallView call={call} status={status} stage={stage} />);
  return call;
}

const startButton = () => screen.getByRole("button", { name: "start call" }) as HTMLButtonElement;

it("is honest about an off stack and disables start", () => {
  renderView(state(), OFF_STACK);
  expect(screen.getByText("listen")).toBeTruthy();
  expect(screen.getByText("listening is off for this call")).toBeTruthy();
  expect(screen.getByText("frames stay on this device")).toBeTruthy();
  expect(startButton().disabled).toBe(true);
});

it("starts, shows the transcript and sends typed turns", () => {
  const call = renderView(state({ phase: "listening", entries: [{ id: 1, role: "user", text: "hello" }], live: "Hi." }));
  fireEvent.click(startButton());
  expect(call.start).toHaveBeenCalled();
  expect(screen.getByText("hello")).toBeTruthy();
  expect(screen.getByText("Hi.")).toBeTruthy();
  fireEvent.change(screen.getByLabelText("typed message"), { target: { value: "a question" } });
  fireEvent.submit(screen.getByLabelText("typed message").closest("form")!);
  expect(call.say).toHaveBeenCalledWith("a question");
});

it("ends the call", () => {
  const call = renderView(state({ phase: "speaking" }));
  fireEvent.click(screen.getByRole("button", { name: "end call" }));
  expect(call.end).toHaveBeenCalled();
});

it("names the provider the camera goes to, and only lets look run with a camera", () => {
  const call = renderView(state({ phase: "listening" }), LOCAL_STACK);
  expect(screen.getByText("frames → openrouter · claude-sonnet-4-5")).toBeTruthy();
  expect((screen.getByRole("button", { name: "look" }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "camera on" }));
  expect(call.toggleCamera).toHaveBeenCalled();
});

it("shows why a call stopped working, and still offers a restart", () => {
  const call = renderView(state({ phase: "error", error: "the voice connection dropped; start the call again" }));
  expect(screen.getByText("the voice connection dropped; start the call again")).toBeTruthy();
  expect(screen.getByText("needs attention")).toBeTruthy();
  expect((screen.getByRole("button", { name: "end call" }) as HTMLButtonElement).disabled).toBe(true);
  expect(startButton().disabled).toBe(false);
  fireEvent.click(startButton());
  expect(call.start).toHaveBeenCalled();
});

it("says which provider answered", () => {
  renderView(
    state({
      phase: "listening",
      chain: [
        { event: "served", provider: "fast_one", model: "fast-mock" },
        { event: "attempt", provider: "big", model: "big-mock" },
      ],
    }),
  );
  expect(screen.getByText("fast_one · fast-mock")).toBeTruthy();
  expect(screen.queryByText("big · big-mock")).toBeNull();
});

it("holds a face in the stage column when the caller brings one", () => {
  renderView(state({ phase: "listening" }), null, <span data-testid="face">ellen on stage</span>);
  const face = screen.getByTestId("face");
  expect(face.textContent).toBe("ellen on stage");
  expect(face.closest(".call-stage")).toBeTruthy();
  expect(screen.queryByText(/no face on this call/)).toBeNull();
});

it("explains an empty library instead of a broken call", () => {
  renderView(state({ phase: "listening" }));
  expect(screen.getByText(/no face on this call/)).toBeTruthy();
  // The rest of the call is untouched by the missing body: the voice answers either way.
  expect((screen.getByRole("button", { name: "end call" }) as HTMLButtonElement).disabled).toBe(false);
});
