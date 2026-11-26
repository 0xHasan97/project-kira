import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { KiraClient } from "../api.ts";
import { ConfirmProvider } from "../confirm.tsx";
import { API_PREFIX } from "../contracts.ts";
import { FAKE_CONFIRM, fakeEngine, imageOutputFixture, imagesFixture } from "../fake-engine.ts";
import { ImagesScreen } from "./ImagesScreen.tsx";

type Engine = ReturnType<typeof fakeEngine>;

function clientFor(engine: Engine): KiraClient {
  vi.stubGlobal("fetch", engine.fetch);
  return new KiraClient({ baseUrl: "http://127.0.0.1:8901", token: "sekret" });
}

function renderScreen(engine: Engine) {
  return render(
    <ConfirmProvider>
      <ImagesScreen client={clientFor(engine)} connected />
    </ConfirmProvider>,
  );
}

const callTo = (engine: Engine, method: string, path: string) =>
  engine.calls.find((call) => call.method === method && call.url === `${API_PREFIX}${path}`);

beforeEach(() => {
  // jsdom implements no object URLs; the screen hands the fetched bytes to the browser as a blob.
  URL.createObjectURL = vi.fn(() => "blob:kira-image");
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ImagesScreen", () => {
  it("says what is missing and where to put it, instead of showing a dead form", async () => {
    renderScreen(
      fakeEngine({
        images: {
          ...(imagesFixture() as object),
          ready: false,
          backend: null,
          backend_path: null,
          models: [],
          outputs: [],
          reason: "no image engine: put stable-diffusion.cpp's executable in C:/kira/images/engines",
        },
      }),
    );

    expect(await screen.findByText(/no image engine/)).toBeTruthy();
    expect(screen.getByText("C:/kira/images/engines")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "generate" })).toBeNull();
  });

  it("draws one picture and shows the row the gallery will hold", async () => {
    const generated = {
      ...(imageOutputFixture() as Record<string, unknown>),
      name: "img-20260101-120001-cat.png",
      url: "/v1/kira/images/file/img-20260101-120001-cat.png",
      prompt: "a cat asleep on a keyboard",
      seed: 777,
    };
    const engine = fakeEngine({ generated, imageFiles: { "img-20260101-120001-cat.png": new Uint8Array([0x89, 0x50, 0x4e, 0x47]) } });
    renderScreen(engine);

    fireEvent.change(await screen.findByLabelText("prompt"), { target: { value: "a cat asleep on a keyboard" } });
    fireEvent.click(screen.getByRole("button", { name: "generate" }));
    fireEvent.change(await screen.findByLabelText("Confirm secret"), { target: { value: FAKE_CONFIRM } });
    fireEvent.click(screen.getByRole("button", { name: "confirm write" }));

    expect(await screen.findByRole("img", { name: "a cat asleep on a keyboard" })).toBeTruthy();
    expect(screen.getAllByText(/seed/).length).toBeGreaterThan(0);
    const post = callTo(engine, "POST", "/kira/images/generate");
    expect(post).toBeTruthy();
    expect(post?.headers["X-Kira-Confirm"]).toBe(FAKE_CONFIRM);
    expect(JSON.parse(post!.body ?? "{}")).toMatchObject({
      prompt: "a cat asleep on a keyboard",
      model: "sd15",
      width: 512,
      height: 512,
    });
  });

  it("reports an engine failure in the form instead of pretending a picture exists", async () => {
    renderScreen(
      fakeEngine({
        imageError: { code: "image_backend_missing", message: "no engine executable", status: 503, retryable: false },
      }),
    );

    fireEvent.change(await screen.findByLabelText("prompt"), { target: { value: "a lighthouse" } });
    fireEvent.click(screen.getByRole("button", { name: "generate" }));
    fireEvent.change(await screen.findByLabelText("Confirm secret"), { target: { value: FAKE_CONFIRM } });
    fireEvent.click(screen.getByRole("button", { name: "confirm write" }));

    expect(await screen.findByText(/no engine executable/)).toBeTruthy();
    expect(screen.queryByRole("img", { name: "a lighthouse" })).toBeNull();
  });

  it("deletes through the confirm dialog and sends the secret in the header", async () => {
    const engine = fakeEngine();
    renderScreen(engine);

    const buttons = await screen.findAllByRole("button", { name: "delete" });
    fireEvent.click(buttons[0]!);
    fireEvent.change(await screen.findByLabelText("Confirm secret"), { target: { value: FAKE_CONFIRM } });
    fireEvent.click(screen.getByRole("button", { name: "confirm write" }));

    await waitFor(() => {
      const call = callTo(engine, "DELETE", "/kira/images/img-20260101-120000-abc123.png");
      expect(call?.headers["X-Kira-Confirm"]).toBe(FAKE_CONFIRM);
    });
  });
});
