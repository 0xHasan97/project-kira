import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { KiraClient } from "../api.ts";
import { ConfirmProvider } from "../confirm.tsx";
import { API_PREFIX } from "../contracts.ts";
import { ELLEN_ID, FAKE_CONFIRM, fakeEngine, PROPS_ID } from "../fake-engine.ts";
import { AvatarScreen } from "./AvatarScreen.tsx";

type Engine = ReturnType<typeof fakeEngine>;

function clientFor(engine: Engine): KiraClient {
  vi.stubGlobal("fetch", engine.fetch);
  return new KiraClient({ baseUrl: "http://127.0.0.1:8901", token: "sekret" });
}

function renderScreen(engine: Engine) {
  return render(<ConfirmProvider><AvatarScreen client={clientFor(engine)} connected /></ConfirmProvider>);
}

const callTo = (engine: Engine, method: string, path: string) =>
  engine.calls.find((call) => call.method === method && call.url === `${API_PREFIX}${path}`);

async function confirmWith(secret = FAKE_CONFIRM) {
  fireEvent.change(await screen.findByLabelText("Confirm secret"), { target: { value: secret } });
  fireEvent.click(screen.getByRole("button", { name: "confirm write" }));
}

beforeEach(() => {
  localStorage.clear();
});

describe("AvatarScreen", () => {
  it("shows the walk's own reading of each character, absent texture included", async () => {
    renderScreen(fakeEngine());

    expect(await screen.findByText("ellen")).toBeTruthy();
    expect(screen.getByText("7/8 — hair.bmp absent")).toBeTruthy();
    expect(screen.getByText("26,798 vertices")).toBeTruthy();
    expect(screen.getByText("101 bones · physics · 1 prop")).toBeTruthy();
    expect(screen.getByText(/redistribution not permitted/)).toBeTruthy();
  });

  it("calls a props-only archive what it is and offers it no stage", async () => {
    renderScreen(fakeEngine());

    expect(await screen.findByText("props only")).toBeTruthy();
    expect(screen.getByText(/no model in the archive passed the body test/)).toBeTruthy();
    // A dead button explains nothing, so the row says why instead.
    expect(screen.getByText("no body to stage")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "use 小道具" })).toBeNull();
  });

  it("puts the picked body on the pane, and admits what the window cannot draw", async () => {
    renderScreen(fakeEngine());

    expect(await screen.findByText("on stage")).toBeTruthy();
    // The pane now mounts the stage for real — loader, textures, renderer — and jsdom has no GL, which is
    // the same hole a locked-down WebView2 has. The screen says so in one line and keeps working.
    const stage = await screen.findByText(/cannot draw 3D/);
    expect(stage.closest(".stage-pane")).toBeTruthy();
    expect(screen.queryByText(/Nothing draws on this pane/)).toBeNull();
  });

  it("leaves the pane no prose to push its control below the fold", async () => {
    // Measured in the 2026-11-02 browser pass: the card's own scroll window ended above the
    // "take everyone off" button because two explanatory paragraphs and the findings list shared the
    // column with it. The control is the pane's business; the prose is the library's.
    renderScreen(fakeEngine());

    const stage = await screen.findByText(/cannot draw 3D/);
    const pane = stage.closest(".stage-pane") as HTMLElement;
    const off = screen.getByRole("button", { name: "take everyone off" });
    expect(off.compareDocumentPosition(pane.querySelector(".avatar-stage") as HTMLElement) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(pane.textContent).not.toMatch(/same body the call speaks with/);
    expect(screen.getByText(/same body the call speaks with/)).toBeTruthy();
  });

  it("says the library is empty, names the licence rule, and keeps the path field", async () => {
    renderScreen(fakeEngine({ characters: { characters: [], active: null } }));

    expect(await screen.findByText(/Kira ships no model and never will/)).toBeTruthy();
    expect(screen.getByText(/licensed to install/)).toBeTruthy();
    expect(screen.getByLabelText(/already on this machine/)).toBeTruthy();
    expect(screen.getByText(/no face yet/)).toBeTruthy();
  });

  it("puts a body on the stage with the pick route and no confirm secret", async () => {
    const engine = fakeEngine({ active: null });
    renderScreen(engine);

    fireEvent.click(await screen.findByRole("button", { name: "use ellen" }));

    await waitFor(() => expect(screen.getByText("on stage")).toBeTruthy());
    const pick = callTo(engine, "PUT", "/kira/characters/active");
    expect(JSON.parse(String(pick?.body))).toEqual({ id: ELLEN_ID });
    // A pick replaces nothing, so the engine gates it on the bearer token alone — and a screen that
    // asked for the secret here would be making the human type it for nothing.
    expect(pick?.headers["X-Kira-Confirm"]).toBeUndefined();
    expect(engine.calls.every((call) => call.headers.Authorization === "Bearer sekret")).toBe(true);
  });

  it("takes everyone off the stage with a real null, not an empty string", async () => {
    const engine = fakeEngine();
    renderScreen(engine);

    fireEvent.click(await screen.findByRole("button", { name: "take everyone off" }));

    await waitFor(() => expect(screen.getByText(/no face yet/)).toBeTruthy());
    expect(JSON.parse(String(callTo(engine, "PUT", "/kira/characters/active")?.body))).toEqual({ id: null });
  });

  it("imports from a path typed on this machine without a secret, and reads the library back", async () => {
    const engine = fakeEngine();
    renderScreen(engine);

    fireEvent.change(screen.getByLabelText(/already on this machine/), { target: { value: "D:\\models\\new.zip" } });
    fireEvent.click(screen.getByRole("button", { name: "import" }));

    expect(await screen.findByText("new")).toBeTruthy();
    const posted = callTo(engine, "POST", "/kira/characters");
    expect(JSON.parse(String(posted?.body))).toEqual({ path: "D:\\models\\new.zip" });
    expect(posted?.headers["X-Kira-Confirm"]).toBeUndefined();
    expect(screen.queryByLabelText("Confirm secret")).toBeNull();
    // The engine's answer is the row and the screen opens it: what you just imported is the thing you
    // want measured, and a folder walk is the only place the texture and morph readings live.
    expect(engine.calls.some((call) => call.url === `${API_PREFIX}/kira/characters/new-00000000`)).toBe(true);
  });

  it("keeps the importer's own refusal, code and all", async () => {
    const engine = fakeEngine({
      importError: {
        code: "already_imported",
        message: `those bytes are already in the library as '${ELLEN_ID}'`,
        status: 409,
        retryable: false,
      },
    });
    renderScreen(engine);

    fireEvent.change(screen.getByLabelText(/already on this machine/), { target: { value: "D:\\models\\ellen.zip" } });
    fireEvent.click(screen.getByRole("button", { name: "import" }));

    expect((await screen.findByRole("alert")).textContent).toContain("already_imported");
    // The bytes stayed out of the library, so the table still has the two rows it started with.
    expect(engine.calls.some((call) => call.method === "POST")).toBe(true);
    expect(screen.getByText("7/8 — hair.bmp absent")).toBeTruthy();
  });

  it("asks for the typed secret before it deletes 45 MB, then drops the row and its pick", async () => {
    const engine = fakeEngine();
    renderScreen(engine);

    fireEvent.click(await screen.findByRole("button", { name: "remove ellen" }));
    await confirmWith();

    await waitFor(() => expect(screen.getByText(/no face yet/)).toBeTruthy());
    expect(screen.queryByText("7/8 — hair.bmp absent")).toBeNull();
    expect(callTo(engine, "DELETE", `/kira/characters/${ELLEN_ID}`)?.headers["X-Kira-Confirm"]).toBe(FAKE_CONFIRM);
    // A removal takes one folder, not the library.
    expect(await screen.findByText("props only")).toBeTruthy();
  });

  it("re-asks rather than leaving a bare 401 in a table cell", async () => {
    const engine = fakeEngine({ confirm: "another-secret" });
    renderScreen(engine);

    fireEvent.click(await screen.findByRole("button", { name: "remove ellen" }));
    await confirmWith();
    expect(await screen.findByText(/refused that secret; type it again/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "cancel" }));
    expect(engine.calls.some((call) => call.method === "DELETE")).toBe(true);
    expect(screen.getByText("7/8 — hair.bmp absent")).toBeTruthy();
  });

  it("opens the walk: measurements, the texture table, the morphs a mouth needs", async () => {
    const engine = fakeEngine();
    renderScreen(engine);

    fireEvent.click(await screen.findByRole("button", { name: "measure ellen" }));

    expect(await screen.findByText(/1 texture the model names and the archive never carried/)).toBeTruthy();
    expect(screen.getByText("tex/颜.tga")).toBeTruthy();
    expect(screen.getByText(/42.9 MB archive/)).toBeTruthy();
    expect(screen.getByText(/PMX 2.1/)).toBeTruthy();
    expect(screen.getByText(/あ, い, う/)).toBeTruthy();
    expect(screen.getByText("model.pmx")).toBeTruthy();
    expect(engine.calls.some((call) => call.url === `${API_PREFIX}/kira/characters/${ELLEN_ID}`)).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "hide ellen" }));
    expect(screen.queryByText(/42.9 MB archive/)).toBeNull();
  });

  it("opens a props archive's own walk, so the reason is the model's and not the screen's", async () => {
    const engine = fakeEngine();
    renderScreen(engine);

    fireEvent.click(await screen.findByRole("button", { name: "measure 小道具" }));

    expect(await screen.findByText(/this archive has no body/)).toBeTruthy();
    expect(screen.getByText(/the 1 model in it is props/)).toBeTruthy();
    expect(engine.calls.some((call) => call.url === `${API_PREFIX}/kira/characters/${PROPS_ID}`)).toBe(true);
  });

  it("keeps the import dead until a path is typed", async () => {
    renderScreen(fakeEngine());
    const button = (await screen.findByRole("button", { name: "import" })) as HTMLButtonElement;

    expect(button.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/already on this machine/), { target: { value: "  " } });
    expect(button.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/already on this machine/), { target: { value: "D:\\m\\a.zip" } });
    expect(button.disabled).toBe(false);
  });

  it("reads the library again when the rail is pulled, rather than holding its own copy", async () => {
    const engine = fakeEngine();
    const client = clientFor(engine);
    const { rerender } = render(
      <ConfirmProvider>
        <AvatarScreen client={client} connected pull={0} />
      </ConfirmProvider>,
    );
    await screen.findByText("ellen");

    rerender(
      <ConfirmProvider>
        <AvatarScreen client={client} connected pull={1} />
      </ConfirmProvider>,
    );

    await waitFor(() =>
      expect(engine.calls.filter((call) => call.url === `${API_PREFIX}/kira/characters`).length).toBe(2),
    );
  });
});
