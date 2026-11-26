import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import {
  BUILTIN_PROMPTS,
  PromptsScreen,
  fillPrompt,
  variablesIn,
} from "./PromptsScreen.tsx";

beforeEach(() => {
  localStorage.clear();
});

describe("prompt variables", () => {
  it("finds each placeholder once, in order", () => {
    expect(variablesIn("From {url} to {name}, again {url}.")).toEqual(["url", "name"]);
  });

  it("fills only values that were given", () => {
    expect(fillPrompt("Read {url} for {name}.", { url: " example.com " })).toBe(
      "Read example.com for {name}.",
    );
  });
});

describe("PromptsScreen", () => {
  it("lists the built-in prompts", () => {
    render(<PromptsScreen onUse={vi.fn()} />);
    expect(screen.getByRole("heading", { name: "Prompts" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Summarize" })).toBeTruthy();
    expect(screen.getByText(`${BUILTIN_PROMPTS.length} of ${BUILTIN_PROMPTS.length} prompts`)).toBeTruthy();
  });

  it("filters by search and by category", () => {
    render(<PromptsScreen onUse={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("search prompts"), {
      target: { value: "translate" },
    });
    expect(screen.getByRole("heading", { name: "Translate to Spanish" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Summarize" })).toBeNull();

    fireEvent.change(screen.getByLabelText("search prompts"), { target: { value: "" } });
    fireEvent.change(screen.getByLabelText("prompt category"), {
      target: { value: "Code" },
    });
    expect(screen.getByRole("heading", { name: "Code review" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Summarize" })).toBeNull();
  });

  it("hands a plain prompt to chat", () => {
    const onUse = vi.fn();
    render(<PromptsScreen onUse={onUse} />);
    fireEvent.click(screen.getByRole("button", { name: "use Summarize" }));
    expect(onUse).toHaveBeenCalledWith(
      "Summarize the following in three sentences. No preamble.\n\n",
    );
  });

  it("will not use a prompt until every value is filled", () => {
    const onUse = vi.fn();
    render(<PromptsScreen onUse={onUse} />);
    const use = screen.getByRole("button", { name: "use Draft a reply" });
    expect((use as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(screen.getByLabelText("Draft a reply message"), {
      target: { value: "Can we meet Friday?" },
    });
    expect((use as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(use);
    expect(onUse).toHaveBeenCalledWith(
      "Draft a professional reply to this message. Keep it short and answer every question.\n\nCan we meet Friday?",
    );
  });

  it("saves a custom prompt and deletes it without a dialog", () => {
    render(<PromptsScreen onUse={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "new prompt" }));
    fireEvent.change(screen.getByLabelText("prompt title"), {
      target: { value: "Meeting notes" },
    });
    fireEvent.change(screen.getByLabelText("prompt instruction"), {
      target: { value: "Turn these notes into decisions:\n\n" },
    });
    fireEvent.click(screen.getByRole("button", { name: "save prompt" }));

    expect(screen.getByRole("heading", { name: "Meeting notes" })).toBeTruthy();
    const stored = JSON.parse(localStorage.getItem("kira.prompts") ?? "[]");
    expect(stored).toHaveLength(1);
    expect(stored[0].title).toBe("Meeting notes");

    fireEvent.click(screen.getByRole("button", { name: "delete Meeting notes" }));
    expect(screen.queryByRole("heading", { name: "Meeting notes" })).toBeNull();
    expect(JSON.parse(localStorage.getItem("kira.prompts") ?? "[]")).toHaveLength(0);
  });
});
