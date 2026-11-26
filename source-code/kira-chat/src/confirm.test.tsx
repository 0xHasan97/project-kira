import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { act } from "react";
import { describe, expect, it, vi } from "vitest";
import { ConfirmProvider, useConfirm } from "./confirm.tsx";

function Reader({ label = "ask" }: { label?: string }) {
  const ask = useConfirm();
  return (
    <button
      type="button"
      onClick={() => {
        void ask({ summary: "turn groq off" }).then((answer) => {
          (globalThis as Record<string, unknown>).__answer = answer;
        });
      }}
    >
      {label}
    </button>
  );
}

function lastAnswer(): string | null {
  return (globalThis as Record<string, unknown>).__answer as string | null;
}

function PhraseReader({ phrase = "DELETE ALL" }: { phrase?: string }) {
  const ask = useConfirm();
  return (
    <button
      type="button"
      onClick={() => {
        void ask({ summary: "delete every session", detail: "DELETE /v1/kira/sessions", danger: true, phrase }).then(
          (answer) => {
            (globalThis as Record<string, unknown>).__answer = answer;
          },
        );
      }}
    >
      ask with a phrase
    </button>
  );
}

describe("ConfirmProvider", () => {
  it("holds the answer until the human types the secret", async () => {
    (globalThis as Record<string, unknown>).__answer = "unset";
    render(
      <ConfirmProvider>
        <Reader />
      </ConfirmProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "ask" }));
    expect(await screen.findByText("turn groq off")).toBeTruthy();
    expect(lastAnswer()).toBe("unset");

    fireEvent.change(screen.getByLabelText("Confirm secret"), { target: { value: "s3cret" } });
    fireEvent.click(screen.getByRole("button", { name: "confirm write" }));
    await waitFor(() => expect(lastAnswer()).toBe("s3cret"));
  });

  it("answers null on cancel and writes nothing anywhere", async () => {
    (globalThis as Record<string, unknown>).__answer = "unset";
    const storage = vi.spyOn(Storage.prototype, "setItem");
    render(
      <ConfirmProvider>
        <Reader />
      </ConfirmProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "ask" }));
    fireEvent.change(screen.getByLabelText("Confirm secret"), { target: { value: "typedin" } });
    fireEvent.click(screen.getByRole("button", { name: "cancel" }));
    await waitFor(() => expect(lastAnswer()).toBeNull());
    expect(storage).not.toHaveBeenCalled();
    expect(document.cookie).toBe("");
    expect(screen.queryByDisplayValue("typedin")).toBeNull();
  });

  it("asks again for the next write - it never remembers the last secret", async () => {
    (globalThis as Record<string, unknown>).__answer = "unset";
    render(
      <ConfirmProvider>
        <Reader />
      </ConfirmProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "ask" }));
    fireEvent.change(screen.getByLabelText("Confirm secret"), { target: { value: "first" } });
    fireEvent.click(screen.getByRole("button", { name: "confirm write" }));
    await waitFor(() => expect(lastAnswer()).toBe("first"));

    fireEvent.click(screen.getByRole("button", { name: "ask" }));
    expect((screen.getByLabelText("Confirm secret") as HTMLInputElement).value).toBe("");
  });

  it("refuses a second ask while one is open instead of deadlocking", async () => {
    (globalThis as Record<string, unknown>).__answer = "unset";
    render(
      <ConfirmProvider>
        <Reader />
        <Reader label="ask again" />
      </ConfirmProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "ask" }));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "ask again" }));
    });
    expect(lastAnswer()).toBeNull();
    expect(screen.getByText("turn groq off")).toBeTruthy();
  });

  it("throws when a screen forgets the provider", () => {
    expect(() => render(<Reader />)).toThrow(/ConfirmProvider/);
  });

  it("will not submit a phrase request until the words match exactly", async () => {
    (globalThis as Record<string, unknown>).__answer = "unset";
    render(
      <ConfirmProvider>
        <PhraseReader />
      </ConfirmProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "ask with a phrase" }));
    const phrase = await screen.findByLabelText("Type DELETE ALL to allow this");
    const submit = screen.getByRole("button", { name: "confirm write" });

    fireEvent.change(phrase, { target: { value: "delete all" } });
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(phrase, { target: { value: "DELETE ALL " } });
    expect((submit as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(phrase, { target: { value: "DELETE ALL" } });
    expect((submit as HTMLButtonElement).disabled).toBe(false);
    fireEvent.change(screen.getByLabelText("Confirm secret"), { target: { value: "s3cret" } });
    fireEvent.click(submit);
    await waitFor(() => expect(lastAnswer()).toBe("s3cret"));
  });

  it("keeps the words in the dialog: the answer is the secret alone", async () => {
    (globalThis as Record<string, unknown>).__answer = "unset";
    render(
      <ConfirmProvider>
        <PhraseReader />
      </ConfirmProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "ask with a phrase" }));
    fireEvent.change(await screen.findByLabelText("Type DELETE ALL to allow this"), { target: { value: "DELETE ALL" } });
    fireEvent.change(screen.getByLabelText("Confirm secret"), { target: { value: "only-this" } });
    fireEvent.click(screen.getByRole("button", { name: "confirm write" }));
    await waitFor(() => expect(lastAnswer()).toBe("only-this"));
    expect(lastAnswer()).not.toMatch(/DELETE ALL/);
    expect(screen.queryByDisplayValue("DELETE ALL")).toBeNull();
  });

  it("holds the words even when the form is submitted by a keystroke", async () => {
    (globalThis as Record<string, unknown>).__answer = "unset";
    render(
      <ConfirmProvider>
        <PhraseReader />
      </ConfirmProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "ask with a phrase" }));
    await screen.findByLabelText("Type DELETE ALL to allow this");
    fireEvent.change(screen.getByLabelText("Confirm secret"), { target: { value: "s3cret" } });
    // Enter in a text input submits its form, which a disabled button alone does not stop.
    fireEvent.keyDown(screen.getByLabelText("Confirm secret"), { key: "Enter", code: "Enter" });
    fireEvent.submit(screen.getByLabelText("Confirm secret").closest("form")!);
    await waitFor(() => expect(lastAnswer()).toBe("unset"));
    expect(screen.getByText("type DELETE ALL exactly, or cancel")).toBeTruthy();
  });
});
