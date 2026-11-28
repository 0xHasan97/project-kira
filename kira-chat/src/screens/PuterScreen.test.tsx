import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PuterScreen } from "./PuterScreen.tsx";
import type { PuterAi, PuterSdk } from "../puter.ts";

const MODELS = [
  {
    id: "claude-sonnet",
    puterId: "anthropic:claude-sonnet",
    provider: "anthropic",
    name: "Claude Sonnet",
    context: 200000,
    max_tokens: 64000,
    cost: { tokens: 1000000, input: 300, output: 1500 },
  },
];

function fakeSdk(options: { signedIn?: boolean; ai?: Partial<PuterAi> } = {}) {
  let signed = options.signedIn ?? true;
  const auth = {
    isSignedIn: vi.fn(() => signed),
    signIn: vi.fn(async () => {
      signed = true;
      return {};
    }),
    signOut: vi.fn(async () => {
      signed = false;
    }),
    getUser: vi.fn(async () => ({ username: "tester", email: "tester@example.test" })),
  };
  const txt2speech = Object.assign(vi.fn(), {
    listEngines: vi.fn().mockResolvedValue([]),
    listVoices: vi.fn().mockResolvedValue([]),
  });
  const ai = {
    chat: vi.fn(),
    txt2img: vi.fn(),
    txt2speech,
    speech2txt: vi.fn(),
    img2txt: vi.fn(),
    txt2vid: vi.fn(),
    speech2speech: vi.fn(),
    realtime: vi.fn(),
    listModels: vi.fn().mockResolvedValue(MODELS),
    listModelProviders: vi.fn().mockResolvedValue(["anthropic", "openai"]),
    ...options.ai,
  } as unknown as PuterAi;
  const sdk: PuterSdk = { auth, ai };
  vi.stubGlobal("puter", sdk);
  return { sdk, ai, auth };
}

async function signedIn() {
  const connect = screen.queryByRole("button", { name: "Connect Puter" });
  if (connect) fireEvent.click(connect);
  expect(await screen.findByText("tester")).toBeTruthy();
}

function mockSpeech(ai: PuterAi) {
  const spy = ai.txt2speech as unknown as ReturnType<typeof vi.fn>;
  spy.mockResolvedValue({ src: "https://cdn.test/voice.mp3", toString: () => "" });
  return spy;
}

describe("Puter screen", () => {
  it("starts signed out and connects through Puter's own popup", async () => {
    const { auth } = fakeSdk({ signedIn: false });
    render(<PuterScreen />);

    const connect = await screen.findByRole("button", { name: "Connect Puter" });
    expect(screen.getByText(/never asks for an API key/)).toBeTruthy();
    fireEvent.click(connect);

    // The SDK load is async, so the sign-in popup needs a second, still-activated click.
    const next = await screen.findByRole("button", { name: "Continue to Puter" });
    expect(auth.signIn).not.toHaveBeenCalled();
    fireEvent.click(next);

    await signedIn();
    expect(auth.signIn).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("tab", { name: "chat" })).toBeTruthy();
  });

  it("streams a chat reply from the SDK and passes the chosen model", async () => {
    async function* reply() {
      yield { type: "text", text: "Hello" };
      yield { type: "text", text: " there" };
    }
    const { ai } = fakeSdk({ ai: { chat: vi.fn().mockResolvedValue(reply()) } });
    render(<PuterScreen />);
    await signedIn();

    fireEvent.change(screen.getByRole("textbox", { name: "message" }), {
      target: { value: "hi" },
    });
    fireEvent.change(screen.getByLabelText("chat model"), {
      target: { value: "anthropic:claude-sonnet" },
    });
    fireEvent.click(screen.getByRole("button", { name: "send" }));

    expect(await screen.findByText("Hello there")).toBeTruthy();
    expect(ai.chat).toHaveBeenCalledWith(
      [{ role: "user", content: "hi" }],
      expect.objectContaining({ stream: true, model: "anthropic:claude-sonnet" }),
    );
  });

  it("draws an image and exposes it as the named result", async () => {
    const { ai } = fakeSdk({
      ai: {
        txt2img: vi.fn().mockResolvedValue({
          src: "https://cdn.test/cat.png",
          toString: () => "https://cdn.test/cat.png",
        }),
      },
    });
    render(<PuterScreen />);
    await signedIn();

    fireEvent.click(screen.getByRole("tab", { name: "images" }));
    fireEvent.change(screen.getByRole("textbox", { name: "image prompt" }), {
      target: { value: "a cat on a windowsill" },
    });
    fireEvent.click(screen.getByRole("button", { name: "generate" }));

    const image = await screen.findByRole("img", { name: "a cat on a windowsill" });
    expect(image.getAttribute("src")).toBe("https://cdn.test/cat.png");
    expect(ai.txt2img).toHaveBeenCalledWith(
      "a cat on a windowsill",
      expect.objectContaining({ aspect_ratio: "1:1", test_mode: false }),
    );
  });

  it("speaks text and reports a generated audio result", async () => {
    const { ai } = fakeSdk();
    const speak = mockSpeech(ai);
    render(<PuterScreen />);
    await signedIn();

    fireEvent.click(screen.getByRole("tab", { name: "speech" }));
    fireEvent.change(screen.getByRole("textbox", { name: "words to speak" }), {
      target: { value: "hello" },
    });
    fireEvent.change(screen.getByLabelText("AWS engine"), { target: { value: "neural" } });
    fireEvent.click(screen.getByLabelText("SSML markup"));
    fireEvent.click(screen.getByRole("button", { name: "speak" }));

    const audio = await screen.findByLabelText("Puter speech result");
    expect(audio.getAttribute("src")).toBe("https://cdn.test/voice.mp3");
    expect(speak).toHaveBeenCalledWith(
      "hello",
      expect.objectContaining({
        provider: "aws-polly",
        engine: "neural",
        language: "en-US",
        ssml: true,
      }),
    );
  });

  it("transcribes an uploaded audio file", async () => {
    const { ai } = fakeSdk({
      ai: {
        speech2txt: vi.fn().mockResolvedValue({ text: "hello from audio", model: "whisper-1" }),
      },
    });
    render(<PuterScreen />);
    await signedIn();

    fireEvent.click(screen.getByRole("tab", { name: "speech" }));
    fireEvent.click(screen.getByRole("tab", { name: "transcribe" }));
    const file = new File(["audio"], "note.wav", { type: "audio/wav" });
    fireEvent.change(screen.getByLabelText("audio file"), { target: { files: [file] } });
    fireEvent.change(screen.getByLabelText("response format"), { target: { value: "verbose_json" } });
    fireEvent.click(screen.getByRole("button", { name: "transcribe" }));

    expect(await screen.findByText("hello from audio")).toBeTruthy();
    expect(ai.speech2txt).toHaveBeenCalledWith(
      file,
      expect.objectContaining({ provider: "openai", response_format: "verbose_json" }),
    );
  });

  it("revoices an audio file with the selected model", async () => {
    const { ai } = fakeSdk({
      ai: {
        speech2speech: vi.fn().mockResolvedValue({
          src: "https://cdn.test/revoiced.mp3",
          toString: () => "",
        }),
      },
    });
    render(<PuterScreen />);
    await signedIn();

    fireEvent.click(screen.getByRole("tab", { name: "speech" }));
    fireEvent.click(screen.getByRole("tab", { name: "revoice" }));
    const file = new File(["audio"], "voice.wav", { type: "audio/wav" });
    fireEvent.change(screen.getByLabelText("audio to revoice"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "revoice" }));

    const audio = await screen.findByLabelText("Puter revoice result");
    expect(audio.getAttribute("src")).toBe("https://cdn.test/revoiced.mp3");
    expect(ai.speech2speech).toHaveBeenCalledWith(
      file,
      expect.objectContaining({
        voice: "21m00Tcm4TlvDq8ikWAM",
        model: "eleven_multilingual_sts_v2",
        remove_background_noise: false,
      }),
    );
  });

  it("reads a document with OCR", async () => {
    const { ai } = fakeSdk({
      ai: { img2txt: vi.fn().mockResolvedValue("invoice total: 42.00") },
    });
    render(<PuterScreen />);
    await signedIn();

    fireEvent.click(screen.getByRole("tab", { name: "vision" }));
    const file = new File(["%PDF"], "invoice.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText("image or document"), { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "read text" }));

    expect(await screen.findByText("invoice total: 42.00")).toBeTruthy();
    expect(ai.img2txt).toHaveBeenCalledWith(file, expect.objectContaining({ provider: "aws-textract" }));
  });

  it("renders a generated video", async () => {
    fakeSdk({
      ai: {
        txt2vid: vi.fn().mockResolvedValue({
          src: "https://cdn.test/boat.mp4",
          toString: () => "",
        }),
      },
    });
    render(<PuterScreen />);
    await signedIn();

    fireEvent.click(screen.getByRole("tab", { name: "video" }));
    fireEvent.change(screen.getByRole("textbox", { name: "video prompt" }), {
      target: { value: "a paper boat" },
    });
    fireEvent.click(screen.getByRole("button", { name: "generate video" }));

    const video = await screen.findByLabelText("a paper boat");
    expect(video.getAttribute("src")).toBe("https://cdn.test/boat.mp4");
  });

  it("lists the live catalogue with provider and context facts", async () => {
    fakeSdk();
    render(<PuterScreen />);
    await signedIn();

    fireEvent.click(screen.getByRole("tab", { name: "models" }));
    expect(await screen.findByText("Claude Sonnet")).toBeTruthy();
    expect(screen.getByText("anthropic:claude-sonnet")).toBeTruthy();
    expect(screen.getByText("200,000")).toBeTruthy();
  });

  it("runs a realtime text turn and streams its delta", async () => {
    const handlers = new Map<string, (event: Record<string, unknown>) => void>();
    const conversation = {
      state: "prepared",
      connect: vi.fn(async () => {}),
      close: vi.fn(),
      sendText: vi.fn(),
      on: vi.fn((type: string, handler: (event: Record<string, unknown>) => void) => {
        handlers.set(type, handler);
        return () => {};
      }),
    };
    fakeSdk({ ai: { realtime: vi.fn().mockResolvedValue(conversation) } });
    render(<PuterScreen />);
    await signedIn();

    fireEvent.click(screen.getByRole("tab", { name: "realtime" }));
    fireEvent.click(screen.getByRole("button", { name: "start text session" }));
    await screen.findByRole("button", { name: "end session" });

    act(() => handlers.get("text")?.({ type: "text", delta: "Hi" }));
    act(() => handlers.get("turn.done")?.({}));
    expect(await screen.findByText("Hi")).toBeTruthy();
    await waitFor(() => expect(conversation.connect).toHaveBeenCalledTimes(1));
  });
});
