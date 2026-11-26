import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OptionsPanel } from "./options-panel.tsx";
import { DEFAULT_LOOK } from "./look.ts";

function mount(overrides: Partial<Parameters<typeof OptionsPanel>[0]> = {}) {
  const props: Parameters<typeof OptionsPanel>[0] = {
    open: true,
    onClose: vi.fn(),
    shell: "chat",
    theme: "charcoal",
    look: DEFAULT_LOOK,
    mode: "AUTO",
    setMode: vi.fn(),
    models: [{ id: "mini", provider: "mock", tier: "fast" } as never],
    model: "mini",
    setModel: vi.fn(),
    health: null,
    sessionId: null,
    sessionCount: 0,
    onRefresh: vi.fn(),
    onDisconnect: vi.fn(),
    ...overrides,
  };
  return { props, view: render(<OptionsPanel {...props} />) };
}

beforeEach(() => localStorage.clear());

describe("options panel", () => {
  it("opens on Theme with the donor's seven themes, in donor order", () => {
    mount();
    const tabs = screen.getAllByRole("tab").map((t) => t.textContent);
    expect(tabs).toEqual(["Theme", "Mode", "Look", "Status"]);
    const tiles = within(
      screen.getByRole("group", { name: "theme" }),
    ).getAllByRole("radio");
    expect(tiles.map((t) => t.textContent)).toEqual([
      "violet",
      "crimson",
      "emerald",
      "celestial",
      "gold",
      "rose",
      "charcoal",
    ]);
    expect(
      screen
        .getByRole("radio", { name: "charcoal" })
        .getAttribute("aria-checked"),
    ).toBe("true");
  });

  it("writes the chosen theme to kira.theme", () => {
    mount();
    fireEvent.click(screen.getByRole("radio", { name: "celestial" }));
    expect(localStorage.getItem("kira.theme")).toBe("celestial");
  });

  it("offers light, dark and system, and writes the mode the user picks", () => {
    mount();
    const group = screen.getByRole("group", { name: "appearance" });
    const modes = within(group).getAllByRole("radio");
    expect(modes.map((mode) => mode.textContent)).toEqual([
      "System",
      "Light",
      "Dark",
    ]);
    expect(
      within(group)
        .getByRole("radio", { name: "System" })
        .getAttribute("aria-checked"),
    ).toBe("true");

    fireEvent.click(within(group).getByRole("radio", { name: "Dark" }));
    expect(localStorage.getItem("kira.appearance")).toBe("dark");
    expect(
      within(group)
        .getByRole("radio", { name: "Dark" })
        .getAttribute("aria-checked"),
    ).toBe("true");
    expect(
      within(group)
        .getByRole("radio", { name: "System" })
        .getAttribute("aria-checked"),
    ).toBe("false");
  });

  it("shows routing mode and models as tiles, and writes the look switches", () => {
    const { props } = mount();
    fireEvent.click(screen.getByRole("tab", { name: /mode/i }));
    fireEvent.click(screen.getByRole("radio", { name: "POWERFUL" }));
    expect(props.setMode).toHaveBeenCalledWith("POWERFUL");
    fireEvent.click(
      screen.getByRole("radio", { name: "use model mini mock fast" }),
    );
    expect(props.setModel).toHaveBeenCalledWith("mini");

    fireEvent.click(screen.getByRole("tab", { name: /look/i }));
    fireEvent.click(screen.getByRole("switch", { name: "glass" }));
    expect(JSON.parse(localStorage.getItem("kira.look")!).glass).toBe(false);
    fireEvent.click(screen.getByRole("radio", { name: "XL" }));
    expect(JSON.parse(localStorage.getItem("kira.look")!).caption).toBe("xl");
  });

  it("shows the session and the provider ledger on Status", () => {
    mount({
      sessionId: "sess-abcdef12",
      sessionCount: 3,
      health: {
        providers: {
          groq: { failures: 0, successes: 4, cooling_s: 0, last_reason: "" },
        },
        configured: [
          {
            name: "groq",
            kind: "openai_compat",
            tier: "fast",
            priority: 50,
            models: ["mini"],
            key_present: true,
            needs_key: true,
          },
        ],
      } as never,
    });
    fireEvent.click(screen.getByRole("tab", { name: /status/i }));
    expect(screen.getByText(/sess-abc/)).toBeTruthy();
    expect(screen.getByText("groq")).toBeTruthy();
    expect(screen.getByText("key ok")).toBeTruthy();
    expect(screen.getByText("4✓ 0✗")).toBeTruthy();
  });

  it("cancels with Escape and closes with the ✕", () => {
    const { props } = mount();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(props.onClose).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "close settings" }));
    expect(props.onClose).toHaveBeenCalledTimes(2);
  });

  it("renders nothing when closed", () => {
    const { view } = mount({ open: false });
    expect(view.container.textContent).toBe("");
  });
});
