import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CommandPalette } from "./command-palette.tsx";
import type { PaletteCommand } from "./command-palette.tsx";

function command(overrides: Partial<PaletteCommand>): PaletteCommand {
  return { id: "go-chat", label: "Go to Chat", hint: "Create", group: "Go", run: vi.fn(), ...overrides };
}

function setup(open = true) {
  const onClose = vi.fn();
  const chat = command({ id: "go-chat", label: "Go to Chat", run: vi.fn() });
  const sessions = command({ id: "go-sessions", label: "Go to Sessions", hint: "Workspace", run: vi.fn() });
  const newChat = command({ id: "new-chat", label: "New chat", hint: "Start fresh", group: "Do", run: vi.fn() });
  render(<CommandPalette open={open} commands={[newChat, chat, sessions]} onClose={onClose} />);
  return { onClose, chat, sessions, newChat };
}

describe("CommandPalette", () => {
  it("lists actions and routes, and filters both", () => {
    setup();
    expect(screen.getByText("Actions")).toBeTruthy();
    expect(screen.getByText("Go to")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Search commands"), { target: { value: "sessions" } });
    expect(screen.queryByText("New chat")).toBeNull();
    expect(screen.getByText("Go to Sessions")).toBeTruthy();
  });

  it("moves with the arrows and opens the highlighted row with Enter", () => {
    const { onClose, chat } = setup();
    const input = screen.getByLabelText("Search commands");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onClose).toHaveBeenCalledOnce();
    expect(chat.run).toHaveBeenCalledOnce();
  });

  it("closes on Escape without running anything", () => {
    const { onClose, newChat } = setup();
    fireEvent.keyDown(screen.getByLabelText("Search commands"), { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
    expect(newChat.run).not.toHaveBeenCalled();
  });

  it("runs a clicked action and says when the search is empty", () => {
    const { onClose, newChat } = setup();
    fireEvent.click(screen.getByText("New chat"));
    expect(onClose).toHaveBeenCalledOnce();
    expect(newChat.run).toHaveBeenCalledOnce();
  });

  it("writes what was typed when there is no match", () => {
    setup();
    fireEvent.change(screen.getByLabelText("Search commands"), { target: { value: "zzz" } });
    expect(screen.getByText(/No route or action matches/)).toBeTruthy();
    expect(screen.getByText(/zzz/)).toBeTruthy();
  });

  it("renders nothing while closed", () => {
    const { container } = render(
      <CommandPalette open={false} commands={[]} onClose={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
  });
});
