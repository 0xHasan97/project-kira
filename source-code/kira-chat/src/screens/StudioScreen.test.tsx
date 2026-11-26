import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { KiraClient } from "../api.ts";
import { ConfirmProvider } from "../confirm.tsx";
import { API_PREFIX } from "../contracts.ts";
import { FAKE_CONFIRM, fakeEngine, studioFixture, studioRuntimeFixture } from "../fake-engine.ts";
import { StudioScreen } from "./StudioScreen.tsx";

type Engine = ReturnType<typeof fakeEngine>;

function renderScreen(engine: Engine) {
  vi.stubGlobal("fetch", engine.fetch);
  const client = new KiraClient({ baseUrl: "http://127.0.0.1:8901", token: "sekret" });
  return render(
    <ConfirmProvider>
      <StudioScreen client={client} connected />
    </ConfirmProvider>,
  );
}

const callTo = (engine: Engine, method: string, path: string) =>
  engine.calls.find((call) => call.method === method && call.url === `${API_PREFIX}${path}`);

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("StudioScreen", () => {
  it("shows every component and what each one is missing", async () => {
    const engine = fakeEngine({
      studio: {
        ...(studioFixture() as object),
        stt: { available: false, engine: null, detail: "no whisper.cpp engine", models: [] },
      },
    });
    renderScreen(engine);

    expect(await screen.findByText("Portable AI Studio found")).toBeTruthy();
    expect(screen.getAllByText(/stable-diffusion\.cpp/).length).toBeGreaterThan(0);
    expect(screen.getByText("no whisper.cpp engine")).toBeTruthy();
    expect(screen.getByRole("button", { name: "start local model" })).toBeTruthy();
  });

  it("starts the local model through the confirm dialog and reports its URL", async () => {
    const engine = fakeEngine();
    renderScreen(engine);

    fireEvent.click(await screen.findByRole("button", { name: "start local model" }));
    fireEvent.change(await screen.findByLabelText("Confirm secret"), { target: { value: FAKE_CONFIRM } });
    fireEvent.click(screen.getByRole("button", { name: "confirm write" }));

    expect(await screen.findByText(/is serving at/)).toBeTruthy();
    expect(screen.getByText("http://127.0.0.1:8123/v1")).toBeTruthy();
    const start = callTo(engine, "POST", "/kira/studio/llm/start");
    expect(start?.headers["X-Kira-Confirm"]).toBe(FAKE_CONFIRM);
    expect(JSON.parse(start!.body ?? "{}")).toEqual({ model: "qwen" });
  });

  it("downloads a model and says where it landed", async () => {
    const engine = fakeEngine();
    renderScreen(engine);

    fireEvent.change(await screen.findByLabelText("kind"), { target: { value: "llm" } });
    fireEvent.change(screen.getByLabelText("file URL"), {
      target: { value: "https://huggingface.co/Qwen/qwen.gguf" },
    });
    fireEvent.click(screen.getByRole("button", { name: "download" }));
    fireEvent.change(await screen.findByLabelText("Confirm secret"), { target: { value: FAKE_CONFIRM } });
    fireEvent.click(screen.getByRole("button", { name: "confirm write" }));

    expect(await screen.findByText(/qwen2\.5-3b-instruct-q4_k_m\.gguf/)).toBeTruthy();
    const post = callTo(engine, "POST", "/kira/studio/download");
    expect(post?.headers["X-Kira-Confirm"]).toBe(FAKE_CONFIRM);
    expect(JSON.parse(post!.body ?? "{}")).toEqual({
      kind: "llm",
      url: "https://huggingface.co/Qwen/qwen.gguf",
      filename: null,
    });
  });

  it("starts the studio server and reveals the tools it owns", async () => {
    const engine = fakeEngine();
    renderScreen(engine);

    fireEvent.click(await screen.findByRole("button", { name: "start studio server" }));
    fireEvent.change(await screen.findByLabelText("Confirm secret"), { target: { value: FAKE_CONFIRM } });
    fireEvent.click(screen.getByRole("button", { name: "confirm write" }));

    expect(await screen.findByRole("tab", { name: "transcribe" })).toBeTruthy();
    expect((await screen.findAllByText("running")).length).toBeGreaterThan(0);
    const start = callTo(engine, "POST", "/kira/studio/app/start");
    expect(start?.headers["X-Kira-Confirm"]).toBe(FAKE_CONFIRM);
  });

  it("transcribes a WAV through the forwarded whisper route", async () => {
    const engine = fakeEngine({ studioRuntime: studioRuntimeFixture(true) });
    renderScreen(engine);

    const input = await screen.findByLabelText("WAV file");
    const file = new File([new Uint8Array([82, 73, 70, 70])], "hello.wav", { type: "audio/wav" });
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "transcribe" }));

    expect(await screen.findByText("hello there")).toBeTruthy();
    const forward = engine.calls.find(
      (call) => call.method === "POST" && call.url.includes("/kira/studio/proxy?path="),
    );
    expect(forward).toBeTruthy();
    expect(decodeURIComponent(forward!.url)).toContain("/api/speech/transcribe?filename=hello.wav");
    expect(forward?.headers["content-type"]).toBe("audio/wav");
  });

  it("lists the studio folders and deletes a file only after the typed secret", async () => {
    const engine = fakeEngine({ studioRuntime: studioRuntimeFixture(true) });
    renderScreen(engine);

    fireEvent.click(await screen.findByRole("tab", { name: "models" }));
    expect(await screen.findByText("dream.safetensors")).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: "delete" })[0]);
    fireEvent.change(await screen.findByLabelText("Confirm secret"), { target: { value: FAKE_CONFIRM } });
    fireEvent.click(screen.getByRole("button", { name: "confirm write" }));

    await waitFor(() => {
      expect(
        engine.calls.some(
          (call) => call.method === "POST" && decodeURIComponent(call.url).includes("/api/delete-model"),
        ),
      ).toBe(true);
    });
    const removed = engine.calls.find(
      (call) => call.method === "POST" && decodeURIComponent(call.url).includes("/api/delete-model"),
    );
    expect(removed?.headers["X-Kira-Confirm"]).toBe(FAKE_CONFIRM);
    expect(JSON.parse(removed!.body ?? "{}")).toEqual({ filename: "dream.safetensors" });
  });

  it("asks again when the engine refuses a studio delete's secret", async () => {
    const engine = fakeEngine({ studioRuntime: studioRuntimeFixture(true) });
    renderScreen(engine);

    fireEvent.click(await screen.findByRole("tab", { name: "models" }));
    fireEvent.click((await screen.findAllByRole("button", { name: "delete" }))[0]);
    fireEvent.change(await screen.findByLabelText("Confirm secret"), { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: "confirm write" }));

    // The forwarded call gets Kira's shaped 401, so the dialog explains itself instead of leaving a
    // bare error under a table that still shows the row.
    expect(await screen.findByText(/refused that secret/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "cancel" }));
  });

  it("tells you how to get a studio when there is none", async () => {
    renderScreen(
      fakeEngine({
        studio: {
          root: null,
          available: false,
          image: { available: false, engine: null, detail: "no image engine", models: [] },
          llm: {
            available: false, engine: null, detail: "", models: [], running: false, model: null,
            url: null, model_dir: "C:/data/llm/models", engine_dir: "C:/data/llm/engines",
            reason: "no GGUF model",
          },
          stt: { available: false, engine: null, detail: "", models: [] },
          tts: { available: false, engine: null, detail: "", models: [] },
        },
      }),
    );

    expect(await screen.findByText(/No Portable AI Studio folder was found/)).toBeTruthy();
    expect(screen.getByText("KIRA_STUDIO_DIR")).toBeTruthy();
    expect(screen.getByText("no GGUF model")).toBeTruthy();
  });
});
