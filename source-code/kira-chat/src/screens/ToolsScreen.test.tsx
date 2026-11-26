import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ConfirmProvider } from "../confirm.tsx";
import { ToolsScreen } from "./ToolsScreen.tsx";

const tools = {
  tools: [
    { name: "read_file", description: "read", parameters: {}, risk: "read", source: "builtin", default_policy: "allow", policy: "allow", overridden: false },
    { name: "write_file", description: "write", parameters: {}, risk: "write", source: "builtin", default_policy: "ask", policy: "deny", overridden: true },
  ],
  plugins: [{ file: "demo.json", name: "demo_lookup", status: "skipped", reason: "name must match …" }],
};

function client() {
  return {
    tools: vi.fn().mockResolvedValue(tools),
    checkpoints: vi.fn().mockResolvedValue({
      checkpoints: [
        {
          id: "cp1",
          tool: "write_file",
          call_id: "call_1",
          status: "complete",
          files: [{ path: "a.txt", existed: true, changed: true }],
          created_at: 1,
        },
      ],
    }),
    setToolPolicy: vi.fn().mockResolvedValue({ tool: { name: "write_file", policy: "allow", overridden: true } }),
    restoreCheckpoint: vi.fn().mockResolvedValue({ restored: ["a.txt"], conflicts: [], checkpoint_id: "cp2" }),
  } as never;
}

function typeSecret(value: string) {
  fireEvent.change(screen.getByLabelText(/confirm secret/i), { target: { value } });
}

describe("ToolsScreen", () => {
  it("lists tools, plugins and checkpoints", async () => {
    render(<ConfirmProvider><ToolsScreen client={client()} connected /></ConfirmProvider>);
    expect(await screen.findByText("read_file")).toBeTruthy();
    expect(screen.getByText("write_file")).toBeTruthy();
    expect(screen.getByText(/demo_lookup/)).toBeTruthy();
    expect(screen.getByText(/name must match/)).toBeTruthy();
    expect(screen.getByText("cp1")).toBeTruthy();
  });

  it("routes a policy change through the confirm dialog", async () => {
    const fake = client();
    render(<ConfirmProvider><ToolsScreen client={fake} connected /></ConfirmProvider>);
    await screen.findByText("write_file");
    fireEvent.change(screen.getByLabelText("policy for write_file"), { target: { value: "allow" } });
    typeSecret("s3cret");
    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));
    await waitFor(() =>
      expect((fake as never as { setToolPolicy: ReturnType<typeof vi.fn> }).setToolPolicy).toHaveBeenCalledWith(
        "write_file",
        "allow",
        "s3cret",
      ),
    );
  });

  it("restores a checkpoint after the same dialog", async () => {
    const fake = client();
    render(<ConfirmProvider><ToolsScreen client={fake} connected /></ConfirmProvider>);
    await screen.findByText("cp1");
    fireEvent.click(screen.getByRole("button", { name: "restore cp1" }));
    typeSecret("s3cret");
    fireEvent.click(screen.getByRole("button", { name: /confirm/i }));
    await waitFor(() =>
      expect((fake as never as { restoreCheckpoint: ReturnType<typeof vi.fn> }).restoreCheckpoint).toHaveBeenCalledWith(
        "cp1",
        "s3cret",
      ),
    );
    expect(await screen.findByText("restored 1 file(s)")).toBeTruthy();
  });

  it("says it cannot read the registry instead of showing an empty table", async () => {
    const failing = {
      tools: vi.fn().mockRejectedValue(new Error("engine down")),
      checkpoints: vi.fn().mockResolvedValue({ checkpoints: [] }),
    } as never;
    render(<ConfirmProvider><ToolsScreen client={failing} connected /></ConfirmProvider>);
    expect((await screen.findByText(/cannot read the tool registry/)).textContent).toContain("engine down");
  });
});
